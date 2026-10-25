from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class WorkShift(models.Model):
    _inherit = 'binaryaid.work.shift'

    # A draft may be created before a worker is chosen: it is an unfilled shift.
    # A worker is required to publish (see _check_publication_eligibility).
    employee_id = fields.Many2one(required=False)
    is_unfilled = fields.Boolean(compute='_compute_is_unfilled', search='_search_is_unfilled', string='Unfilled')

    client_id = fields.Many2one('binaryaid.care.client', string='Client', ondelete='restrict', tracking=True,
                                index=True, check_company=True)
    service_location_id = fields.Many2one('binaryaid.care.service.location', string='Service location',
                                          ondelete='restrict', tracking=True,
                                          domain="[('client_id', '=', client_id)]")
    client_request_id = fields.Many2one('binaryaid.care.client.request', string='Client request', ondelete='set null',
                                        tracking=True, domain="[('client_id', '=', client_id), ('state', 'in', ['approved', 'scheduled'])]")
    location = fields.Char(compute='_compute_location', store=True, readonly=False, tracking=True)
    timezone = fields.Selection(compute='_compute_timezone', store=True, readonly=False, precompute=True)
    location_latitude = fields.Float(related='service_location_id.latitude', digits=(10, 7))
    location_longitude = fields.Float(related='service_location_id.longitude', digits=(10, 7))
    location_verified = fields.Boolean(related='service_location_id.coordinates_verified')
    client_requirements = fields.Html(related='client_id.care_requirements', string='Approved care requirements',
                                      groups='binaryaid_work_management.group_work_admin,binaryaid_care.group_care_reviewer')
    approved_request_ids = fields.Many2many('binaryaid.care.client.request', compute='_compute_approved_requests',
                                            string='Approved client requests',
                                            groups='binaryaid_work_management.group_work_admin')
    binaryaid_revision = fields.Integer(readonly=True, copy=False, default=0)
    binaryaid_revision_token = fields.Char(compute='_compute_revision_token', inverse='_inverse_revision_token')

    @api.depends('employee_id')
    def _compute_is_unfilled(self):
        for shift in self:
            shift.is_unfilled = not shift.employee_id

    def _search_is_unfilled(self, operator, value):
        if operator not in ('=', '!='):
            raise UserError(_('Unsupported search on unfilled shifts.'))
        unfilled = (operator == '=') == bool(value)
        return [('employee_id', '=' if unfilled else '!=', False)]

    @api.constrains('start', 'end', 'unpaid_break_minutes', 'employee_id', 'task_ids',
                    'company_id', 'notice_hours', 'min_rest_hours', 'weekly_hours_limit')
    def _check_details(self):
        unfilled = self.filtered(lambda s: not s.employee_id)
        for shift in unfilled:
            if shift.state != 'draft':
                raise ValidationError(_('Assign a worker before publishing a shift.'))
            if shift.end <= shift.start or shift.unpaid_break_minutes < 0 or shift.planned_hours <= 0:
                raise ValidationError(_('End must follow start and unpaid breaks must leave positive paid hours.'))
            if shift.task_ids:
                raise ValidationError(_('Assign a worker before adding shift tasks.'))
        return super(WorkShift, self - unfilled)._check_details()

    @api.depends('service_location_id', 'service_location_id.name')
    def _compute_location(self):
        for shift in self:
            # Published shifts keep the location text they were published with.
            if shift.service_location_id and shift.state == 'draft':
                address = shift.service_location_id.address_text()
                shift.location = '%s%s' % (shift.service_location_id.name, ' (%s)' % address if address else '')
            else:
                shift.location = shift.location

    @api.depends('service_location_id')
    def _compute_timezone(self):
        for shift in self:
            if shift.service_location_id and shift.state in (False, 'draft'):
                shift.timezone = shift.service_location_id.timezone
            elif not shift.timezone:
                shift.timezone = 'Australia/Sydney'

    @api.depends('client_id')
    def _compute_approved_requests(self):
        for shift in self:
            shift.approved_request_ids = self.env['binaryaid.care.client.request'].search([
                ('client_id', '=', shift.client_id.id), ('state', 'in', ['approved', 'scheduled'])], limit=20) \
                if shift.client_id else False

    def _compute_revision_token(self):
        for shift in self:
            shift.binaryaid_revision_token = str(shift.binaryaid_revision)

    def _inverse_revision_token(self):
        """Checked in write(); kept so the form may send the token it loaded."""

    @api.onchange('client_id')
    def _onchange_client_id(self):
        if self.service_location_id.client_id != self.client_id:
            self.service_location_id = self.client_id.location_ids[:1]
        if self.client_id and not self.name:
            self.name = _('%s support', self.client_id.name)

    @api.constrains('client_id', 'service_location_id', 'client_request_id')
    def _check_client_links(self):
        for shift in self:
            if shift.service_location_id and shift.service_location_id.client_id != shift.client_id:
                raise ValidationError(_('The service location must belong to the selected client.'))
            if shift.client_request_id and shift.client_request_id.client_id != shift.client_id:
                raise ValidationError(_('The client request must belong to the selected client.'))

    def write(self, vals):
        token = vals.pop('binaryaid_revision_token', None)
        if token is not None:
            # Optimistic lock: the form sends the revision it loaded; a different current
            # revision means someone else saved or changed this shift in the meantime.
            self.lock_for_update()
            self.invalidate_recordset(['binaryaid_revision'])
            if any(str(shift.binaryaid_revision) != str(token) for shift in self):
                raise UserError(_('This shift was changed by someone else while you were editing it. '
                                  'Discard your changes and reload the shift, then try again.'))
        if not vals:
            return True
        result = super().write(vals)
        self._bump_revision()
        return result

    def _roster_transition_write(self, vals):
        result = super()._roster_transition_write(vals)
        self._bump_revision()
        return result

    def _bump_revision(self):
        if self.ids:
            self.env.cr.execute('UPDATE binaryaid_work_shift SET binaryaid_revision = binaryaid_revision + 1 '
                                'WHERE id IN %s', [tuple(self.ids)])
            self.invalidate_recordset(['binaryaid_revision', 'binaryaid_revision_token'])

    def _missing_worker_documents(self):
        """Required worker document categories that are missing, unapproved or expired at shift start."""
        self.ensure_one()
        if not self.employee_id:
            return []
        categories = self.env['binaryaid.care.document.category'].sudo().search(
            [('applies_to', '=', 'employee'), ('required', '=', True)])
        documents = self.env['binaryaid.care.document'].sudo().search(
            [('employee_id', '=', self.employee_id.id), ('category_id', 'in', categories.ids)])
        problems = []
        for category in categories:
            document = documents.filtered(lambda d: d.category_id == category)[:1]
            version = document.current_version_id
            if not version:
                problems.append(_('%s is missing', category.name))
            elif version.expiry_date and version.expiry_date < self.start.date():
                problems.append(_('%s expired on %s', category.name, version.expiry_date))
        return problems

    def _review_warnings(self):
        warnings = super()._review_warnings()
        if self.client_id and not self.service_location_id:
            warnings.append(_('No service location is selected for this client shift.'))
        elif self.service_location_id and not self.service_location_id.has_coordinates():
            warnings.append(_('The service location has no coordinates; sign in cannot be location verified.'))
        elif self.service_location_id and not self.service_location_id.coordinates_verified:
            warnings.append(_('The service location coordinates are not verified.'))
        for problem in self._missing_worker_documents():
            warnings.append(_('Worker document: %s.', problem))
        return warnings

    def _check_publication_eligibility(self):
        if self.filtered(lambda s: not s.employee_id):
            raise ValidationError(_('Assign a worker before publishing this shift.'))
        super()._check_publication_eligibility()
        for shift in self:
            if shift.client_id and (not shift.client_id.active or shift.client_id.status != 'active'):
                raise ValidationError(_('%s is not an active client.', shift.client_id.name))

    def action_publish(self):
        result = super().action_publish()
        self.client_request_id.filtered(lambda r: r.state == 'approved').sudo().write({'state': 'scheduled'})
        self.client_request_id.filtered(lambda r: r.state == 'scheduled')._notify_requester()
        return result
