import unittest
import main


class ResponsiveViewerTests(unittest.TestCase):
    def test_magazine_intro_survives_new_issues(self):
        for slug in ('green-builder-q4-2026', 'future-issue'):
            page = main.featured_description_markup(dict(slug=slug,
                title='New Issue', description='Uploaded from admin'), 'magazine')
            self.assertIn('For 21 years', page)
            self.assertIn('mailto:', page)
            self.assertIn('matt-power-headshot-640.jpg', page)
            self.assertIn('width="250"', page)
            self.assertNotIn('Q3 2026', page)

    def test_ebook_description_is_unchanged(self):
        page = main.featured_description_markup(dict(description='Ebook summary'), 'ebook')
        self.assertEqual(page, '<p class="lede">Ebook summary</p>')

    def test_both_viewers_have_white_responsive_chrome(self):
        for kind in ('magazine', 'ebook'):
            for embedded in (True, False):
                page = main.render_book_viewer(dict(slug='preview', title='Preview',
                    flipbook_type=kind, pages=[], links=[]), embedded=embedded).body.decode()
                self.assertIn('id="responsive-white-viewer"', page)
                self.assertIn('color-scheme:light', page)
                self.assertIn('height:100dvh', page)
                self.assertIn('width:100%', page)
                self.assertIn('minmax(0,1fr)', page)
                self.assertNotIn('window.top.location', page)

    def test_archive_fonts_do_not_scale_with_viewport(self):
        page = main.render_archive_view([], embedded=True).body.decode()
        self.assertNotIn('4.8vw', page)
        self.assertNotIn('2.1vw', page)


if __name__ == '__main__':
    unittest.main()
