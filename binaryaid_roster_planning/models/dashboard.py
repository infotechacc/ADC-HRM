from odoo import api, models


class HrmsDashboard(models.AbstractModel):
    _inherit = 'binaryaid.hrms.dashboard'

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
        return data
