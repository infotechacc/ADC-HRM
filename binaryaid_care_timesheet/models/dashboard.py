from odoo import api, fields, models, _
from odoo.exceptions import AccessError


class HrmsDashboard(models.AbstractModel):
    _inherit = 'binaryaid.hrms.dashboard'

    def _specifications(self):
        specs = super()._specifications()
        if self._is_shift_admin():
            # Fortnightly timesheets replace per-shift actual approvals as the review queue.
            specs['timesheets'] = ('binaryaid.care.timesheet', _('Timesheet reviews'), [
                ('company_id', '=', self.env.company.id), ('state', 'in', ['draft', 'review']),
                ('period_end', '<', fields.Date.context_today(self))],
                'fa-check-square-o', 'blue', _('Ended fortnights'))
        return specs

    @api.model
    def quick_action(self, key, date=None):
        if key == 'generate_timesheets':
            self._check_user()
            if not self._is_shift_admin():
                raise AccessError(_('Only roster administrators can generate timesheets.'))
            return {'type': 'ir.actions.act_window', 'name': _('Generate fortnightly timesheets'),
                    'res_model': 'binaryaid.care.timesheet.generate', 'views': [(False, 'form')], 'target': 'new'}
        return super().quick_action(key, date)
