from urllib.parse import parse_qs, urlsplit

from odoo.tests import HttpCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestCleanBackendRoutes(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        new_test_user(cls.env, login='clean_route_user', password='clean_route_user', groups='base.group_user')

    def test_authenticated_deep_links_render_webclient(self):
        self.authenticate('clean_route_user', 'clean_route_user')
        for path in ('/app', '/app/employees', '/app/action-1', '/app/action-1/123', '/web'):
            with self.subTest(path=path):
                response = self.url_open(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn('web.assets_web', response.text)
                self.assertEqual(response.headers.get('Cache-Control'), 'no-store')

    def test_legacy_redirect_preserves_path_and_query(self):
        self.authenticate('clean_route_user', 'clean_route_user')
        response = self.url_open('/odoo/action-1/123?debug=1&menu_id=7', allow_redirects=False)
        self.assertEqual(response.status_code, 303)
        location = urlsplit(response.headers['Location'])
        self.assertEqual(location.path, '/app/action-1/123')
        self.assertEqual(parse_qs(location.query), {'debug': ['1'], 'menu_id': ['7']})

    def test_anonymous_deep_link_requires_login(self):
        response = self.url_open('/app/action-1/123', allow_redirects=False)
        self.assertEqual(response.status_code, 303)
        location = urlsplit(response.headers['Location'])
        self.assertEqual(location.path, '/web/login')
        self.assertTrue(parse_qs(location.query)['redirect'][0].startswith('/app/action-1/123'))
