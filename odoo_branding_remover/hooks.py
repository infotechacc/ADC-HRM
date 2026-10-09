def post_init_hook(env):
    env = env(su=True)
    env["mail.template"].search([])._remove_platform_branding()
    _cleanup_report_labels(env)
    _cleanup_module_labels(env)


def _cleanup_report_labels(env):
    report = env.ref(
        "account_edi_ubl_cii.action_report_account_invoices_generated_by_odoo",
        raise_if_not_found=False,
    )
    if report:
        report.name = "Invoice report"


def _cleanup_module_labels(env):
    replacements = {
        "mail_bot": "Assistant",
        "mail_bot_hr": "Assistant - HR",
    }
    modules = env["ir.module.module"].search([("name", "in", list(replacements))])
    for module in modules:
        module.shortdesc = replacements[module.name]
