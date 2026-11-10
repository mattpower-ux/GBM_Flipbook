import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pymupdf
from fastapi import UploadFile
from fastapi.testclient import TestClient
import main
from issue_summaries import CATALOG, issue_blurb, summary_button


class IssueSummaryTests(unittest.TestCase):
    def test_catalog_and_explicit_override(self):
        self.assertEqual(len(CATALOG), 65)
        slug = 'green-builder-q4-2026'
        self.assertTrue(issue_blurb({'slug': slug}).startswith('Housing’s'))
        self.assertEqual(issue_blurb({'slug': slug, 'summary_blurb': 'Edited'}), 'Edited')
        self.assertEqual(issue_blurb({'slug': slug, 'summary_blurb': ''}), '')

    def test_summary_is_safe_text(self):
        button = summary_button({'summary_blurb': '"><script>alert(1)</script>', 'title': '<img>'})
        self.assertNotIn('<script>', button)
        self.assertIn('&lt;script&gt;', button)

    def test_replacing_pdf_keeps_summary(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(main, 'active_storage_path', Path(directory)):
            main.write_manifest('test-book', {'slug': 'test-book', 'summary_blurb': 'Keep this editorial copy.'})
            with pymupdf.open() as doc:
                doc.new_page()
                pdf = doc.tobytes()
            main.save_publication_upload(slug='test-book', file=UploadFile(filename='replacement.pdf', file=io.BytesIO(pdf)))
            self.assertEqual(main.read_manifest('test-book')['summary_blurb'], 'Keep this editorial copy.')

    def test_admin_summary_edit_preserves_registration(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(main, 'active_storage_path', Path(directory)):
            main.write_manifest('test-book', {'slug': 'test-book', 'registration_required': True,
                'registration_portal_id': '309276', 'registration_form_id': 'ca14e4bc-4743-4ed4-a010-36be9140ec09'})
            client = TestClient(main.app, base_url='https://testserver')
            client.post('/admin/login', data={'password': '1313'})
            url = '/admin/api/publications/test-book/metadata'
            self.assertEqual(client.post(url, data={'summary_blurb': 'New summary'}).status_code, 200)
            saved = main.read_manifest('test-book')
            self.assertEqual(saved['summary_blurb'], 'New summary')
            self.assertTrue(saved['registration_required'])
            self.assertEqual(client.post(url, data={'summary_blurb': 'x'*2401}).status_code, 400)
            self.assertEqual(main.read_manifest('test-book')['summary_blurb'], 'New summary')
