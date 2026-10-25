from odoo import http
from odoo.exceptions import AccessError, MissingError
from odoo.http import request


class CareDocumentController(http.Controller):

    @http.route('/care/document/<int:version_id>/<string:mode>', type='http', auth='user', methods=['GET'])
    def document_content(self, version_id, mode='preview'):
        """Serve a document version after an ORM access check, and record the access."""
        if mode not in ('preview', 'download'):
            raise request.not_found()
        version = request.env['binaryaid.care.document.version'].browse(version_id)
        try:
            version.check_access('read')
            version.document_id.check_access('read')
        except (AccessError, MissingError):
            raise request.not_found()
        if not version.attachment_id:
            raise request.not_found()
        request.env['binaryaid.care.document.access'].sudo().create({
            'document_id': version.document_id.id, 'version_id': version.id, 'user_id': request.env.uid,
            'action': mode, 'ip_address': request.httprequest.remote_addr})
        stream = request.env['ir.binary']._get_stream_from(version.attachment_id.sudo())
        mimetype = stream.mimetype or ''
        inline = mode == 'preview' and (mimetype.startswith('image/') or mimetype == 'application/pdf')
        response = stream.get_response(as_attachment=not inline)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        if not mimetype == 'application/pdf':
            response.headers['Content-Security-Policy'] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
        response.headers['Cache-Control'] = 'no-store'
        return response
