import base64

from odoo import fields, models, _
from odoo.exceptions import UserError


class DocumentUpload(models.TransientModel):
    _name = 'binaryaid.care.document.upload'
    _description = 'Upload Care Document Version'

    document_id = fields.Many2one('binaryaid.care.document', required=True, readonly=True)
    category_id = fields.Many2one(related='document_id.category_id')
    requires_expiry = fields.Boolean(related='document_id.category_id.requires_expiry')
    file = fields.Binary(required=True, attachment=False)
    file_name = fields.Char()
    issue_date = fields.Date()
    expiry_date = fields.Date()
    note = fields.Text()

    def action_upload(self):
        self.ensure_one()
        if not self.file:
            raise UserError(_('Choose a file to upload.'))
        self.env['binaryaid.care.document.version']._create_version(
            self.document_id, base64.b64decode(self.file), self.file_name or 'document',
            expiry_date=self.expiry_date, issue_date=self.issue_date, note=self.note)
        return {'type': 'ir.actions.act_window_close'}


class DocumentReview(models.TransientModel):
    _name = 'binaryaid.care.document.review'
    _description = 'Reject Care Document Version'

    version_id = fields.Many2one('binaryaid.care.document.version', required=True, readonly=True)
    note = fields.Text(string='Reason', required=True)

    def action_reject(self):
        self.ensure_one()
        self.version_id._review('rejected', self.note)
        return {'type': 'ir.actions.act_window_close'}
