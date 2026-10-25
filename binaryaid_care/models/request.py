from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


def float_to_time(value):
    hours = int(value)
    return time(min(hours, 23), int(round((value - hours) * 60)) % 60)


class ClientRequest(models.Model):
    _name = 'binaryaid.care.client.request'
    _description = 'Client Support Request'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _order = 'state_priority, preferred_date_from, id desc'
    _check_company_auto = True

    name = fields.Char(string='Reference', readonly=True, copy=False, default=lambda self: _('New'))
    client_id = fields.Many2one('binaryaid.care.client', required=True, ondelete='restrict', tracking=True,
                                check_company=True, index=True)
    company_id = fields.Many2one(related='client_id.company_id', store=True)
    contact_id = fields.Many2one('binaryaid.care.client.contact', domain="[('client_id', '=', client_id)]",
                                 string='Submitted for')
    requested_by_id = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)
    support_needs = fields.Text(required=True, tracking=True)
    preferred_date_from = fields.Date(required=True, tracking=True)
    preferred_date_to = fields.Date(tracking=True)
    preferred_start_time = fields.Float(tracking=True)
    preferred_end_time = fields.Float(tracking=True)
    location_id = fields.Many2one('binaryaid.care.service.location', domain="[('client_id', '=', client_id)]",
                                  tracking=True)
    location_note = fields.Char(string='Other location / access details')
    instructions = fields.Text()
    state = fields.Selection([('submitted', 'Submitted'), ('in_review', 'In review'), ('approved', 'Approved'),
                              ('scheduled', 'Scheduled'), ('declined', 'Declined'), ('cancelled', 'Cancelled')],
                             default='submitted', required=True, tracking=True, index=True)
    state_priority = fields.Integer(compute='_compute_state_priority', store=True)
    review_note = fields.Text(string='Response to client', tracking=True)
    reviewer_id = fields.Many2one('res.users', readonly=True, tracking=True)
    shift_ids = fields.One2many('binaryaid.work.shift', 'client_request_id', string='Shifts')
    shift_count = fields.Integer(compute='_compute_shift_count')

    @api.depends('state')
    def _compute_state_priority(self):
        order = {'submitted': 0, 'in_review': 1, 'approved': 2, 'scheduled': 3, 'declined': 4, 'cancelled': 5}
        for request in self:
            request.state_priority = order.get(request.state, 9)

    def _compute_shift_count(self):
        for request in self:
            request.shift_count = len(request.shift_ids)

    def _compute_access_url(self):
        super()._compute_access_url()
        for request in self:
            request.access_url = '/my/support-requests/%s' % request.id

    @api.constrains('preferred_date_from', 'preferred_date_to', 'preferred_start_time', 'preferred_end_time')
    def _check_preferences(self):
        for request in self:
            if request.preferred_date_to and request.preferred_date_to < request.preferred_date_from:
                raise ValidationError(_('The last preferred date cannot be before the first.'))
            for value in (request.preferred_start_time, request.preferred_end_time):
                if value < 0 or value >= 24:
                    raise ValidationError(_('Preferred times must be between 00:00 and 23:59.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('binaryaid.care.client.request') or _('New')
        requests = super().create(vals_list)
        for request in requests:
            request.message_post(body=_('Request submitted.'))
        return requests

    def _check_admin(self):
        if not self.env.user.has_group('binaryaid_work_management.group_work_admin'):
            raise AccessError(_('Only roster administrators can review client requests.'))

    def _set_state(self, state, allowed):
        self._check_admin()
        for request in self:
            if request.state not in allowed:
                raise UserError(_('%(ref)s cannot move from %(state)s.', ref=request.name,
                                  state=dict(self._fields['state'].selection)[request.state]))
        self.write({'state': state, 'reviewer_id': self.env.uid})
        self._notify_requester()
        return True

    def _notify_requester(self):
        for request in self:
            partner = request.requested_by_id.partner_id
            if partner and request.requested_by_id.share:
                # Status only: the message never includes worker names or HR information.
                request.message_notify(partner_ids=partner.ids, subject=_('Support request %s', request.name),
                                       body=_('Your support request %(ref)s is now: %(state)s.', ref=request.name,
                                              state=dict(self._fields['state'].selection)[request.state]))

    def action_start_review(self):
        return self._set_state('in_review', ['submitted'])

    def action_approve(self):
        return self._set_state('approved', ['submitted', 'in_review'])

    def action_decline(self):
        if any(not (request.review_note or '').strip() for request in self):
            raise UserError(_('Add a response to the client explaining why the request is declined.'))
        return self._set_state('declined', ['submitted', 'in_review', 'approved'])

    def action_mark_scheduled(self):
        return self._set_state('scheduled', ['approved'])

    def action_cancel(self):
        for request in self:
            if request.requested_by_id != self.env.user:
                self._check_admin()
            if request.state not in ('submitted', 'in_review'):
                raise UserError(_('Only requests that are not yet approved can be cancelled.'))
        self.sudo().write({'state': 'cancelled'})
        return True

    def _suggested_window(self):
        self.ensure_one()
        tz = pytz.timezone(self.location_id.timezone or self.env.user.tz or 'Australia/Sydney')
        start_t = float_to_time(self.preferred_start_time or 9.0)
        end_t = float_to_time(self.preferred_end_time or (self.preferred_start_time or 9.0) + 4)
        start = tz.localize(datetime.combine(self.preferred_date_from, start_t))
        end = tz.localize(datetime.combine(self.preferred_date_from, end_t))
        if end <= start:
            end += timedelta(days=1)  # overnight preference
        return (start.astimezone(pytz.UTC).replace(tzinfo=None), end.astimezone(pytz.UTC).replace(tzinfo=None), tz.zone)

    def action_create_shift(self):
        """Admin creates a draft shift from an approved request; publishing stays a separate step."""
        self.ensure_one()
        self._check_admin()
        if self.state not in ('approved', 'scheduled'):
            raise UserError(_('Approve the request before creating a shift.'))
        start, end, tz = self._suggested_window()
        context = {
            'default_client_id': self.client_id.id, 'default_client_request_id': self.id,
            'default_service_location_id': self.location_id.id, 'default_timezone': tz,
            'default_name': (self.support_needs or '').splitlines()[0][:80] if self.support_needs else self.client_id.name,
            'default_start': fields.Datetime.to_string(start), 'default_end': fields.Datetime.to_string(end),
            'default_instructions': self.instructions,
        }
        return {'type': 'ir.actions.act_window', 'name': _('New shift for %s', self.client_id.name),
                'res_model': 'binaryaid.work.shift', 'view_mode': 'form', 'target': 'new',
                'views': [(self.env.ref('binaryaid_care.view_shift_quick_form').id, 'form')], 'context': context}

    def action_open_shifts(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Shifts'), 'res_model': 'binaryaid.work.shift',
                'view_mode': 'list,form', 'domain': [('client_request_id', '=', self.id)]}
