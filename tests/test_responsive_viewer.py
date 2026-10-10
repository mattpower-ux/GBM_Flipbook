import unittest
import main


class ResponsiveViewerTests(unittest.TestCase):
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
