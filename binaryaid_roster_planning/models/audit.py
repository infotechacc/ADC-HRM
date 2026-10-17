from odoo import api, fields, models, _
from odoo.exceptions import AccessError


class RosterEvent(models.Model):
    _name = 'binaryaid.roster.event'
    _description = 'Immutable Roster Event Snapshot'
    _order = 'id desc'

    shift_id = fields.Many2one('binaryaid.work.shift', required=True, ondelete='restrict', index=True)
    company_id = fields.Many2one('res.company', required=True, index=True)
    employee_id = fields.Many2one('hr.employee', required=True, ondelete='restrict')
    user_id = fields.Many2one('res.users', required=True, ondelete='restrict', index=True)
    author_id = fields.Many2one('res.users', required=True, ondelete='restrict')
    event = fields.Char(required=True)
    reason = fields.Text()
    snapshot = fields.Json(required=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise AccessError(_('Roster events can only be recorded by authorized internal actions.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('Roster events are append-only.'))

    def unlink(self):
        raise AccessError(_('Roster events are retained for history.'))
