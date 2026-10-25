from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import format_datetime


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    binaryaid_conflict_count = fields.Integer(compute='_compute_binaryaid_conflicts', string='Affected shifts')
    binaryaid_conflict_summary = fields.Text(compute='_compute_binaryaid_conflicts', string='Affected published shifts')

    def _binaryaid_conflicting_shifts(self):
        """Published shifts of the employee during this leave (elevated count/summary only)."""
        self.ensure_one()
        if not self.employee_id or not self.date_from or not self.date_to:
            return self.env['binaryaid.work.shift']
        return self.env['binaryaid.work.shift'].sudo().search([
            ('employee_id', '=', self.employee_id.id), ('state', '=', 'published'),
            ('start', '<', self.date_to), ('end', '>', self.date_from)], order='start')

    @api.depends('employee_id', 'date_from', 'date_to')
    def _compute_binaryaid_conflicts(self):
        for leave in self:
            shifts = leave._binaryaid_conflicting_shifts()
            leave.binaryaid_conflict_count = len(shifts)
            tz = self.env.user.tz or 'Australia/Sydney'
            leave.binaryaid_conflict_summary = '\n'.join(
                '%s – %s · %s%s' % (format_datetime(self.env, s.start, tz=tz, dt_format='EEE d MMM HH:mm'),
                                     format_datetime(self.env, s.end, tz=tz, dt_format='HH:mm'), s.name,
                                     ' · %s' % s.client_id.name if s.client_id else '') for s in shifts) or False

    def _binaryaid_require_staffing_resolution(self):
        for leave in self:
            shifts = leave._binaryaid_conflicting_shifts()
            if shifts:
                raise UserError(_(
                    '%(employee)s has %(count)s published shift(s) during this leave:\n%(shifts)s\n\n'
                    'Reassign (Replace / Swap) or cancel these shifts before approving the leave.',
                    employee=leave.employee_id.name, count=len(shifts), shifts=leave.binaryaid_conflict_summary))

    def action_approve(self, check_state=True):
        self._binaryaid_require_staffing_resolution()
        result = super().action_approve(check_state=check_state)
        self._binaryaid_notify_decision()
        return result


    def _binaryaid_notify_decision(self):
        for leave in self.filtered(lambda l: l.state in ('validate', 'validate1') and l.employee_id.user_id):
            leave.message_notify(
                partner_ids=leave.employee_id.user_id.partner_id.ids, subject=_('Leave request update'),
                body=_('Your %(type)s request from %(start)s to %(end)s is %(state)s.',
                       type=leave.holiday_status_id.name, start=leave.request_date_from, end=leave.request_date_to,
                       state=_('approved') if leave.state == 'validate' else _('approved at first level')))

    def action_binaryaid_open_conflicts(self):
        self.ensure_one()
        shifts = self._binaryaid_conflicting_shifts()
        return {'type': 'ir.actions.act_window', 'name': _('Affected shifts'), 'res_model': 'binaryaid.work.shift',
                'view_mode': 'list,form', 'domain': [('id', 'in', shifts.ids)]}
