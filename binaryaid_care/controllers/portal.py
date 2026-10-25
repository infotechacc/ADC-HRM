from odoo import _, fields, http
from odoo.exceptions import ValidationError
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal


class CareClientPortal(CustomerPortal):
    """Restricted client access: submit support needs and follow own request status only."""

    def _care_contacts(self):
        return request.env['binaryaid.care.client.contact'].sudo().search([
            ('user_id', '=', request.env.uid), ('is_authorised', '=', True),
            ('client_id.active', '=', True), ('client_id.status', '!=', 'inactive')])

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'care_request_count' in counters:
            values['care_request_count'] = request.env['binaryaid.care.client.request'].search_count([]) \
                if self._care_contacts() else 0
        return values

    @http.route(['/my/support-requests'], type='http', auth='user', website=True)
    def care_requests(self, **kw):
        contacts = self._care_contacts()
        requests = request.env['binaryaid.care.client.request'].search([], order='create_date desc')
        values = self._prepare_portal_layout_values()
        values.update({'page_name': 'care_requests', 'care_requests': requests, 'care_clients': contacts.client_id})
        return request.render('binaryaid_care.portal_my_care_requests', values)

    @http.route(['/my/support-requests/<int:request_id>'], type='http', auth='user', website=True)
    def care_request(self, request_id, **kw):
        record = request.env['binaryaid.care.client.request'].search([('id', '=', request_id)], limit=1)
        if not record:
            return request.redirect('/my/support-requests')
        values = self._prepare_portal_layout_values()
        values.update({'page_name': 'care_request', 'care_request': record,
                       'location_name': record.sudo().location_id.name})
        return request.render('binaryaid_care.portal_my_care_request', values)

    @http.route(['/my/support-requests/<int:request_id>/cancel'], type='http', auth='user', methods=['POST'], website=True)
    def care_request_cancel(self, request_id, **kw):
        record = request.env['binaryaid.care.client.request'].search([('id', '=', request_id)], limit=1)
        if record and record.state in ('submitted', 'in_review'):
            record.sudo().write({'state': 'cancelled'})
            record.sudo().message_post(body=_('Cancelled by %s.', request.env.user.name))
        return request.redirect('/my/support-requests/%s' % request_id if record else '/my/support-requests')

    @http.route(['/my/support-requests/new'], type='http', auth='user', website=True, methods=['GET', 'POST'])
    def care_request_new(self, **post):
        contacts = self._care_contacts()
        if not contacts:
            return request.redirect('/my')
        clients = contacts.client_id
        values = self._prepare_portal_layout_values()
        values.update({'page_name': 'care_request_new', 'care_clients': clients, 'error': '', 'post': post,
                       'locations': clients.location_ids.filtered('active')})
        if request.httprequest.method == 'POST':
            try:
                record = self._create_care_request(contacts, post)
            except (ValidationError, ValueError) as error:
                values['error'] = str(error.args[0] if error.args else error)
                return request.render('binaryaid_care.portal_care_request_new', values)
            return request.redirect('/my/support-requests/%s?created=1' % record.id)
        return request.render('binaryaid_care.portal_care_request_new', values)

    def _parse_time(self, value):
        if not value:
            return 0.0
        hours, minutes = value.split(':')[:2]
        return int(hours) + int(minutes) / 60

    def _create_care_request(self, contacts, post):
        client_id = int(post.get('client_id') or 0)
        contact = contacts.filtered(lambda c: c.client_id.id == client_id)[:1]
        if not contact:
            raise ValidationError(_('Choose the client you are requesting support for.'))
        if not (post.get('support_needs') or '').strip():
            raise ValidationError(_('Describe the support you need.'))
        date_from = fields.Date.to_date(post.get('preferred_date_from') or None)
        if not date_from:
            raise ValidationError(_('Choose a preferred date.'))
        if date_from < fields.Date.context_today(contact):
            raise ValidationError(_('The preferred date cannot be in the past.'))
        location = contact.client_id.location_ids.filtered(lambda l: l.id == int(post.get('location_id') or 0))
        # Created as the system after the ownership checks above; clients never choose workers.
        return request.env['binaryaid.care.client.request'].sudo().create({
            'client_id': contact.client_id.id, 'contact_id': contact.id, 'requested_by_id': request.env.uid,
            'support_needs': post['support_needs'].strip()[:4000],
            'preferred_date_from': date_from,
            'preferred_date_to': fields.Date.to_date(post.get('preferred_date_to') or None) or False,
            'preferred_start_time': self._parse_time(post.get('preferred_start_time')),
            'preferred_end_time': self._parse_time(post.get('preferred_end_time')),
            'location_id': location.id, 'location_note': (post.get('location_note') or '')[:255],
            'instructions': (post.get('instructions') or '')[:4000],
        })
