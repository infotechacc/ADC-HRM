import pytz

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

ADMIN_GROUPS = 'binaryaid_work_management.group_work_admin,binaryaid_care.group_care_reviewer'


class CareClient(models.Model):
    _name = 'binaryaid.care.client'
    _description = 'Client / Participant'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name, id'
    _check_company_auto = True

    name = fields.Char(required=True, tracking=True)
    reference = fields.Char(string='Client / Participant ID', required=True, tracking=True, copy=False)
    status = fields.Selection([('active', 'Active'), ('on_hold', 'On hold'), ('inactive', 'Inactive')],
                              default='active', required=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    phone = fields.Char(groups=ADMIN_GROUPS)
    email = fields.Char(groups=ADMIN_GROUPS)
    date_of_birth = fields.Date(groups=ADMIN_GROUPS)
    care_requirements = fields.Html(groups=ADMIN_GROUPS, tracking=True,
                                    help='Approved care requirements. Never shown on dashboard cards.')
    internal_notes = fields.Text(groups=ADMIN_GROUPS)
    contact_ids = fields.One2many('binaryaid.care.client.contact', 'client_id', string='Authorised contacts',
                                  groups=ADMIN_GROUPS)
    location_ids = fields.One2many('binaryaid.care.service.location', 'client_id', string='Service locations')
    document_ids = fields.One2many('binaryaid.care.document', 'client_id', string='Documents', groups=ADMIN_GROUPS)
    request_ids = fields.One2many('binaryaid.care.client.request', 'client_id', string='Requests', groups=ADMIN_GROUPS)
    shift_ids = fields.One2many('binaryaid.work.shift', 'client_id', string='Shifts')
    shift_count = fields.Integer(compute='_compute_counts', groups=ADMIN_GROUPS)
    request_count = fields.Integer(compute='_compute_counts', groups=ADMIN_GROUPS)
    document_issue_count = fields.Integer(compute='_compute_counts', groups=ADMIN_GROUPS,
                                          string='Missing or expiring documents')

    _reference_unique = models.Constraint('UNIQUE(company_id, reference)', 'The client ID must be unique.')

    def _compute_counts(self):
        shifts = dict(self.env['binaryaid.work.shift']._read_group([('client_id', 'in', self.ids)], ['client_id'], ['__count']))
        requests = dict(self.env['binaryaid.care.client.request']._read_group(
            [('client_id', 'in', self.ids), ('state', 'in', ['submitted', 'in_review'])], ['client_id'], ['__count']))
        categories = self.env['binaryaid.care.document.category'].search_count([('applies_to', '=', 'client')])
        for client in self:
            documents = client.document_ids
            ok = documents.filtered(lambda d: d.expiry_state == 'valid')
            client.shift_count = shifts.get(client, 0)
            client.request_count = requests.get(client, 0)
            client.document_issue_count = max(categories - len(ok), 0)

    def write(self, vals):
        result = super().write(vals)
        if vals.get('active') is False or vals.get('status') == 'inactive':
            # Deactivated clients lose portal access; their history stays linked.
            self.sudo().contact_ids.user_id.filtered('active').write({'active': False})
        return result

    def action_open_shifts(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Shifts for %s', self.name), 'res_model': 'binaryaid.work.shift',
                'view_mode': 'list,calendar,form', 'domain': [('client_id', '=', self.id)],
                'context': {'default_client_id': self.id, 'search_default_group_employee': 0}}

    def action_open_requests(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Requests from %s', self.name),
                'res_model': 'binaryaid.care.client.request', 'view_mode': 'list,form',
                'domain': [('client_id', '=', self.id)], 'context': {'default_client_id': self.id}}

    def action_prepare_documents(self):
        """Create one empty document slot per client category, ready for upload."""
        categories = self.env['binaryaid.care.document.category'].search([('applies_to', '=', 'client')])
        for client in self:
            missing = categories - client.document_ids.category_id
            self.env['binaryaid.care.document'].create([
                {'client_id': client.id, 'category_id': category.id, 'company_id': client.company_id.id}
                for category in missing])
        return True

    @api.model_create_multi
    def create(self, vals_list):
        clients = super().create(vals_list)
        clients.action_prepare_documents()
        return clients


class ClientContact(models.Model):
    _name = 'binaryaid.care.client.contact'
    _description = 'Client Authorised Contact'
    _order = 'client_id, sequence, id'

    client_id = fields.Many2one('binaryaid.care.client', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='client_id.company_id', store=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    contact_type = fields.Selection([('participant', 'Participant'), ('representative', 'Authorised representative'),
                                     ('other', 'Other contact')], required=True, default='representative')
    relationship = fields.Char()
    phone = fields.Char()
    email = fields.Char()
    is_authorised = fields.Boolean(string='Authorised', default=True,
                                   help='May receive information about and make decisions for the client.')
    user_id = fields.Many2one('res.users', string='Portal login', readonly=True, copy=False, ondelete='set null')
    portal_active = fields.Boolean(compute='_compute_portal_active')

    @api.depends('user_id.active')
    def _compute_portal_active(self):
        for contact in self:
            contact.portal_active = bool(contact.user_id.sudo().active)

    def action_grant_portal(self):
        """Give the contact a restricted portal login to submit and follow requests."""
        for contact in self:
            if not contact.is_authorised or contact.contact_type == 'other':
                raise UserError(_('Only the participant or an authorised representative can receive a login.'))
            if not contact.email:
                raise UserError(_('Add an email address for %s first.', contact.name))
            if contact.client_id.status == 'inactive' or not contact.client_id.active:
                raise UserError(_('The client is not active.'))
            user = contact.user_id.sudo().with_context(active_test=False)
            if user:
                user.write({'active': True})
            else:
                existing = self.env['res.users'].sudo().with_context(active_test=False).search(
                    [('login', '=', contact.email)], limit=1)
                if existing and not existing.share:
                    raise UserError(_('%s already belongs to an internal user.', contact.email))
                user = existing or self.env['res.users'].sudo().with_context(no_reset_password=True).create({
                    'name': contact.name, 'login': contact.email, 'email': contact.email,
                    'company_id': contact.company_id.id, 'company_ids': [(6, 0, contact.company_id.ids)],
                    'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])]})
                user.write({'active': True})
                contact.sudo().user_id = user
            user.partner_id.signup_prepare()
            contact.client_id.message_post(body=_('Portal access granted to %s.', contact.name))
        return True

    def action_revoke_portal(self):
        for contact in self:
            contact.user_id.sudo().write({'active': False})
            contact.client_id.message_post(body=_('Portal access revoked for %s.', contact.name))
        return True


class ServiceLocation(models.Model):
    _name = 'binaryaid.care.service.location'
    _description = 'Client Service Location'
    _inherit = ['mail.thread']
    _order = 'client_id, sequence, id'

    client_id = fields.Many2one('binaryaid.care.client', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='client_id.company_id', store=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    name = fields.Char(required=True, tracking=True)
    street = fields.Char(tracking=True)
    city = fields.Char(string='Suburb', tracking=True)
    state_id = fields.Many2one('res.country.state', tracking=True)
    zip = fields.Char(string='Postcode', tracking=True)
    country_id = fields.Many2one('res.country', default=lambda self: self.env.ref('base.au', raise_if_not_found=False))
    latitude = fields.Float(digits=(10, 7), tracking=True)
    longitude = fields.Float(digits=(10, 7), tracking=True)
    coordinates_verified = fields.Boolean(readonly=True, tracking=True)
    verified_by_id = fields.Many2one('res.users', readonly=True)
    verified_on = fields.Datetime(readonly=True)
    timezone = fields.Selection([(tz, tz) for tz in pytz.all_timezones if tz.startswith('Australia/')] + [('UTC', 'UTC')],
                                required=True, default='Australia/Sydney', tracking=True)
    radius_m = fields.Integer(string='Clock radius (m)', default=50, tracking=True,
                              help='Maximum distance from these coordinates for sign in and sign out.')
    map_url = fields.Char(compute='_compute_map_url')

    @api.depends('latitude', 'longitude')
    def _compute_map_url(self):
        for location in self:
            location.map_url = ('https://www.google.com/maps/search/?api=1&query=%s,%s' % (location.latitude, location.longitude)
                                if location.has_coordinates() else False)

    def has_coordinates(self):
        self.ensure_one()
        return bool(self.latitude or self.longitude)

    @api.depends('client_id.name', 'name')
    def _compute_display_name(self):
        for location in self:
            location.display_name = location.name if self.env.context.get('short_location') else (
                '%s – %s' % (location.client_id.name, location.name) if location.client_id else location.name)

    @api.constrains('latitude', 'longitude', 'radius_m')
    def _check_coordinates(self):
        for location in self:
            if not (-90 <= location.latitude <= 90 and -180 <= location.longitude <= 180):
                raise ValidationError(_('Latitude must be between -90 and 90 and longitude between -180 and 180.'))
            if location.radius_m <= 0 or location.radius_m > 1000:
                raise ValidationError(_('The clock radius must be between 1 and 1000 metres.'))

    def write(self, vals):
        if {'latitude', 'longitude'} & set(vals) and not self.env.context.get('binaryaid_verifying'):
            vals = dict(vals, coordinates_verified=False, verified_by_id=False, verified_on=False)
        return super().write(vals)

    def action_verify_coordinates(self):
        for location in self:
            if not location.has_coordinates():
                raise UserError(_('Enter the latitude and longitude of %s first.', location.name))
        self.with_context(binaryaid_verifying=True).write({
            'coordinates_verified': True, 'verified_by_id': self.env.uid, 'verified_on': fields.Datetime.now()})
        return True

    def address_text(self):
        self.ensure_one()
        return ', '.join(filter(None, [self.street, self.city, self.state_id.code, self.zip]))
