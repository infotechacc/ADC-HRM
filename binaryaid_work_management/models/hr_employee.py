from odoo import models, _
from odoo.exceptions import AccessError


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    def action_binaryaid_work(self):
        self.ensure_one()
        if not self.env.user.has_group('binaryaid_work_management.group_work_admin'):
            raise AccessError(_('Only Work Management administrators can review employee work.'))
        self.check_access('read')
        action = self.env['ir.actions.actions']._for_xml_id('binaryaid_work_management.action_work_items')
        action['domain'] = [('binaryaid_employee_id', '=', self.id)]
        action['context'] = {'default_binaryaid_employee_id': self.id,
                             'group_by': ['binaryaid_work_date:day']}
        return action

    def action_binaryaid_work_history(self):
        self.ensure_one()
        if not self.env.user.has_group('binaryaid_work_management.group_work_admin'):
            raise AccessError(_('Only Work Management administrators can review employee work.'))
        self.check_access('read')
        action = self.env['ir.actions.actions']._for_xml_id('binaryaid_work_management.action_work_history')
        action['domain'] = [('employee_id', '=', self.id)]
        return action
