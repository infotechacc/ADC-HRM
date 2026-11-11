import pytz

from odoo import Command, api, fields, models, _
from odoo.exceptions import ValidationError

ADMIN_GROUPS = 'binaryaid_work_management.group_work_admin,binaryaid_care.group_care_reviewer'
# Every time zone, as on shifts; Australia/Sydney stays the default.
TIMEZONES = [(tz, tz) for tz in pytz.all_timezones]


class CarePlan(models.Model):
    _name = 'binaryaid.care.plan'
    _description = 'Care Plan'
    _order = 'name, id'

    name = fields.Char(string='Plan name', required=True)
    line_ids = fields.One2many('binaryaid.care.plan.line', 'plan_id', string='Services', copy=True)


class CarePlanLine(models.Model):
    _name = 'binaryaid.care.plan.line'
    _description = 'Care Plan Service'
    _order = 'plan_id, sequence, id'

    plan_id = fields.Many2one('binaryaid.care.plan', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Service', required=True)


class CareClient(models.Model):
    _name = 'binaryaid.care.client'
    _description = 'Client'
    _inherit = ['mail.thread']
    _order = 'name, id'
    _check_company_auto = True

    name = fields.Char(string='Client name', required=True, tracking=True)
    reference = fields.Char(string='Client ID', copy=False)
    status = fields.Selection([('active', 'Active'), ('on_hold', 'On hold'), ('inactive', 'Inactive')],
                              default='active', required=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    phone = fields.Char(string='Client phone', groups=ADMIN_GROUPS)
    email = fields.Char(string='Client email', groups=ADMIN_GROUPS)
    contact_name = fields.Char(string='Alternative contact name', groups=ADMIN_GROUPS)
    contact_phone = fields.Char(string='Alternative contact phone', groups=ADMIN_GROUPS)
    contact_email = fields.Char(string='Alternative contact email', groups=ADMIN_GROUPS)
    plan_ids = fields.Many2many('binaryaid.care.plan', string='Care plans', groups=ADMIN_GROUPS)
    service_ids = fields.One2many('binaryaid.care.client.service', 'client_id', string='Services', groups=ADMIN_GROUPS)
    document_ids = fields.One2many('binaryaid.care.client.document', 'client_id', string='Documents', groups=ADMIN_GROUPS)
    location_ids = fields.One2many('binaryaid.care.service.location', 'client_id', string='Service locations')
    shift_ids = fields.One2many('binaryaid.work.shift', 'client_id', string='Shifts')

    # The client's service location, edited directly on the client form.
    service_location = fields.Char(compute='_compute_location', inverse='_inverse_location', string='Service location')
    latitude = fields.Float(compute='_compute_location', inverse='_inverse_location', digits=(10, 7))
    longitude = fields.Float(compute='_compute_location', inverse='_inverse_location', digits=(10, 7))
    timezone = fields.Selection(TIMEZONES, compute='_compute_location', inverse='_inverse_location')
    radius_m = fields.Float(string='Clock radius (m)', digits=(12, 2), compute='_compute_location', inverse='_inverse_location')

    _reference_unique = models.Constraint('UNIQUE(company_id, reference)', 'The client ID must be unique.')

    def _plan_service_split(self):
        """Service lines of plans that are no longer selected, and the services of selected
        plans that are still missing. Lines added only for this client are always kept."""
        self.ensure_one()
        selected = set(self.plan_ids._origin.ids)
        removed = self.service_ids.filtered(lambda l: l.plan_id and l.plan_id._origin.id not in selected)
        present = {(l.plan_id._origin.id, l.name) for l in self.service_ids - removed if l.plan_id}
        missing = [{'plan_id': plan.id, 'name': line.name, 'sequence': line.sequence}
                   for plan in self.plan_ids._origin for line in plan.line_ids if (plan.id, line.name) not in present]
        return removed, missing

    @api.onchange('plan_ids')
    def _onchange_plan_ids(self):
        removed, missing = self._plan_service_split()
        if removed:
            self.service_ids -= removed
        if missing:
            self.service_ids = [Command.create(vals) for vals in missing]

    @api.model_create_multi
    def create(self, vals_list):
        clients = super().create(vals_list)
        clients._sync_plan_services()
        return clients

    def write(self, vals):
        result = super().write(vals)
        if 'plan_ids' in vals:
            self._sync_plan_services()
        return result

    def _sync_plan_services(self):
        for client in self:
            removed, missing = client._plan_service_split()
            removed.unlink()
            if missing:
                client.service_ids = [Command.create(vals) for vals in missing]

    @api.depends('location_ids.name', 'location_ids.latitude', 'location_ids.longitude',
                 'location_ids.timezone', 'location_ids.radius_m')
    def _compute_location(self):
        for client in self:
            location = client.location_ids[:1]
            client.service_location = location.name
            client.latitude = location.latitude
            client.longitude = location.longitude
            client.timezone = location.timezone or 'Australia/Sydney'
            client.radius_m = location.radius_m or 50

    def _inverse_location(self):
        for client in self:
            values = {'name': client.service_location or client.name, 'latitude': client.latitude,
                      'longitude': client.longitude, 'timezone': client.timezone or 'Australia/Sydney',
                      'radius_m': client.radius_m}
            location = client.location_ids[:1]
            if location:
                location.write(values)
            else:
                self.env['binaryaid.care.service.location'].create(
                    dict(values, client_id=client.id, radius_m=client.radius_m or 50))


class ClientService(models.Model):
    _name = 'binaryaid.care.client.service'
    _description = 'Client Service'
    _order = 'client_id, sequence, id'

    client_id = fields.Many2one('binaryaid.care.client', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='client_id.company_id', store=True)
    sequence = fields.Integer(default=100)
    name = fields.Char(string='Service', required=True)
    plan_id = fields.Many2one('binaryaid.care.plan', string='Care plan', ondelete='cascade',
                              help='Empty for services added only for this client.')


class ClientDocument(models.Model):
    _name = 'binaryaid.care.client.document'
    _description = 'Client Document'
    _order = 'id desc'

    client_id = fields.Many2one('binaryaid.care.client', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='client_id.company_id', store=True)
    file = fields.Binary(string='Document', required=True, attachment=True)
    name = fields.Char(string='File name')

    def _content_url(self, download):
        self.ensure_one()
        self.check_access('read')
        return '/web/content/%s/%s/file/%s?download=%s' % (self._name, self.id, self.name or 'document',
                                                          'true' if download else 'false')

    def action_preview(self):
        return {'type': 'ir.actions.act_url', 'url': self._content_url(False), 'target': 'new'}

    def action_download(self):
        return {'type': 'ir.actions.act_url', 'url': self._content_url(True), 'target': 'self'}


class ServiceLocation(models.Model):
    _name = 'binaryaid.care.service.location'
    _description = 'Client Service Location'
    _order = 'client_id, sequence, id'

    client_id = fields.Many2one('binaryaid.care.client', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='client_id.company_id', store=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    name = fields.Char(string='Service location', required=True)
    latitude = fields.Float(digits=(10, 7))
    longitude = fields.Float(digits=(10, 7))
    timezone = fields.Selection(TIMEZONES, required=True, default='Australia/Sydney')
    radius_m = fields.Float(string='Clock radius (m)', digits=(12, 2), default=50,
                              help='Maximum distance from these coordinates for check in and check out.')
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
            if location.radius_m <= 0:
                raise ValidationError(_('The clock radius must be more than 0 metres.'))
