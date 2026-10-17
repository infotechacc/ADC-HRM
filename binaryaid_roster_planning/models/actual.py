from odoo import api, fields, models, _
from odoo.exceptions import AccessError

from .assignment import ROSTER_TOKEN


class RosterActual(models.Model):
    _name = 'binaryaid.roster.actual'
    _description = 'Approved Attendance Snapshot for a Shift'
    _order = 'id desc'

    shift_id = fields.Many2one('binaryaid.work.shift', required=True, ondelete='restrict', index=True)
    company_id = fields.Many2one('res.company', required=True, index=True)
    employee_id = fields.Many2one('hr.employee', required=True, ondelete='restrict')
    user_id = fields.Many2one('res.users', required=True, ondelete='restrict', index=True)
    author_id = fields.Many2one('res.users', required=True, ondelete='restrict')
    attendance_ids = fields.Many2many('hr.attendance', readonly=True)
    hours = fields.Float(readonly=True, string='Approved Native Worked Hours')
    is_void = fields.Boolean(readonly=True)
    reason = fields.Text(required=True, readonly=True)
    snapshot = fields.Json(required=True, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('_roster_internal') is not ROSTER_TOKEN:
            raise AccessError(_('Approve actual work through attendance reconciliation.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('Actual-work approvals are append-only; submit a correction or reversal.'))

    def unlink(self):
        raise AccessError(_('Actual-work approvals are retained for history.'))
