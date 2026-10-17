from datetime import timedelta

import pytz

from odoo import api, fields, models
from odoo.tools import format_datetime


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
        data['schedule'] = {
            'timezone': viewer_timezone,
            'shifts': [{'id': s.id, 'name': s.name, 'start': format_datetime(self.env, s.start, tz=viewer_timezone),
                        'end': format_datetime(self.env, s.end, tz=viewer_timezone), 'hours': round(s.planned_hours, 2),
                        'location': s.location or '', 'tasks': ', '.join(s.task_ids.mapped('name'))} for s in shifts],
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
