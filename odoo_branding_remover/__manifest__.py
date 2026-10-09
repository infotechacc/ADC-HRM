{
    "name": "System Branding Cleanup",
    "version": "19.0.1.0.1",
    "category": "Tools",
    "summary": "Remove platform branding from user-facing areas",
    "description": """
White Label
===========

Customize the user interface and replace platform branding with your own
company or product identity.

Features:
- Remove platform branding from the user interface
- Replace exposed vendor references with custom branding
- Customize browser titles and UI labels
- Customize login and system branding
- Support white-label deployments
    """,
    "author": "Ahosan Kabir",
    "co-author": "Binary Aid",
    "website": "https://binaryaid.com/",
    "license": "LGPL-3",
    "depends": [
        "base",
        "web",
        "mail",
        "portal",
        "auth_signup",
        "base_import",
    ],
    "data": [
        "views/webclient_templates.xml",
        "views/report_templates.xml",
        "views/portal_templates.xml",
        "views/auth_signup_templates.xml",
        # "views/report_label_data.xml",
        "views/mail_template_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "odoo_branding_remover/static/src/js/branding_cleanup.esm.js",
            "odoo_branding_remover/static/src/import_data_content/import_data_content.xml",
            "odoo_branding_remover/static/src/import_data_sidepanel/import_data_sidepanel.xml",
        ],
        "web.assets_frontend": [],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}
