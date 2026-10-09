from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        result = super().session_info()
        if self.env.user.has_group('base.group_user'):
            action = self.env.ref('binaryaid_hrms_dashboard.action_dashboard', raise_if_not_found=False)
            if action:
                result['home_action_id'] = action.id
        return result
