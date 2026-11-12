import json
import io
import threading
from contextlib import contextmanager
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pymupdf
from fastapi import HTTPException, UploadFile
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NullObject, NumberObject, TextStringObject
import main
import pdf_jobs


@contextmanager
def occupied_pdf_slot():
    ready, release = threading.Event(), threading.Event()
    def hold():
        with pdf_jobs._pdf_job_lock:
            ready.set()
            release.wait(timeout=20)
    thread = threading.Thread(target=hold)
    thread.start()
    assert ready.wait(timeout=5)
    try:
        yield
    finally:
        release.set()
        thread.join(timeout=5)


class PdfProcessingTests(unittest.TestCase):
    def test_null_and_indirect_annotations_preserve_valid_links(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'annotations.pdf'
            writer = PdfWriter()
            for _ in range(4):
                writer.add_blank_page(width=612, height=792)
            writer.pages[0][NameObject('/Annots')] = NullObject()
            writer.pages[1][NameObject('/Annots')] = writer._add_object(NullObject())
            annotation = DictionaryObject({NameObject('/Subtype'): NameObject('/Link'),
                NameObject('/Rect'): ArrayObject([NumberObject(n) for n in (10, 10, 100, 100)]),
                NameObject('/A'): DictionaryObject({NameObject('/S'): NameObject('/URI'),
                    NameObject('/URI'): TextStringObject('https://example.com/')})})
            writer.pages[2][NameObject('/Annots')] = writer._add_object(ArrayObject([writer._add_object(annotation), NullObject()]))
            writer.write(path)
            links = main.extract_pdf_links(path, 4)
            self.assertEqual(len(links), 1)
            self.assertEqual(links[0]['source_page_number'], 3)
            self.assertEqual(links[0]['uri'], 'https://example.com/')
            self.assertEqual(main.refresh_embedded_links('test-book', {'original_pdf_path':str(path), 'page_count':4})['links'], links)

    def test_real_child_renders_batches_and_returns_only_metadata(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(main, 'active_storage_path', Path(directory)):
            source = Path(directory) / 'source.pdf'
            with pymupdf.open() as document:
                for index in range(3):
                    document.new_page().insert_text((40,40), f'Page {index+1}')
                document.save(source)
            self.assertEqual(main.get_pdf_page_count(source), 3)
            first = main.render_pdf_page_range('test-book', source, 1, 2)
            second = main.render_pdf_page_range('test-book', source, 3, 2)
            self.assertEqual(first['next_start_page'], 3)
            self.assertIsNone(second['next_start_page'])
            self.assertEqual(len(list((Path(directory)/'test-book'/'pages').glob('*.jpg'))), 3)
            self.assertTrue((Path(directory)/'test-book'/'covers'/'cover.jpg').is_file())
            for image in (Path(directory)/'test-book'/'pages').glob('*.jpg'):
                self.assertGreater(pymupdf.Pixmap(str(image)).width, 0)
            self.assertEqual(main.render_pdf_page_range('test-book', source, 4, 2)['rendered_pages'], [])
            with self.assertRaises(HTTPException) as error:
                main.render_pdf_page_range('test-book', source, 1, 26)
            self.assertEqual(error.exception.status_code,400)

    def test_busy_job_does_not_spawn(self):
        with occupied_pdf_slot(), patch.object(pdf_jobs.subprocess, 'run') as run:
            with self.assertRaises(HTTPException) as error:
                pdf_jobs.run_pdf_job('page_count', {'pdf_path':'unused'})
            self.assertEqual(error.exception.status_code,409)
            run.assert_not_called()

    def test_timeout_crash_and_bad_result_release_lock(self):
        for outcome in (subprocess.TimeoutExpired('python',180), OSError('cannot start'),
                        SimpleNamespace(returncode=9), SimpleNamespace(returncode=0)):
            with self.subTest(outcome=outcome), patch.object(pdf_jobs.subprocess,'run') as run:
                if isinstance(outcome,Exception): run.side_effect=outcome
                else: run.return_value=outcome
                with self.assertRaises(HTTPException) as error:
                    pdf_jobs.run_pdf_job('page_count', {'pdf_path':'unused'})
                self.assertEqual(error.exception.status_code,503)
                acquired=[]
                def probe_lock():
                    success=pdf_jobs._pdf_job_lock.acquire(blocking=False)
                    acquired.append(success)
                    if success: pdf_jobs._pdf_job_lock.release()
                probe=threading.Thread(target=probe_lock)
                probe.start();probe.join(timeout=5)
                self.assertEqual(acquired,[True])

    def test_failed_render_does_not_update_manifest(self):
        manifest={'original_pdf_path':'unused','links':[], 'link_extraction_checked_at':'already', 'pages':[]}
        with patch.object(main,'read_manifest',return_value=manifest), patch.object(main,'render_pdf_page_range',side_effect=HTTPException(503,'failed')), patch.object(main,'write_manifest') as write:
            with self.assertRaises(HTTPException): main.process_publication_batch('test-book',1,5)
            write.assert_not_called()

    def test_transient_link_worker_error_is_not_marked_checked(self):
        for status in (409,503):
            manifest={'original_pdf_path':'unused','links':[], 'pages':[]}
            with patch.object(main,'read_manifest',return_value=manifest), patch.object(main,'refresh_embedded_links',side_effect=HTTPException(status,'retry')), patch.object(main,'render_pdf_page_range') as render, patch.object(main,'write_manifest') as write:
                with self.assertRaises(HTTPException): main.process_publication_batch('test-book',1,5)
                self.assertNotIn('link_extraction_checked_at',manifest)
                render.assert_not_called()
                write.assert_not_called()

    def test_busy_upload_and_full_processing_preserve_existing_files(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(main,'active_storage_path',Path(directory)):
            book=Path(directory)/'test-book';book.mkdir()
            (book/'pages').mkdir();(book/'thumbs').mkdir()
            files={'original.pdf':b'original', 'manifest.json':b'{"original":true}',
                   'pages/page-001.jpg':b'page', 'thumbs/page-001.jpg':b'thumb'}
            for name,content in files.items(): (book/name).write_bytes(content)
            with occupied_pdf_slot():
                calls=[lambda:main.save_publication_upload(slug='test-book',file=UploadFile(io.BytesIO(b'replacement'),filename='test.pdf')),
                       lambda:main.render_pdf_assets('test-book',book/'original.pdf'),
                       lambda:main.process_publication_pdf('test-book')]
                for call in calls:
                    with self.assertRaises(HTTPException) as error: call()
                    self.assertEqual(error.exception.status_code,409)
                    for name,content in files.items(): self.assertEqual((book/name).read_bytes(),content)

    def test_invalid_replacement_preserves_existing_files(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(main,'active_storage_path',Path(directory)):
            book=Path(directory)/'test-book';book.mkdir();(book/'pages').mkdir()
            files={'original.pdf':b'original','manifest.json':b'{"original":true}','pages/page-001.jpg':b'page'}
            for name,content in files.items(): (book/name).write_bytes(content)
            with self.assertRaises(HTTPException) as error:
                main.save_publication_upload(slug='test-book',file=UploadFile(io.BytesIO(b'not a pdf'),filename='test.pdf'))
            self.assertEqual(error.exception.status_code,400)
            for name,content in files.items(): self.assertEqual((book/name).read_bytes(),content)
            self.assertEqual(sorted(p.name for p in book.glob('*.pdf')),['original.pdf'])

    def test_malformed_links_still_allow_batch_rendering(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(main,'active_storage_path',Path(directory)):
            path=Path(directory)/'bad-link.pdf'
            writer=PdfWriter();page=writer.add_blank_page(width=612,height=792)
            annotation=DictionaryObject({NameObject('/Subtype'):NameObject('/Link'),
                NameObject('/Rect'):ArrayObject([TextStringObject('bad'),NumberObject(0),NumberObject(100),NumberObject(100)])})
            page[NameObject('/Annots')]=ArrayObject([writer._add_object(annotation)])
            writer.write(path)
            main.write_manifest('test-book',{'slug':'test-book','original_pdf_path':str(path),'page_count':1,'pages':[],'links':[]})
            result=main.process_publication_batch('test-book',1,5)
            self.assertEqual(result['status'],'processed')
            self.assertEqual(result['link_count'],0)
            self.assertTrue((Path(directory)/'test-book'/'pages'/'page-001.jpg').is_file())
