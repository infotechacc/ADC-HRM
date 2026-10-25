from odoo import fields, models

from odoo.addons.binaryaid_care.models.tools import DEFAULTS

DEFAULTS.update({
    'clock_in_early_minutes': '30',
    'clock_out_late_minutes': '120',
    'gps_max_accuracy_m': '100',
    'clock_out_time_rule': 'tap',
    'incident_max_upload_mb': '50',
    'incident_escalation_severity': 'high',
})


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    binaryaid_clock_in_early_minutes = fields.Integer(
        string='Sign in opens (minutes before start)', config_parameter='binaryaid_care.clock_in_early_minutes', default=30)
    binaryaid_clock_out_late_minutes = fields.Integer(
        string='Sign out closes (minutes after end)', config_parameter='binaryaid_care.clock_out_late_minutes', default=120)
    binaryaid_gps_max_accuracy_m = fields.Integer(
        string='Maximum GPS uncertainty (m)', config_parameter='binaryaid_care.gps_max_accuracy_m', default=100,
        help='Readings less precise than this are rejected; the worker can retry or report an exception.')
    binaryaid_clock_out_time_rule = fields.Selection(
        [('tap', 'When Clock Out is tapped (note writing is unpaid)'),
         ('note_submit', 'When the shift note is submitted (note writing is paid)')],
        string='Recorded sign out time', config_parameter='binaryaid_care.clock_out_time_rule', default='tap')
    binaryaid_incident_max_upload_mb = fields.Integer(
        string='Incident attachment limit (MB)', config_parameter='binaryaid_care.incident_max_upload_mb', default=50)
    binaryaid_incident_escalation_severity = fields.Selection(
        [('medium', 'Medium and above'), ('high', 'High and above'), ('critical', 'Critical only')],
        string='Escalate incidents', config_parameter='binaryaid_care.incident_escalation_severity', default='high')
