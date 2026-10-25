from odoo import api, fields, models, _
from odoo.exceptions import AccessError
from odoo.tools import format_datetime

from odoo.addons.binaryaid_hrms_dashboard.models.dashboard import ATTENTION_LIMIT


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

    def _signout_tab(self, domain):
        attendances = self.env['hr.attendance'].search(domain, order='check_in', limit=ATTENTION_LIMIT)
        tz = self._viewer_tz()
        items = [{
            'source': 'attendance', 'id': attendance.id, 'title': attendance.employee_id.name,
            'subtitle': _('Signed in %s', format_datetime(self.env, attendance.check_in, tz=tz, dt_format='EEE d MMM, HH:mm')),
            'meta': _('No published shift is running'), 'tone': 'red', 'warning': '',
            'actions': [{'name': 'open', 'label': _('Correct'), 'style': 'link'}],
        } for attendance in attendances]
        return {'key': 'missing_signout', 'label': _('Sign-outs'), 'icon': 'fa-sign-out',
                'count': self.env['hr.attendance'].search_count(domain), 'items': items,
                'empty': _('Everyone signed in has a running shift.')}

    def _timesheet_tab(self, domain):
        shifts = self.env['binaryaid.work.shift'].search(domain, order='end desc, id desc', limit=ATTENTION_LIMIT)
        tz = self._viewer_tz()
        items = [{
            'source': 'timesheet', 'id': shift.id, 'title': shift.employee_name, 'subtitle': shift.name,
            'meta': '%s · %s · %s h' % (format_datetime(self.env, shift.start, tz=tz, dt_format='EEE d MMM'),
                                         self._time_label(shift), round(shift.planned_hours, 2)),
            'tone': 'blue', 'warning': '',
            'actions': [{'name': 'reconcile', 'label': _('Review'), 'style': 'success'},
                        {'name': 'open', 'label': _('Shift'), 'style': 'link'}],
        } for shift in shifts]
        return {'key': 'timesheets', 'label': _('Timesheets'), 'icon': 'fa-check-square-o',
                'count': self.env['binaryaid.work.shift'].search_count(domain), 'items': items,
                'empty': _('All ended shifts have approved actual hours.')}

    def _attention_tabs(self, specs):
        tabs = super()._attention_tabs(specs)
        if 'missing_signout' in specs:
            tabs.append(self._signout_tab(specs['missing_signout'][2]))
        if 'timesheets' in specs:
            tabs.append(self._timesheet_tab(specs['timesheets'][2]))
        for tab in tabs:
            if tab['key'] == 'leave':
                self._flag_leave_conflicts(tab['items'])
        return tabs

    def _flag_leave_conflicts(self, items):
        """Leave overlapping published shifts needs a staffing decision before approval."""
        leaves = self.env['hr.leave'].browse([item['id'] for item in items])
        by_id = {leave.id: leave for leave in leaves}
        # Count only: no shift details are disclosed to leave approvers without roster access.
        shifts = self.env['binaryaid.work.shift'].sudo()
        for item in items:
            leave = by_id[item['id']]
            conflicts = shifts.search_count([
                ('employee_id', '=', leave.employee_id.id), ('state', '=', 'published'),
                ('start', '<', leave.date_to), ('end', '>', leave.date_from)])
            if conflicts:
                item['warning'] = _('Overlaps %s published shift(s) — reassign before approving.', conflicts)
                item['actions'] = [a for a in item['actions'] if a['name'] != 'approve']

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
        if data.get('today'):
            self._attendance_status(data['today']['rows'], fields.Datetime.now())
        data['presence'] = self._own_presence()
        return data

    def _attention_record(self, source, res_id):
        if source not in ('attendance', 'timesheet'):
            return super()._attention_record(source, res_id)
        specs = self._specifications()
        key = 'missing_signout' if source == 'attendance' else 'timesheets'
        if key not in specs:
            raise AccessError(_('This item is not available on your dashboard.'))
        model, label, domain = specs[key][:3]
        record = self.env[model].search(domain + [('id', '=', res_id)], limit=1)
        if not record:
            raise AccessError(_('This item is no longer waiting on your dashboard. Refresh to update it.'))
        return record

    @api.model
    def item_action(self, source, res_id, name):
        if source not in ('attendance', 'timesheet'):
            return super().item_action(source, res_id, name)
        self._check_user()
        record = self._attention_record(source, res_id)
        if name == 'open':
            view = self.env.ref('binaryaid_work_scheduling.view_shift_form').id if source == 'timesheet' else False
            return self._dialog(record, view=view)
        if source == 'timesheet' and name == 'reconcile':
            return record.action_approve_actual()
        raise AccessError(_('This action is not available for this item.'))
