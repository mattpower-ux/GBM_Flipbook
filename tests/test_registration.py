import json
import re
import unittest
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
import main


class RegistrationTests(unittest.TestCase):
    def manifest(self):
        return dict(slug='test-book', title='Test & Book', pages=[], links=[],
                    registration_required=True, registration_portal_id='309276',
                    registration_form_id='ca14e4bc-4743-4ed4-a010-36be9140ec09')

    def test_viewer_resolves_registration(self):
        page = main.render_book_viewer(self.manifest()).body.decode()
        self.assertNotRegex(page, r'__[A-Z_]+__')
        self.assertIn('registration-thanks', page)
        self.assertIn('Download PDF', page)

    def test_manifest_json_preserves_title(self):
        page = main.render_book_viewer(self.manifest()).body.decode()
        data = re.search(r'id="manifest-data">(.*?)</script>', page, re.S)[1]
        self.assertEqual(json.loads(data)['title'], 'Test & Book')

    def test_custom_campaign_preserved(self):
        self.assertEqual(main.normalize_registration_campaign('2026 Resiliency Campaign'),
                         '2026 Resiliency Campaign')

    def test_admin_links_to_hubspot(self):
        page = main.render_admin_view([], 'magazine').body.decode()
        self.assertIn('Manage Campaigns in HubSpot', page)
        self.assertIn('Require HubSpot registration', page)
        self.assertIn('target="_blank"', page)

    def test_metadata_save_disable_and_validation(self):
        previous = main.active_storage_path
        with tempfile.TemporaryDirectory() as directory:
            main.active_storage_path = Path(directory)
            try:
                main.write_manifest('test-book', self.manifest())
                client = TestClient(main.app, base_url='https://testserver')
                client.post('/admin/login', data={'password': '1313'})
                url = '/admin/api/publications/test-book/metadata'
                response = client.post(url, data={'registration_required':'true', 'registration_form_id':'bad'})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(main.read_manifest('test-book')['registration_form_id'], self.manifest()['registration_form_id'])
                response = client.post(url, data={'registration_required':'true', 'registration_campaign':'2026 Resiliency Campaign'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(main.read_manifest('test-book')['registration_campaign'], '2026 Resiliency Campaign')
                self.assertEqual(client.post(url, data={'registration_required':'false'}).status_code, 200)
                self.assertFalse(main.registration_enabled(main.read_manifest('test-book')))
            finally:
                main.active_storage_path = previous

    def test_gated_archive_download_goes_to_embedded_registration(self):
        publication = dict(slug='test-book', title='Test', status='processed', cover_url='/cover.png',
                           date='2026-01-01', description='', flipbook_type='ebook', registration_required='true')
        page = main.render_archive_view([publication], flipbook_type='ebook', embedded=True).body.decode()
        self.assertIn('href="/embed/book/test-book"', page)
        self.assertNotIn('href="/api/publications/test-book/original.pdf"', page)


if __name__ == '__main__':
    unittest.main()
