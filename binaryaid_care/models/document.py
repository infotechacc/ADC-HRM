import base64
import hashlib
import logging
import socket
import struct

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from .tools import get_param

_logger = logging.getLogger(__name__)

# Leading bytes accepted for each allowed extension; content must match its name.
SIGNATURES = {
    'pdf': [b'%PDF'],
    'png': [b'\x89PNG\r\n\x1a\n'],
    'jpg': [b'\xff\xd8\xff'], 'jpeg': [b'\xff\xd8\xff'],
    'heic': [b'ftyp'],  # checked at offset 4
    'docx': [b'PK\x03\x04'], 'xlsx': [b'PK\x03\x04'],
    'doc': [b'\xd0\xcf\x11\xe0'], 'xls': [b'\xd0\xcf\x11\xe0'],
    'mp4': [b'ftyp'], 'mov': [b'ftyp'], 'm4a': [b'ftyp'],
    'mp3': [b'ID3', b'\xff\xfb', b'\xff\xf3', b'\xff\xf2'],
    'wav': [b'RIFF'], 'webm': [b'\x1aE\xdf\xa3'], 'ogg': [b'OggS'],
}
BLOCKED_SIGNATURES = [b'MZ', b'\x7fELF', b'#!']


def validate_upload(env, data, filename, allowed=None):
    """Server-side validation of an uploaded file: type, size, content signature and optional AV scan."""
    if not data:
        raise ValidationError(_('Choose a file to upload.'))
    extension = (filename or '').rsplit('.', 1)[-1].lower() if '.' in (filename or '') else ''
    allowed = allowed or [e.strip().lower() for e in get_param(env, 'allowed_extensions').split(',') if e.strip()]
    if extension not in allowed:
        raise ValidationError(_('File type ".%(ext)s" is not allowed. Allowed types: %(allowed)s.',
                                ext=extension, allowed=', '.join(allowed)))
    limit = int(get_param(env, 'max_upload_mb')) * 1024 * 1024
    if len(data) > limit:
        raise ValidationError(_('The file is larger than the %s MB limit.', get_param(env, 'max_upload_mb')))
    if any(data.startswith(sig) for sig in BLOCKED_SIGNATURES):
        raise ValidationError(_('Executable files cannot be uploaded.'))
    signatures = SIGNATURES.get(extension)
    if signatures:
        head = data[4:8] if signatures == [b'ftyp'] else data
        if not any(head.startswith(sig) for sig in signatures):
            raise ValidationError(_('The file content does not match its ".%s" extension.', extension))
    scan_with_clamd(env, data)
    return extension


def scan_with_clamd(env, data):
    """Optional ClamAV INSTREAM scan. Uploads are rejected if the configured scanner is unavailable."""
    target = get_param(env, 'clamd_socket')
    if not target:
        return
    try:
        if ':' in target and not target.startswith('/'):
            host, port = target.rsplit(':', 1)
            sock = socket.create_connection((host, int(port)), timeout=30)
        else:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(30)
            sock.connect(target)
        with sock:
            sock.sendall(b'zINSTREAM\0')
            for offset in range(0, len(data), 65536):
                chunk = data[offset:offset + 65536]
                sock.sendall(struct.pack('!L', len(chunk)) + chunk)
            sock.sendall(struct.pack('!L', 0))
            reply = sock.recv(4096).decode(errors='replace')
    except OSError as error:
        _logger.warning('Document virus scan unavailable: %s', error)
        raise UserError(_('The document virus scanner is unavailable. Please try again later.'))
    if 'FOUND' in reply:
        raise ValidationError(_('The file was rejected by the virus scanner.'))


class DocumentCategory(models.Model):
    _name = 'binaryaid.care.document.category'
    _description = 'Care Document Category'
    _order = 'applies_to, sequence, id'

    name = fields.Char(required=True, translate=True)
    applies_to = fields.Selection([('client', 'Client'), ('employee', 'Worker')], required=True, default='client')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text()
    requires_expiry = fields.Boolean(help='Each version must have an expiry date; alerts are raised before it.')
    expiry_alert_days = fields.Integer(default=30, string='Alert days before expiry')
    required = fields.Boolean(
        string='Required for rostering',
        help='Worker: publishing a shift is flagged when this document is missing or expired.')


