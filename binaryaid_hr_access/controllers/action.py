from odoo import http
from odoo.http import request
from odoo.addons.web.controllers.action import Action


class DirectoryAction(Action):
    @http.route()
    def load(self, action_id, context=None):
        action = super().load(action_id, context=context)
        if action and action.get('res_model') == 'hr.employee.public':
            request.env['hr.employee.public']._check_directory_access()
        return action
