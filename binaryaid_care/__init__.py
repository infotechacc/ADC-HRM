from . import controllers
from . import models
from . import wizard


def _prepare_document_slots(env):
    """Give every existing employee one document slot per worker category, so missing
    documents are reported for records created before this module was installed."""
    env['hr.employee'].search([]).action_binaryaid_prepare_documents()
