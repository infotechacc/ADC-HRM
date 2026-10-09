from odoo import http
from odoo.http import request

from odoo.addons.web.controllers.home import Home


LEGACY_PREFIX = "/odoo"
CLEAN_PREFIX = "/app"


class CleanBackendHome(Home):
    @http.route(
        [
            "/web",
            "/odoo",
            "/odoo/<path:subpath>",
            "/app",
            "/app/<path:subpath>",
            "/scoped_app/<path:subpath>",
        ],
        type="http",
        auth="none",
        readonly=Home._web_client_readonly,
    )
    def web_client(self, s_action=None, subpath=None, **kw):
        path = request.httprequest.path
        if path == LEGACY_PREFIX or path.startswith(f"{LEGACY_PREFIX}/"):
            clean_path = f"{CLEAN_PREFIX}{path[len(LEGACY_PREFIX):]}"
            query = request.httprequest.query_string.decode()
            if query:
                clean_path = f"{clean_path}?{query}"
            return request.redirect(clean_path, 303)
        return super().web_client(s_action=s_action, subpath=subpath, **kw)
