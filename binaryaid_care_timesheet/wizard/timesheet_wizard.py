from datetime import timedelta

from odoo import fields, models, _

from odoo.addons.binaryaid_care.models.tools import fortnight_start


class TimesheetGenerate(models.TransientModel):
    _name = 'binaryaid.care.timesheet.generate'
    _description = 'Generate Fortnightly Timesheets'

    date = fields.Date(string='Any date in the fortnight', required=True,
                       default=lambda self: fields.Date.context_today(self) - timedelta(days=14))
    period_start = fields.Date(compute='_compute_period', string='Fortnight starts')
    period_end = fields.Date(compute='_compute_period', string='Fortnight ends')

    def _compute_period(self):
        for wizard in self:
            wizard.period_start = fortnight_start(self.env, wizard.date) if wizard.date else False
            wizard.period_end = wizard.period_start and wizard.period_start + timedelta(days=13)

    def action_generate(self):
        sheets = self.env['binaryaid.care.timesheet']._generate(self.date)
        return {'type': 'ir.actions.act_window', 'name': _('Fortnightly timesheets'), 'res_model': 'binaryaid.care.timesheet',
                'view_mode': 'list,form', 'domain': [('id', 'in', sheets.ids)]}


class TimesheetAdjust(models.TransientModel):
    _name = 'binaryaid.care.timesheet.adjust'
    _description = 'Adjust Timesheet Hours'

    line_id = fields.Many2one('binaryaid.care.timesheet.line', required=True, readonly=True)
    actual_hours = fields.Float(related='line_id.actual_hours')
    hours = fields.Float(string='Adjusted hours', required=True)
    reason = fields.Text(required=True)
    clear = fields.Boolean(string='Remove adjustment (use actual hours)')

    def action_apply(self):
        if self.clear:
            self.line_id._clear_adjustment()
        else:
            self.line_id._adjust(self.hours, self.reason)
        return {'type': 'ir.actions.act_window_close'}


class TimesheetCorrection(models.TransientModel):
    _name = 'binaryaid.care.timesheet.correction'
    _description = 'Request Timesheet Correction'

    line_id = fields.Many2one('binaryaid.care.timesheet.line', required=True, readonly=True)
    note = fields.Text(string='Correction needed', required=True)

    def action_request(self):
        self.line_id._request_correction(self.note)
        return {'type': 'ir.actions.act_window_close'}
