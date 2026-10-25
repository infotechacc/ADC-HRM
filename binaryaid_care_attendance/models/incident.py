from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from odoo.addons.binaryaid_care.models.document import BLOCKED_SIGNATURES, SIGNATURES, scan_with_clamd
from odoo.addons.binaryaid_care.models.tools import get_param

SEVERITY_RANK = {'low': 0, 'medium': 1, 'high': 2, 'critical': 3}
MEDIA_EXTENSIONS = ['jpg', 'jpeg', 'png', 'heic', 'mp4', 'mov', 'webm', 'm4a', 'mp3', 'wav', 'ogg', 'pdf']


class IncidentCategory(models.Model):
    _name = 'binaryaid.care.incident.category'
    _description = 'Incident Category'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)


class Incident(models.Model):
    _name = 'binaryaid.care.incident'
    _description = 'Incident Report'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'occurred_at desc, id desc'
    _mail_post_access = 'read'

    name = fields.Char(string='Reference', readonly=True, copy=False, default=lambda self: _('New'))
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    reported_by_id = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True, index=True)
    reporter_employee_id = fields.Many2one('hr.employee', readonly=True,
                                           default=lambda self: self.env.user.employee_id)
    client_id = fields.Many2one('binaryaid.care.client', required=True, tracking=True,
                                domain="[('id', 'in', allowed_client_ids)]")
    allowed_client_ids = fields.Many2many('binaryaid.care.client', compute='_compute_allowed_clients')
    shift_id = fields.Many2one('binaryaid.work.shift', readonly=True)
    location = fields.Char(required=True, tracking=True)
    occurred_at = fields.Datetime(required=True, default=fields.Datetime.now, tracking=True)
    category_id = fields.Many2one('binaryaid.care.incident.category', required=True, tracking=True)
    severity = fields.Selection([('low', 'Low'), ('medium', 'Medium'), ('high', 'High'), ('critical', 'Critical')],
                                required=True, default='medium', tracking=True)
    description = fields.Text(required=True)
    immediate_action = fields.Text(string='Immediate action taken', required=True)
    attachment_ids = fields.Many2many('ir.attachment', 'binaryaid_incident_attachment_rel', 'incident_id', 'attachment_id',
                                      string='Photos, video or audio')
    state = fields.Selection([('submitted', 'Submitted'), ('in_review', 'In review'), ('action', 'Action required'),
                              ('closed', 'Closed')], default='submitted', required=True, tracking=True, index=True)
    owner_id = fields.Many2one('res.users', string='Owner', tracking=True,
                               domain=lambda self: [('group_ids', 'in', self.env.ref('binaryaid_care.group_care_reviewer').ids)])
    outcome = fields.Text(tracking=True)
    external_notice = fields.Html(compute='_compute_external_notice')

    def _compute_external_notice(self):
        for incident in self:
            incident.external_notice = _('This is an internal ADC report. It does not submit any external or '
                                         'regulatory notification; reviewers must make required notifications separately.')

    @api.depends_context('uid')
    def _compute_allowed_clients(self):
        clients = self._permitted_clients(fields.Datetime.now())
        for incident in self:
            incident.allowed_client_ids = clients

    def _is_reviewer(self):
        return self.env.user.has_group('binaryaid_care.group_care_reviewer')

    def _permitted_clients(self, when):
        """Clients the worker supports around this time (published shifts within a day)."""
        if self._is_reviewer():
            return self.env['binaryaid.care.client'].search([])
        shifts = self.env['binaryaid.work.shift'].sudo().search([
            ('user_id', '=', self.env.uid), ('state', '=', 'published'), ('client_id', '!=', False),
            ('start', '<=', when + timedelta(days=1)), ('end', '>=', when - timedelta(days=1))])
        return shifts.client_id

    def _validate_attachments(self):
        """Photos, video and audio only: size, extension, content signature and optional virus scan."""
        limit_mb = int(get_param(self.env, 'incident_max_upload_mb'))
        for attachment in self.attachment_ids.sudo():
            if attachment.file_size > limit_mb * 1024 * 1024:
                raise ValidationError(_('%(name)s is larger than %(mb)s MB.', name=attachment.name, mb=limit_mb))
            extension = (attachment.name or '').rsplit('.', 1)[-1].lower() if '.' in (attachment.name or '') else ''
            if extension not in MEDIA_EXTENSIONS:
                raise ValidationError(_('%s is not an accepted photo, video, audio or PDF file.', attachment.name))
            data = attachment.raw or b''
            if any(data.startswith(sig) for sig in BLOCKED_SIGNATURES):
                raise ValidationError(_('Executable files cannot be attached.'))
            signatures = SIGNATURES.get(extension)
            if signatures:
                head = data[4:8] if signatures == [b'ftyp'] else data
                if not any(head.startswith(sig) for sig in signatures):
                    raise ValidationError(_('%s does not match its file type.', attachment.name))
            scan_with_clamd(self.env, data)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals['name'] = self.env['ir.sequence'].sudo().next_by_code('binaryaid.care.incident') or _('New')
            vals['reported_by_id'] = self.env.uid
            vals['reporter_employee_id'] = self.env.user.employee_id.id
            vals.pop('state', None)
            if not self._is_reviewer():
                vals.pop('owner_id', None)
        incidents = super().create(vals_list)
        for incident in incidents:
            when = incident.occurred_at
            if when > fields.Datetime.now() + timedelta(minutes=5):
                raise ValidationError(_('The occurrence time cannot be in the future.'))
            if incident.client_id not in self._permitted_clients(when):
                raise AccessError(_('You can report incidents only for clients you support around that time.'))
            shift = self.env['binaryaid.work.shift'].sudo().search([
                ('user_id', '=', incident.reported_by_id.id), ('client_id', '=', incident.client_id.id),
                ('state', '=', 'published'), ('start', '<=', when + timedelta(hours=2)), ('end', '>=', when - timedelta(hours=2))],
                order='start desc', limit=1)
            incident.sudo().shift_id = shift
            incident.attachment_ids.sudo().write({'res_model': self._name, 'res_id': incident.id})
            incident._validate_attachments()
            incident._escalate()
        return incidents

    def write(self, vals):
        if not self.env.su and not self._is_reviewer():
            raise AccessError(_('Submitted incident reports can only be updated by care reviewers.'))
        result = super().write(vals)
        if 'attachment_ids' in vals:
            self.attachment_ids.sudo().write({'res_model': self._name})
            self._validate_attachments()
        return result

    def unlink(self):
        raise AccessError(_('Incident reports are kept for history.'))

    def _escalate(self):
        threshold = SEVERITY_RANK.get(get_param(self.env, 'incident_escalation_severity'), 2)
        reviewers = self.env.ref('binaryaid_care.group_care_reviewer').sudo().user_ids.filtered('active')
        for incident in self:
            if SEVERITY_RANK[incident.severity] < threshold:
                continue
            for user in reviewers:
                incident.sudo().activity_schedule(
                    'mail.mail_activity_data_todo', user_id=user.id,
                    summary=_('Review %(sev)s incident %(ref)s', sev=incident.severity, ref=incident.name))

    def _set_state(self, state):
        if not self._is_reviewer():
            raise AccessError(_('Only care reviewers can change incident status.'))
        self.write({'state': state, 'owner_id': self.owner_id.id or self.env.uid})

    def action_review(self):
        self._set_state('in_review')

    def action_require_action(self):
        self._set_state('action')

    def action_close(self):
        if any(not (incident.outcome or '').strip() for incident in self):
            raise UserError(_('Record the outcome before closing the incident.'))
        self._set_state('closed')
