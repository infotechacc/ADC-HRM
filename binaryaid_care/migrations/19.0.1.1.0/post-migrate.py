from odoo import SUPERUSER_ID, api

from odoo.addons.binaryaid_care import _prepare_document_slots


def migrate(cr, version):
    _prepare_document_slots(api.Environment(cr, SUPERUSER_ID, {}))
