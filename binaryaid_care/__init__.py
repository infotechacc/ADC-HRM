from . import controllers
from . import models
from . import wizard


def _prepare_document_slots(env):
    """Give every existing client and employee one document slot per category, so missing
    documents are reported for records created before this module was installed."""
    env['binaryaid.care.client'].with_context(active_test=False).search([]).action_prepare_documents()
    env['hr.employee'].search([]).action_binaryaid_prepare_documents()
