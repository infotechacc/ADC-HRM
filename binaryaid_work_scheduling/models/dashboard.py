from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import AccessError
from odoo.tools import format_date, format_datetime

from odoo.addons.binaryaid_hrms_dashboard.models.dashboard import ATTENTION_LIMIT

ROSTER_DAYS = 14


class HrmsDashboard(models.AbstractModel):
    _inherit = 'binaryaid.hrms.dashboard'

    def _viewer_tz(self):
        return self.env.context.get('tz') or self.env.user.tz or 'UTC'

    def _utc_bounds(self, first_date, days):
        """UTC naive bounds of `days` local calendar days starting at first_date."""
        tz = pytz.timezone(self._viewer_tz())
        start = tz.localize(datetime.combine(first_date, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
        end = tz.localize(datetime.combine(first_date + timedelta(days=days), time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
        return start, end

    def _roster_start(self):
        # Two calendar weeks from this Monday until ADC confirms the fortnight anchor.
        today = fields.Date.context_today(self)
        return today - timedelta(days=today.weekday())

    def _is_shift_admin(self):
        return self.env.user.has_group('binaryaid_work_management.group_work_admin')

    def _specifications(self):
        specs = super()._specifications()
        if self._is_shift_admin():
            company = self.env.company.id
            today_start, today_end = self._utc_bounds(fields.Date.context_today(self), 1)
            roster_start, roster_end = self._utc_bounds(fields.Date.context_today(self), ROSTER_DAYS)
            specs['shifts_today'] = ('binaryaid.work.shift', _("Today's shifts"), [
                ('company_id', '=', company), ('state', '=', 'published'),
                ('start', '<', today_end), ('end', '>', today_start)], 'fa-calendar', 'teal', _('Published for today'))
            specs['unpublished'] = ('binaryaid.work.shift', _('Unpublished shifts'), [
                ('company_id', '=', company), ('state', '=', 'draft'),
                ('end', '>', roster_start), ('start', '<', roster_end)], 'fa-pencil-square-o', 'purple', _('Drafts in the next 14 days'))
        return specs

    def _time_label(self, shift):
        tz = self._viewer_tz()
        local_start = pytz.UTC.localize(shift.start).astimezone(pytz.timezone(tz))
        local_end = pytz.UTC.localize(shift.end).astimezone(pytz.timezone(tz))
        same_day = local_start.date() == local_end.date()
        return '%s – %s' % (
            format_datetime(self.env, shift.start, tz=tz, dt_format='HH:mm'),
            format_datetime(self.env, shift.end, tz=tz, dt_format='HH:mm' if same_day else 'EEE d MMM, HH:mm'))

    def _shift_status(self, shift, now):
        """Planning status; the planning extension refines it with attendance."""
        if shift.state == 'draft':
            return 'draft', _('Draft'), 'purple'
        if shift.end <= now:
            return 'ended', _('Ended'), 'muted'
        if shift.start <= now:
            return 'running', _('In progress'), 'teal'
        return 'upcoming', _('Upcoming'), 'blue'

    def _roster_days(self, shifts, first_date):
        tz = pytz.timezone(self._viewer_tz())
        today = fields.Date.context_today(self)
        days = []
        for offset in range(ROSTER_DAYS):
            date = first_date + timedelta(days=offset)
            days.append({'date': str(date), 'label': format_date(self.env, date, date_format='EEE'),
                         'number': date.day, 'month': format_date(self.env, date, date_format='MMM'),
                         'today': date == today, 'past': date < today, 'week_start': offset % 7 == 0,
                         'count': 0, 'published': 0, 'draft': 0})
        for shift in shifts:
            local_start = pytz.UTC.localize(shift.start).astimezone(tz)
            local_end = pytz.UTC.localize(shift.end).astimezone(tz)
            # A shift continuing overnight is marked on each day it touches.
            for day in days:
                if str(local_start.date()) <= day['date'] <= str((local_end - timedelta(microseconds=1)).date()):
                    day['count'] += 1
                    day['published' if shift.state == 'published' else 'draft'] += 1
        return days

    def _period_label(self, first_date):
        return '%s – %s' % (format_date(self.env, first_date, date_format='d MMM'),
                            format_date(self.env, first_date + timedelta(days=ROSTER_DAYS - 1), date_format='d MMM y'))

    def _own_schedule(self):
        """The employee's own published 14 day roster."""
        tz = pytz.timezone(self._viewer_tz())
        first_date = self._roster_start()
        start, end = self._utc_bounds(first_date, ROSTER_DAYS)
        domain = [('user_id', '=', self.env.uid), ('company_id', '=', self.env.company.id),
                  ('state', '=', 'published'), ('start', '<', end), ('end', '>', start)]
        shifts = self.env['binaryaid.work.shift'].search(domain, limit=100)
        now = fields.Datetime.now()
        items = []
        active = False
        for shift in shifts:
            local_start = pytz.UTC.localize(shift.start).astimezone(tz)
            status, status_label, tone = self._shift_status(shift, now)
            item = {
                'id': shift.id, 'name': shift.name,
                'start': format_datetime(self.env, shift.start, tz=self._viewer_tz()),
                'end': format_datetime(self.env, shift.end, tz=self._viewer_tz()),
                'day': format_date(self.env, local_start.date(), date_format='EEE'),
                'day_number': local_start.day, 'time_label': self._time_label(shift),
                'hours': round(shift.planned_hours, 2), 'location': shift.location or '',
                'tasks': ', '.join(shift.task_ids.mapped('name')),
                'status': status, 'status_label': status_label, 'tone': tone, 'past': shift.end <= now,
            }
            items.append(item)
            if status == 'running' and not active:
                active = item
        upcoming = [item for item in items if item['status'] == 'upcoming']
        return {
            'timezone': self._viewer_tz(), 'days': self._roster_days(shifts, first_date),
            'period': self._period_label(first_date),
            'preview_limited': len(shifts) == 100, 'shifts': items,
            'active': active, 'next': upcoming[0] if upcoming else False,
            'planned_hours': round(sum(i['hours'] for i in items if not i['past']), 2),
        }

    def _today_board(self):
        """Every shift touching the viewer's local today, for administrators."""
        start, end = self._utc_bounds(fields.Date.context_today(self), 1)
        shifts = self.env['binaryaid.work.shift'].search([
            ('company_id', '=', self.env.company.id), ('state', 'in', ['draft', 'published']),
            ('start', '<', end), ('end', '>', start)], order='start, employee_name', limit=60)
        now = fields.Datetime.now()
        rows = []
        for shift in shifts:
            status, label, tone = self._shift_status(shift, now)
            rows.append({'id': shift.id, 'employee': shift.employee_name, 'name': shift.name,
                         'initials': ''.join(part[0] for part in (shift.employee_name or '?').split()[:2]).upper(),
                         'time_label': self._time_label(shift), 'location': shift.location or '',
                         'hours': round(shift.planned_hours, 2), 'state': shift.state,
                         'status': status, 'status_label': label, 'tone': tone})
        return {'rows': rows, 'limited': len(shifts) == 60}

    def _coverage(self):
        first_date = self._roster_start()
        start, end = self._utc_bounds(first_date, ROSTER_DAYS)
        shifts = self.env['binaryaid.work.shift'].search([
            ('company_id', '=', self.env.company.id), ('state', 'in', ['draft', 'published']),
            ('start', '<', end), ('end', '>', start)])
        return {'days': self._roster_days(shifts, first_date), 'period': self._period_label(first_date),
                'timezone': self._viewer_tz()}

    def _unpublished_tab(self, domain):
        shifts = self.env['binaryaid.work.shift'].search(domain, order='start, id', limit=ATTENTION_LIMIT)
        tz = self._viewer_tz()
        items = [{
            'source': 'shift', 'id': shift.id, 'title': shift.employee_name, 'subtitle': shift.name,
            'meta': '%s · %s' % (format_datetime(self.env, shift.start, tz=tz, dt_format='EEE d MMM'), self._time_label(shift)),
            'tone': 'purple', 'warning': '',
            'actions': [{'name': 'publish', 'label': _('Publish'), 'style': 'success'},
                        {'name': 'open', 'label': _('Edit'), 'style': 'link'}],
        } for shift in shifts]
        return {'key': 'unpublished', 'label': _('Drafts'), 'icon': 'fa-pencil-square-o',
                'count': self.env['binaryaid.work.shift'].search_count(domain), 'items': items,
                'empty': _('Every shift in the next 14 days is published.')}

    def _attention_tabs(self, specs):
        tabs = super()._attention_tabs(specs)
        if 'unpublished' in specs:
            tabs.insert(0, self._unpublished_tab(specs['unpublished'][2]))
        return tabs

    def _quick_actions(self, admin):
        actions = super()._quick_actions(admin)
        if self._is_shift_admin():
            actions.insert(0, {'key': 'create_shift', 'label': _('Create shift'), 'icon': 'fa-plus', 'primary': True})
        return actions

    @api.model
    @api.readonly
    def get_overview(self):
        data = super().get_overview()
        data['schedule'] = None
        data['today'] = None
        data['coverage'] = None
        if self._is_shift_admin():
            data['today'] = self._today_board()
            data['coverage'] = self._coverage()
            data['shortcuts'].insert(0, {'key': 'work_schedule', 'label': _('Shift calendar'), 'icon': 'fa-calendar'})
        if data['can_work']:
            data['schedule'] = self._own_schedule()
            if not self._is_shift_admin():
                data['shortcuts'].insert(0, {'key': 'work_schedule', 'label': _('My shift calendar'), 'icon': 'fa-calendar'})
        return data

    @api.model
    @api.readonly
    def open_section(self, key):
        if key != 'work_schedule':
            return super().open_section(key)
        self._check_user()
        self.env['binaryaid.work.shift'].check_access('read')
        action = self.env['ir.actions.actions']._for_xml_id('binaryaid_work_scheduling.action_work_schedule')
        action['domain'] = [('company_id', '=', self.env.company.id)]
        return action

    @api.model
    def quick_action(self, key, date=None):
        if key != 'create_shift':
            return super().quick_action(key, date)
        self._check_user()
        if not self._is_shift_admin():
            raise AccessError(_('Only Work Management administrators can manage shifts.'))
        context = {'default_company_id': self.env.company.id}
        if date:
            # Suggest a 09:00–17:00 local shift on the selected day; every value stays editable.
            start, _end = self._utc_bounds(fields.Date.to_date(date), 1)
            context.update(default_start=fields.Datetime.to_string(start + timedelta(hours=9)),
                           default_end=fields.Datetime.to_string(start + timedelta(hours=17)))
        return {'type': 'ir.actions.act_window', 'name': _('New shift'), 'res_model': 'binaryaid.work.shift',
                'views': [(self.env.ref('binaryaid_work_scheduling.view_shift_form').id, 'form')],
                'target': 'new', 'context': context}

    def _attention_record(self, source, res_id):
        if source != 'shift':
            return super()._attention_record(source, res_id)
        if not self._is_shift_admin():
            raise AccessError(_('This item is not available on your dashboard.'))
        shift = self.env['binaryaid.work.shift'].search([
            ('id', '=', res_id), ('company_id', '=', self.env.company.id)], limit=1)
        if not shift:
            raise AccessError(_('This shift is not available on your dashboard.'))
        return shift

    @api.model
    def item_action(self, source, res_id, name):
        if source != 'shift':
            return super().item_action(source, res_id, name)
        self._check_user()
        shift = self._attention_record(source, res_id)
        if name == 'open':
            return self._dialog(shift, view=self.env.ref('binaryaid_work_scheduling.view_shift_form').id)
        if name == 'publish':
            shift.action_publish()
            return True
        raise AccessError(_('This action is not available for this item.'))

    @api.model
    @api.readonly
    def open_shift(self, shift_id):
        self._check_user()
        shift = self.env['binaryaid.work.shift'].search([
            ('id', '=', shift_id), ('user_id', '=', self.env.uid),
            ('company_id', '=', self.env.company.id), ('state', '=', 'published')], limit=1)
        if not shift:
            raise AccessError(_('This shift is not available on your dashboard.'))
        return {'type': 'ir.actions.act_window', 'name': shift.name,
                'res_model': 'binaryaid.work.shift', 'res_id': shift.id,
                'views': [(self.env.ref('binaryaid_work_scheduling.view_shift_form').id, 'form')]}
