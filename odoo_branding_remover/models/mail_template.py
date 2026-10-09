import re

from lxml import html

from odoo import models


POWERED_BY_RE = re.compile(
    r"<!--\s*POWERED BY\s*-->.*?</tr>\s*</table>",
    flags=re.IGNORECASE | re.DOTALL,
)


class MailTemplate(models.Model):
    _inherit = "mail.template"

    def _remove_platform_branding(self):
        for template in self:
            body_html = template.body_html or ""
            cleaned = self._clean_branding_html(body_html)
            if cleaned != body_html:
                template.write({"body_html": cleaned})

    def _clean_branding_html(self, body_html):
        cleaned = POWERED_BY_RE.sub("", body_html)
        if "odoo.com" not in cleaned.lower() and "powered by" not in cleaned.lower():
            return cleaned

        try:
            root = html.fragment_fromstring(cleaned, create_parent="div")
        except (ValueError, html.ParserError):
            return cleaned.replace("Powered by Odoo", "").replace("Powered By Odoo", "")

        for element in root.xpath(
            ".//*[contains(translate(@href, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'odoo.com')]"
        ):
            parent = element.getparent()
            if parent is not None:
                parent.drop_tree()

        return "".join(html.tostring(child, encoding="unicode") for child in root)

    def action_remove_platform_branding(self):
        self._remove_platform_branding()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": self.env._("Templates have been cleaned successfully."),
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }
