import math
from datetime import timedelta

from odoo import fields

PARAM_PREFIX = 'binaryaid_care.'
DEFAULTS = {
    'fortnight_anchor': '2026-01-05',
    'max_upload_mb': '10',
    'allowed_extensions': 'pdf,jpg,jpeg,png,heic,doc,docx',
    'retention_years': '7',
    'clamd_socket': '',
}


def get_param(env, key, default=None):
    value = env['ir.config_parameter'].sudo().get_param(PARAM_PREFIX + key)
    return value if value not in (None, False, '') else DEFAULTS.get(key, default)


def fortnight_start(env, date):
    """First day of the roster fortnight containing date (anchor is a configured Monday)."""
    anchor = fields.Date.to_date(get_param(env, 'fortnight_anchor'))
    return date - timedelta(days=(date - anchor).days % 14)


def distance_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres (haversine)."""
    radius = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))
