from odoo import models 


class IrModuleModule(models.Model):
    _inherit = "ir.module.module"

    def write(self, vals):
        result = super().write(vals)
        self._cleanup_platform_labels()
        return result

    def _cleanup_platform_labels(self):
        replacements = {
            "mail_bot": "Assistant",
            "mail_bot_hr": "Assistant - HR",
        }
        modules = self.sudo().search([("name", "in", list(replacements))])
        for module in modules:
            if module.shortdesc != replacements[module.name]:
                module.shortdesc = replacements[module.name]
