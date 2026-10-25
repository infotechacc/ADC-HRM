from odoo import fields, models

from odoo.addons.binaryaid_care.models.tools import DEFAULTS

DEFAULTS.update({'apply_unpaid_breaks': 'False'})


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    binaryaid_apply_unpaid_breaks = fields.Boolean(
        string='Deduct unpaid breaks from actual hours', config_parameter='binaryaid_care.apply_unpaid_breaks',
        help='Only enable once ADC has agreed its break and paid time rules.')
