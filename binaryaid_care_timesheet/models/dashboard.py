from odoo import api, fields, models, _
from odoo.exceptions import AccessError
from odoo.tools import format_date

from odoo.addons.binaryaid_hrms_dashboard.models.dashboard import ATTENTION_LIMIT


class HrmsDashboard(models.AbstractModel):
    _inherit = 'binaryaid.hrms.dashboard'

    def _specifications(self):
        specs = super()._specifications()
        if self._is_shift_admin():
            # Fortnightly timesheets replace per-shift actual approvals as the review queue.
            specs['timesheets'] = ('binaryaid.care.timesheet', _('Timesheet reviews'), [
                ('company_id', '=', self.env.company.id), ('state', 'in', ['draft', 'review']),
                ('period_end', '<', fields.Date.context_today(self))],
                'fa-check-square-o', 'blue', _('Ended fortnights to approve'))
        return specs

    def _timesheet_tab(self, domain):
        sheets = self.env['binaryaid.care.timesheet'].search(domain, order='period_start, employee_id', limit=ATTENTION_LIMIT)
        items = [{
            'source': 'timesheet', 'id': sheet.id, 'title': sheet.employee_id.name,
            'subtitle': _('%(planned).1f h planned · %(actual).1f h actual', planned=sheet.planned_hours, actual=sheet.actual_hours),
            'meta': '%s – %s' % (format_date(self.env, sheet.period_start, date_format='d MMM'),
                                 format_date(self.env, sheet.period_end, date_format='d MMM')),
            'tone': 'blue', 'warning': _('%s row(s) need attention', sheet.issue_count) if sheet.issue_count else '',
            'actions': [{'name': 'open', 'label': _('Review'), 'style': 'success'}],
        } for sheet in sheets]
        return {'key': 'timesheets', 'label': _('Timesheets'), 'icon': 'fa-check-square-o',
                'count': self.env['binaryaid.care.timesheet'].search_count(domain), 'items': items,
                'empty': _('No ended fortnights are waiting for approval.')}

    @api.model
    def item_action(self, source, res_id, name):
        if source != 'timesheet':
            return super().item_action(source, res_id, name)
        self._check_user()
        record = self._attention_record(source, res_id)
        if name == 'open':
            return {'type': 'ir.actions.act_window', 'name': record.name, 'res_model': record._name, 'res_id': record.id,
                    'views': [(False, 'form')], 'target': 'current'}
        raise AccessError(_('This action is not available for this item.'))

    @api.model
    def quick_action(self, key, date=None):
        if key == 'generate_timesheets':
            self._check_user()
            if not self._is_shift_admin():
                raise AccessError(_('Only roster administrators can generate timesheets.'))
            return {'type': 'ir.actions.act_window', 'name': _('Generate fortnightly timesheets'),
                    'res_model': 'binaryaid.care.timesheet.generate', 'views': [(False, 'form')], 'target': 'new'}
        return super().quick_action(key, date)
