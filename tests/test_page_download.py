import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pymupdf
from fastapi import HTTPException
import main


class PageDownloadTests(unittest.TestCase):
    def test_ranges_and_duplicates(self):
        self.assertEqual(main.parse_page_selection('2, 5, 7, 9, 14-17, 5', 20),
                         [1, 4, 6, 8, 13, 14, 15, 16])

    def test_invalid_ranges(self):
        for value in ('', '0', '21', '4-2', '2,,3', 'abc', '-1', '1-999999999'):
            with self.assertRaises(HTTPException):
                main.parse_page_selection(value, 20)

    def test_pdf_contains_only_requested_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.pdf'
            with pymupdf.open() as doc:
                for number in range(1, 6):
                    doc.new_page().insert_text((40, 40), f'Page {number}')
                doc.save(source)
            with patch.object(main, 'read_manifest', return_value={'original_pdf_path': str(source)}):
                response = main.download_selected_pages('test-book', '2,4-5')
            try:
                with pymupdf.open(response.path) as doc:
                    self.assertEqual(len(doc), 3)
                    self.assertEqual([p.get_text().strip() for p in doc], ['Page 2', 'Page 4', 'Page 5'])
            finally:
                Path(response.path).unlink()

    def test_viewer_fits_height_and_has_download_form(self):
        page = main.render_book_viewer(dict(slug='test', title='Test', pages=[], links=[])).body.decode()
        self.assertIn('stage.clientHeight-20', page)
        self.assertIn('new ResizeObserver(fitPages)', page)
        self.assertIn('Download Pages:', page)
        self.assertIn('/api/publications/test/selected-pages.pdf', page)
