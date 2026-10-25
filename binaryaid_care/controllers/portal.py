from datetime import datetime

import pytz

from odoo import _, fields, http
from odoo.exceptions import ValidationError
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal

OPEN_STATES = ('submitted', 'in_review', 'approved')
STATE_TONES = {'submitted': 'blue', 'in_review': 'amber', 'approved': 'teal', 'scheduled': 'green',
               'declined': 'red', 'cancelled': 'muted'}
TIMELINE = [('submitted', 'Submitted'), ('in_review', 'In review'), ('approved', 'Approved'), ('scheduled', 'Scheduled')]


class CareClientPortal(CustomerPortal):
    """ADC client portal: a branded space for participants and authorised representatives."""

    # ------------------------------------------------------------------ helpers
    def _care_contacts(self):
        return request.env['binaryaid.care.client.contact'].sudo().search([
            ('user_id', '=', request.env.uid), ('is_authorised', '=', True),
            ('client_id.active', '=', True), ('client_id.status', '!=', 'inactive')])

    def _prepare_portal_layout_values(self):
        values = super()._prepare_portal_layout_values()
        values['care_is_contact'] = bool(self._care_contacts())
        return values

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'care_request_count' in counters:
            values['care_request_count'] = request.env['binaryaid.care.client.request'].search_count([]) \
                if self._care_contacts() else 0
        return values

    def _care_values(self, page, **extra):
        user = request.env.user
        values = {
            'page': page, 'user': user, 'company': request.env.company,
            'first_name': (user.name or '').replace('[DEMO]', '').split()[0] if user.name else '',
            'care_clients': self._care_contacts().client_id, 'tones': STATE_TONES, 'timeline': TIMELINE,
            'state_labels': dict(request.env['binaryaid.care.client.request']._fields['state']._description_selection(request.env)),
            'no_header': True, 'no_footer': True,
        }
        values.update(extra)
        return values

    def _visits(self, clients, limit=6, request_record=None):
        """Upcoming published visits for the clients: date, time and place only (no worker details)."""
        domain = [('state', '=', 'published'), ('end', '>=', fields.Datetime.now())]
        domain.append(('client_request_id', '=', request_record.id) if request_record else ('client_id', 'in', clients.ids))
        visits = []
        for shift in request.env['binaryaid.work.shift'].sudo().search(domain, order='start', limit=limit):
            tz = pytz.timezone(shift.service_location_id.timezone or shift.timezone or 'Australia/Sydney')
            start = pytz.UTC.localize(shift.start).astimezone(tz)
            end = pytz.UTC.localize(shift.end).astimezone(tz)
            visits.append({'client': shift.client_id.name, 'weekday': start.strftime('%a'), 'day': start.day,
                           'month': start.strftime('%b'), 'date': start.strftime('%A %d %B'),
                           'time': '%s – %s' % (start.strftime('%H:%M'), end.strftime('%H:%M')),
                           'place': shift.service_location_id.name or shift.location or '', 'title': shift.name})
        return visits

    # ------------------------------------------------------------------ pages
    @http.route()
    def home(self, **kw):
        if self._care_contacts():
            return request.redirect('/my/care')
        return super().home(**kw)

    @http.route(['/my/care'], type='http', auth='user', website=True)
    def care_home(self, **kw):
        contacts = self._care_contacts()
        if not contacts:
            return request.redirect('/my/care/account')
        clients = contacts.client_id
        Request = request.env['binaryaid.care.client.request']
        requests_ = Request.search([], order='create_date desc', limit=5)
        visits = self._visits(clients)
        stats = {'open': Request.search_count([('state', 'in', list(OPEN_STATES))]),
                 'scheduled': Request.search_count([('state', '=', 'scheduled')]),
                 'visits': len(self._visits(clients, limit=100))}
        people = []
        for client in clients:
            location = client.sudo().location_ids.filtered('active')[:1]
            nxt = self._visits(client, limit=1)
            people.append({'name': client.name, 'address': location.address_text() if location else '',
                           'next': nxt[0] if nxt else None})
        return request.render('binaryaid_care.client_home', self._care_values(
            'home', care_requests=requests_, visits=visits, stats=stats, people=people))

    @http.route(['/my/support-requests'], type='http', auth='user', website=True)
    def care_requests(self, status='all', **kw):
        domain = {'open': [('state', 'in', list(OPEN_STATES))], 'scheduled': [('state', '=', 'scheduled')],
                  'closed': [('state', 'in', ['declined', 'cancelled'])]}.get(status, [])
        records = request.env['binaryaid.care.client.request'].search(domain, order='create_date desc')
        filters = [('all', _('All')), ('open', _('Open')), ('scheduled', _('Scheduled')), ('closed', _('Closed'))]
        return request.render('binaryaid_care.client_requests', self._care_values(
            'requests', care_requests=records, status=status, filters=filters))

    @http.route(['/my/support-requests/<int:request_id>'], type='http', auth='user', website=True)
    def care_request(self, request_id, **kw):
        record = request.env['binaryaid.care.client.request'].search([('id', '=', request_id)], limit=1)
        if not record:
            return request.redirect('/my/support-requests')
        order = [key for key, _label in TIMELINE]
        reached = order.index(record.state) if record.state in order else -1
        return request.render('binaryaid_care.client_request', self._care_values(
            'requests', care_request=record, reached=reached, client_name=record.sudo().client_id.name,
            location_name=record.sudo().location_id.name, visits=self._visits(None, 10, record.sudo()),
            created=kw.get('created')))

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
            return request.redirect('/my/care/account')
        clients = contacts.client_id
        values = self._care_values('new', error='', post=post, locations=clients.sudo().location_ids.filtered('active'),
                                   today=fields.Date.to_string(fields.Date.context_today(contacts[:1])))
        if request.httprequest.method == 'POST':
            try:
                record = self._create_care_request(contacts, post)
            except (ValidationError, ValueError) as error:
                values['error'] = str(error.args[0] if error.args else error)
                return request.render('binaryaid_care.client_request_new', values)
            return request.redirect('/my/support-requests/%s?created=1' % record.id)
        return request.render('binaryaid_care.client_request_new', values)

    @http.route(['/my/care/account'], type='http', auth='user', website=True, methods=['GET', 'POST'])
    def care_account(self, **post):
        """Branded account page: details, phone and password."""
        values = self._care_values('account', errors='', success='', post=post)
        partner = request.env.user.partner_id
        if request.httprequest.method == 'POST':
            if post.get('form') == 'details':
                partner.sudo().write({'phone': (post.get('phone') or '').strip()[:32]})
                values['success'] = _('Your phone number was saved.')
            elif post.get('form') == 'password':
                result = self._update_password(post.get('old', '').strip(), post.get('new1', '').strip(), post.get('new2', '').strip())
                if result.get('errors'):
                    error = result['errors'].get('password')
                    values['errors'] = ' '.join(error.values()) if isinstance(error, dict) else str(error)
                else:
                    values['success'] = _('Your password was changed.')
        values['partner'] = partner
        return request.render('binaryaid_care.client_account', values)

    # ------------------------------------------------------------------ actions
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
