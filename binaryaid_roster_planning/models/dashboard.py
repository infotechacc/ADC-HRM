from odoo import api, fields, models, _
from odoo.tools import format_datetime


class HrmsDashboard(models.AbstractModel):
    _inherit = 'binaryaid.hrms.dashboard'

    def _running_employee_ids(self, now):
        return self.env['binaryaid.work.shift'].search([
            ('company_id', '=', self.env.company.id), ('state', '=', 'published'),
            ('start', '<=', now), ('end', '>', now)]).employee_id.ids

    def _specifications(self):
        specs = super()._specifications()
        if self._is_shift_admin() and self._can_read('hr.attendance'):
            now = fields.Datetime.now()
            specs['missing_signout'] = ('hr.attendance', _('Missing sign-outs'), [
                ('employee_id.company_id', '=', self.env.company.id), ('check_out', '=', False),
                ('employee_id', 'not in', self._running_employee_ids(now))],
                'fa-sign-out', 'red', _('No running shift'))
        if self._is_shift_admin():
            specs['timesheets'] = ('binaryaid.work.shift', _('Timesheet reviews'), [
                ('company_id', '=', self.env.company.id), ('state', '=', 'published'),
                ('end', '<=', fields.Datetime.now()), ('roster_actual_ids', '=', False)],
                'fa-check-square-o', 'blue', _('Ended shifts awaiting approval'))
        return specs

    def _enrich_day_rows(self, rows, shifts):
        super()._enrich_day_rows(rows, shifts)
        self._attendance_status(rows, fields.Datetime.now())

    def _attendance_status(self, rows, now):
        if not rows or not self._can_read('hr.attendance'):
            return
        shifts = self.env['binaryaid.work.shift'].browse([row['id'] for row in rows])
        attendances = self.env['hr.attendance'].search([
            ('employee_id', 'in', shifts.employee_id.ids),
            ('check_in', '<', max(shifts.mapped('end'))),
            '|', ('check_out', '=', False), ('check_out', '>', min(shifts.mapped('start')))])
        for row, shift in zip(rows, shifts):
            if shift.state != 'published':
                continue
            mine = attendances.filtered(lambda a: a.employee_id == shift.employee_id and a.check_in < shift.end
                                        and (not a.check_out or a.check_out > shift.start))
            if mine.filtered(lambda a: not a.check_out):
                row.update(status='on_shift', status_label=_('Signed in'), tone='green')
            elif mine and shift.end <= now:
                row.update(status='completed', status_label=_('Completed'), tone='muted')
            elif mine:
                row.update(status='signed_out', status_label=_('Signed out early'), tone='amber')
            elif shift.start <= now:
                row.update(status='late', status_label=_('Not signed in'), tone='red')

    def _own_presence(self):
        employee = self.env.user.employee_id
        if not employee or 'hr.attendance' not in self.env:
            return None
        # Own attendance status only; the record rules of hr.employee are not relaxed.
        own = employee.sudo()
        return {'checked_in': own.attendance_state == 'checked_in',
                'since': format_datetime(self.env, own.last_check_in, tz=self._viewer_tz(), dt_format='HH:mm')
                if own.attendance_state == 'checked_in' and own.last_check_in else ''}

    @api.model
    @api.readonly
    def get_overview(self):
        data = super().get_overview()
        schedule = data.get('schedule')
        if schedule:
            shifts = self.env['binaryaid.work.shift'].browse([s['id'] for s in schedule['shifts']])
            by_id = {s.id: s for s in shifts}
            for item in schedule['shifts']:
                item['unpaid_break_minutes'] = by_id[item['id']].unpaid_break_minutes
                item['break_instructions'] = by_id[item['id']].break_instructions or ''
        data['presence'] = self._own_presence()
        return data
