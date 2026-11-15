import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


class ArchiveVisibilityTests(unittest.TestCase):
    def test_old_q4_duplicate_is_unlisted_but_readable(self):
        slugs = ('green-builder-q4-2026', 'green-builder-q4-2026-2', 'green-builder-q3-2026')
        publications = [
            dict(slug=slug, status='processed', cover_url=f'/covers/{slug}.jpg',
                 flipbook_type='magazine', title=slug, description='', date='2026-11-10', display_date='November 2026')
            for slug in slugs
        ]
        client = TestClient(main.app)
        with patch.object(main, 'list_publications', return_value=publications):
            for archive, book in (('/archive', '/book'), ('/embed/archive', '/embed/book')):
                with self.subTest(archive=archive):
                    response = client.get(archive)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(f'href="{book}/{slugs[0]}"', response.text)
                    self.assertNotIn(slugs[1], response.text)
                    self.assertIn(f'href="{book}/{slugs[2]}"', response.text)
            self.assertEqual(client.get('/api/publications').json()['count'], 3)
        with patch.object(main, 'read_manifest', side_effect=lambda slug: {'slug': slug}):
            for slug in slugs[:2]:
                self.assertEqual(client.get(f'/api/publications/{slug}/manifest').json()['slug'], slug)
