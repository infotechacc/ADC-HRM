from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    binaryaid_fortnight_anchor = fields.Char(
        string='Fortnight start (a Monday)', config_parameter='binaryaid_care.fortnight_anchor', default='2026-01-05',
        help='Roster fortnights and timesheet periods start on this Monday and every 14 days after it.')
    binaryaid_max_upload_mb = fields.Integer(
        string='Maximum document size (MB)', config_parameter='binaryaid_care.max_upload_mb', default=10)
    binaryaid_allowed_extensions = fields.Char(
        string='Allowed document types', config_parameter='binaryaid_care.allowed_extensions',
        default='pdf,jpg,jpeg,png,heic,doc,docx')
    binaryaid_retention_years = fields.Integer(
        string='Document retention (years)', config_parameter='binaryaid_care.retention_years', default=7)
    binaryaid_clamd_socket = fields.Char(
        string='ClamAV socket', config_parameter='binaryaid_care.clamd_socket',
        help='Optional clamd UNIX socket path or host:port. When set, every upload is virus scanned.')

    @api.constrains('binaryaid_fortnight_anchor')
    def _check_binaryaid_anchor(self):
        for settings in self:
            try:
                anchor = fields.Date.to_date(settings.binaryaid_fortnight_anchor)
            except ValueError:
                anchor = None
            if not anchor or anchor.weekday() != 0:
                raise ValidationError(_('The fortnight start must be a Monday date (YYYY-MM-DD).'))
