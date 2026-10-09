from odoo import http
from odoo.http import request

from odoo.addons.web.controllers.home import Home
from odoo.addons.web.controllers.utils import is_user_internal


class BrandingHome(Home):
    @http.route("/", type="http", auth="none")
    def index(self, s_action=None, db=None, **kw):
        if request.db and request.session.uid and not is_user_internal(request.session.uid):
            return request.redirect_query("/web/login_successful", query=request.params)
        return request.redirect_query("/web", query=request.params)

    def _login_redirect(self, uid, redirect=None):
        target = super()._login_redirect(uid, redirect=redirect)
        return "/web" if target == "/odoo" else target