class CareDocument(models.Model):
    _name = 'binaryaid.care.document'
    _description = 'Care Document'
    _inherit = ['mail.thread']
    _order = 'category_sequence, id'

    category_id = fields.Many2one('binaryaid.care.document.category', required=True, ondelete='restrict', tracking=True)
    category_sequence = fields.Integer(related='category_id.sequence', store=True)
    applies_to = fields.Selection(related='category_id.applies_to', store=True)
    name = fields.Char(compute='_compute_name', store=True, readonly=False)
    client_id = fields.Many2one('binaryaid.care.client', ondelete='restrict', index=True)
    employee_id = fields.Many2one('hr.employee', ondelete='restrict', index=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    active = fields.Boolean(default=True)
    version_ids = fields.One2many('binaryaid.care.document.version', 'document_id', string='Versions')
    current_version_id = fields.Many2one('binaryaid.care.document.version', compute='_compute_current', store=True)
    pending_version_count = fields.Integer(compute='_compute_current', store=True)
    version_count = fields.Integer(compute='_compute_current', store=True)
    expiry_date = fields.Date(related='current_version_id.expiry_date', store=True)
    alert_date = fields.Date(compute='_compute_alert_date', store=True,
                             help='Date from which the document is reported as expiring.')
    expiry_state = fields.Selection([('missing', 'No approved file'), ('valid', 'Valid'), ('expiring', 'Expiring'),
                                     ('expired', 'Expired')], compute='_compute_expiry_state', search='_search_expiry_state')
    retention_due = fields.Boolean(readonly=True, copy=False)
    access_log_ids = fields.One2many('binaryaid.care.document.access', 'document_id', string='Access Log')

    _owner_unique = models.UniqueIndex('(category_id, client_id, employee_id) WHERE active')

    @api.depends('category_id')
    def _compute_name(self):
        for document in self:
            document.name = document.name or document.category_id.name

    @api.depends('version_ids.state')
    def _compute_current(self):
        for document in self:
            versions = document.version_ids.sorted('version', reverse=True)
            approved = versions.filtered(lambda v: v.state == 'approved')
            document.current_version_id = approved[:1]
            document.pending_version_count = len(versions.filtered(lambda v: v.state == 'submitted'))
            document.version_count = len(versions)

    @api.depends('expiry_date', 'category_id.expiry_alert_days')
    def _compute_alert_date(self):
        for document in self:
            document.alert_date = document.expiry_date and (
                document.expiry_date - relativedelta(days=document.category_id.expiry_alert_days or 0))

    @api.depends('current_version_id', 'expiry_date', 'alert_date')
    @api.depends_context('date')
    def _compute_expiry_state(self):
        today = fields.Date.context_today(self)
        for document in self:
            if not document.current_version_id:
                document.expiry_state = 'missing'
            elif document.expiry_date and document.expiry_date < today:
                document.expiry_state = 'expired'
            elif document.alert_date and document.alert_date <= today:
                document.expiry_state = 'expiring'
            else:
                document.expiry_state = 'valid'

    def _search_expiry_state(self, operator, value):
        if operator not in ('=', 'in'):
            raise UserError(_('Unsupported search on document expiry status.'))
        values = [value] if operator == '=' else value
        today = fields.Date.context_today(self)
        domains = {
            'missing': [('current_version_id', '=', False)],
            'expired': [('current_version_id', '!=', False), ('expiry_date', '<', today)],
            'expiring': [('current_version_id', '!=', False), ('expiry_date', '>=', today), ('alert_date', '<=', today)],
            'valid': [('current_version_id', '!=', False), '|', ('expiry_date', '=', False), '&',
                      ('expiry_date', '>=', today), '|', ('alert_date', '=', False), ('alert_date', '>', today)],
        }
        result = []
        for state in values:
            result = ['|'] + result + domains[state] if result else domains[state]
        return result or [('id', '=', 0)]

    @api.constrains('client_id', 'employee_id', 'category_id')
    def _check_owner(self):
        for document in self:
            if bool(document.client_id) == bool(document.employee_id):
                raise ValidationError(_('A document belongs to exactly one client or one worker.'))
            if (document.category_id.applies_to == 'client') != bool(document.client_id):
                raise ValidationError(_('Use a %s document category for this record.',
                                        _('client') if document.client_id else _('worker')))

    def action_upload(self):
        self.ensure_one()
        self.check_access('read')
        return {'type': 'ir.actions.act_window', 'name': _('Upload new version'),
                'res_model': 'binaryaid.care.document.upload', 'view_mode': 'form', 'target': 'new',
                'context': {'default_document_id': self.id}}

    def action_preview(self):
        self.ensure_one()
        if not self.current_version_id:
            raise UserError(_('There is no approved version to preview.'))
        return self.current_version_id.action_preview()

    @api.model
    def _cron_retention_review(self):
        """Flag documents of archived clients/workers past the retention period; nothing is deleted."""
        cutoff = fields.Datetime.now() - relativedelta(years=int(get_param(self.env, 'retention_years')))
        documents = self.with_context(active_test=False).search([('retention_due', '=', False), '|',
            '&', ('client_id.active', '=', False), ('client_id.write_date', '<', cutoff),
            '&', ('employee_id.active', '=', False), ('employee_id.write_date', '<', cutoff)])
        documents.write({'retention_due': True})
        self.env['binaryaid.care.document.access'].search([('create_date', '<', cutoff)]).unlink()


class DocumentVersion(models.Model):
    _name = 'binaryaid.care.document.version'
    _description = 'Care Document Version'
    _order = 'document_id, version desc'

    document_id = fields.Many2one('binaryaid.care.document', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='document_id.company_id', store=True)
    version = fields.Integer(readonly=True)
    file_name = fields.Char(readonly=True)
    mimetype = fields.Char(readonly=True)
    file_size = fields.Integer(readonly=True)
    checksum = fields.Char(readonly=True)
    attachment_id = fields.Many2one('ir.attachment', readonly=True, ondelete='restrict')
    issue_date = fields.Date()
    expiry_date = fields.Date()
    note = fields.Text()
    state = fields.Selection([('submitted', 'Awaiting approval'), ('approved', 'Approved'), ('rejected', 'Rejected')],
                             default='submitted', required=True, readonly=True)
    uploaded_by_id = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)
    reviewed_by_id = fields.Many2one('res.users', readonly=True)
    reviewed_on = fields.Datetime(readonly=True)
    review_note = fields.Text(readonly=True)

    def _is_document_manager(self, document):
        user = self.env.user
        if document.client_id:
            return user.has_group('binaryaid_work_management.group_work_admin')
        return user.has_group('hr.group_hr_user')

    @api.model
    def _create_version(self, document, data, filename, expiry_date=False, issue_date=False, note=False):
        """The only way to add file content: validates, stores the attachment and appends a version."""
        document.check_access('read')
        manager = self._is_document_manager(document)
        if not manager and not (document.employee_id and document.employee_id.user_id == self.env.user):
            raise AccessError(_('You cannot upload documents for this record.'))
        extension = validate_upload(self.env, data, filename)
        if document.category_id.requires_expiry and not expiry_date:
            raise ValidationError(_('%s requires an expiry date.', document.category_id.name))
        document.lock_for_update()
        number = (max(document.version_ids.mapped('version')) if document.version_ids else 0) + 1
        version = self.sudo().create({
            'document_id': document.id, 'version': number, 'file_name': filename,
            'file_size': len(data), 'checksum': hashlib.sha256(data).hexdigest(),
            'issue_date': issue_date, 'expiry_date': expiry_date, 'note': note,
            'uploaded_by_id': self.env.uid,
            'state': 'approved' if manager else 'submitted',
            'reviewed_by_id': self.env.uid if manager else False,
            'reviewed_on': fields.Datetime.now() if manager else False,
        })
        attachment = self.env['ir.attachment'].sudo().create({
            'name': filename, 'raw': data, 'res_model': self._name, 'res_id': version.id,
            'company_id': document.company_id.id})
        version.sudo().write({'attachment_id': attachment.id, 'mimetype': attachment.mimetype})
        document.sudo().message_post(body=_('Version %(number)s uploaded (%(file)s, .%(ext)s).',
                                            number=number, file=filename, ext=extension))
        return version

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise AccessError(_('Upload documents with the Upload action.'))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            raise AccessError(_('Document versions are kept unchanged. Upload a new version instead.'))
        return super().write(vals)

    def unlink(self):
        raise AccessError(_('Document versions are kept for history.'))

    def _review(self, state, note=False):
        for version in self:
            if not version._is_document_manager(version.document_id):
                raise AccessError(_('Only document managers can approve or reject versions.'))
            if version.state != 'submitted':
                raise UserError(_('Only versions awaiting approval can be reviewed.'))
            version.sudo().write({'state': state, 'reviewed_by_id': self.env.uid,
                                  'reviewed_on': fields.Datetime.now(), 'review_note': note})
            version.document_id.sudo().message_post(body=_('Version %(number)s %(state)s.', number=version.version,
                                                           state=dict(self._fields['state'].selection)[state]))

    def action_approve(self):
        self._review('approved')

    def action_reject(self):
        self.ensure_one()
        if not self._is_document_manager(self.document_id):
            raise AccessError(_('Only document managers can approve or reject versions.'))
        return {'type': 'ir.actions.act_window', 'name': _('Reject version'), 'res_model': 'binaryaid.care.document.review',
                'view_mode': 'form', 'target': 'new', 'context': {'default_version_id': self.id}}

    def action_preview(self):
        self.ensure_one()
        self.check_access('read')
        return {'type': 'ir.actions.act_url', 'url': '/care/document/%s/preview' % self.id, 'target': 'new'}

    def action_download(self):
        self.ensure_one()
        self.check_access('read')
        return {'type': 'ir.actions.act_url', 'url': '/care/document/%s/download' % self.id, 'target': 'self'}


class DocumentAccess(models.Model):
    _name = 'binaryaid.care.document.access'
    _description = 'Care Document Access Log'
    _order = 'id desc'

    document_id = fields.Many2one('binaryaid.care.document', required=True, ondelete='cascade', index=True)
    version_id = fields.Many2one('binaryaid.care.document.version', ondelete='cascade')
    company_id = fields.Many2one(related='document_id.company_id', store=True)
    user_id = fields.Many2one('res.users', required=True, readonly=True)
    action = fields.Selection([('preview', 'Preview'), ('download', 'Download')], required=True, readonly=True)
    ip_address = fields.Char(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise AccessError(_('Access logs are recorded automatically.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('Access logs cannot be changed.'))
