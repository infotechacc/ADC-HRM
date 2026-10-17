from datetime import timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import AccessError
from odoo.tools import format_date, format_datetime


class HrmsDashboard(models.AbstractModel):
    _inherit = 'binaryaid.hrms.dashboard'

    @api.model
    @api.readonly
    def get_overview(self):
        data = super().get_overview()
        data['schedule'] = None
        if not data['can_work']:
            return data
        today = fields.Date.context_today(self)
        monday = today - timedelta(days=today.weekday())
        viewer_timezone = self.env.context.get('tz') or self.env.user.tz or 'UTC'
        tz = pytz.timezone(viewer_timezone)
        start = tz.localize(fields.Datetime.to_datetime(monday)).astimezone(pytz.UTC).replace(tzinfo=None)
        end = tz.localize(fields.Datetime.to_datetime(monday + timedelta(days=7))).astimezone(pytz.UTC).replace(tzinfo=None)
        domain = [('user_id', '=', self.env.uid), ('company_id', '=', self.env.company.id),
                  ('state', '=', 'published'), ('start', '<', end), ('end', '>', start)]
        shifts = self.env['binaryaid.work.shift'].search(domain, limit=100)
        items = []
        days = []
        for offset in range(7):
            date = monday + timedelta(days=offset)
            days.append({'date': str(date), 'label': format_date(self.env, date, date_format='EEE'),
                         'number': date.day, 'today': date == today, 'count': 0})
        for shift in shifts:
            local_start = pytz.UTC.localize(shift.start).astimezone(tz)
            local_end = pytz.UTC.localize(shift.end).astimezone(tz)
            # A shift continuing overnight is marked on each day it touches.
            for day in days:
                if str(local_start.date()) <= day['date'] <= str((local_end - timedelta(microseconds=1)).date()):
                    day['count'] += 1
            same_day = local_start.date() == local_end.date()
            items.append({
                'id': shift.id, 'name': shift.name,
                'start': format_datetime(self.env, shift.start, tz=viewer_timezone),
                'end': format_datetime(self.env, shift.end, tz=viewer_timezone),
                'day': format_date(self.env, local_start.date(), date_format='EEE'),
                'day_number': local_start.day,
                'time_label': '%s – %s' % (
                    format_datetime(self.env, shift.start, tz=viewer_timezone, dt_format='HH:mm'),
                    format_datetime(self.env, shift.end, tz=viewer_timezone,
                                    dt_format='HH:mm' if same_day else 'EEE d MMM, HH:mm')),
                'hours': round(shift.planned_hours, 2), 'location': shift.location or '',
                'tasks': ', '.join(shift.task_ids.mapped('name')),
            })
        data['schedule'] = {
            'timezone': viewer_timezone, 'days': days,
            'period': '%s – %s' % (format_date(self.env, monday, date_format='d MMM'),
                                   format_date(self.env, monday + timedelta(days=6), date_format='d MMM y')),
            'preview_limited': len(shifts) == 100, 'shifts': items,
        }
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
