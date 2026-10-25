from odoo import api, fields, models, _
from odoo.exceptions import AccessError
from odoo.tools import format_date, format_datetime

from odoo.addons.binaryaid_hrms_dashboard.models.dashboard import ATTENTION_LIMIT



class HrmsDashboard(models.AbstractModel):
    _inherit = 'binaryaid.hrms.dashboard'

    def _shift_form_view(self, shift=None):
        if shift is None or shift.state == 'draft':
            return self.env.ref('binaryaid_care.view_shift_quick_form').id
        return super()._shift_form_view(shift)

    def _is_admin(self):
        # Care reviewers (e.g. clinical leads) use the administration view for incidents and notes.
        return super()._is_admin() or self.env.user.has_group('binaryaid_care.group_care_reviewer')

    def _roster_start(self):
        # Dashboards look ahead: today plus the next 13 days. The configured fortnight
        # anchor drives timesheet periods (see binaryaid_care_timesheet).
        return fields.Date.context_today(self)

    def _care_document_domain(self):
        domain = [('company_id', '=', self.env.company.id), ('expiry_state', 'in', ['expiring', 'expired'])]
        user = self.env.user
        owners = []
        if user.has_group('binaryaid_work_management.group_work_admin'):
            owners.append([('client_id', '!=', False)])
        if user.has_group('hr.group_hr_user'):
            owners.append([('employee_id', '!=', False)])
        if not owners:
            return None
        return domain + (['|'] + owners[0] + owners[1] if len(owners) == 2 else owners[0])

    def _specifications(self):
        specs = super()._specifications()
        specs.pop('documents', None)
        document_domain = self._care_document_domain()
        if document_domain is not None:
            specs['documents'] = ('binaryaid.care.document', _('Document alerts'), document_domain,
                                  'fa-id-card-o', 'red', _('Expired or expiring soon'))
        if self._is_shift_admin():
            today_start, horizon_end = self._utc_bounds(fields.Date.context_today(self), 14)
            if 'unpublished' in specs:
                model, label, domain, icon, tone, hint = specs['unpublished']
                specs['unpublished'] = (model, label, domain + [('employee_id', '!=', False)], icon, tone, hint)
            specs['unfilled'] = ('binaryaid.work.shift', _('Unfilled shifts'), [
                ('company_id', '=', self.env.company.id), ('state', '=', 'draft'), ('employee_id', '=', False),
                ('end', '>', today_start), ('start', '<', horizon_end)],
                'fa-user-times', 'red', _('Next 14 days'))
            specs['client_requests'] = ('binaryaid.care.client.request', _('Client requests'), [
                ('company_id', '=', self.env.company.id), ('state', 'in', ['submitted', 'in_review', 'approved'])],
                'fa-inbox', 'amber', _('To review or schedule'))
        if self.env.user.employee_id:
            specs['messages'] = ('binaryaid.care.announcement', _('Unread messages'), [
                ('state', '=', 'sent'), ('recipient_ids.user_id', '=', self.env.uid),
                ('recipient_ids', 'any', [('user_id', '=', self.env.uid), ('read_on', '=', False)])],
                'fa-bullhorn', 'blue', _('Team messages for you'))
        return specs

    def _card_keys(self, admin):
        keys = super()._card_keys(admin)
        if admin:
            keys.insert(1, 'unfilled')
            keys.insert(2, 'client_requests')
        else:
            keys.insert(0, 'messages')
        return keys

    def _request_tab(self, domain):
        requests = self.env['binaryaid.care.client.request'].search(domain, limit=ATTENTION_LIMIT)
        items = []
        for request in requests:
            actions = []
            if request.state in ('submitted', 'in_review'):
                actions.append({'name': 'approve', 'label': _('Approve'), 'style': 'success'})
            if request.state == 'approved':
                actions.append({'name': 'create_shift', 'label': _('Create shift'), 'style': 'success'})
            actions.append({'name': 'open', 'label': _('Review'), 'style': 'link'})
            hours = ''
            if request.preferred_start_time or request.preferred_end_time:
                hours = ' · %02d:%02d–%02d:%02d' % (int(request.preferred_start_time), round(request.preferred_start_time % 1 * 60),
                                                    int(request.preferred_end_time), round(request.preferred_end_time % 1 * 60))
            items.append({
                'source': 'request', 'id': request.id, 'title': request.client_id.name,
                'subtitle': '%s · %s' % (request.name, dict(request._fields['state'].selection)[request.state]),
                # Dates and place only: support needs stay inside the request.
                'meta': '%s%s%s' % (format_date(self.env, request.preferred_date_from, date_format='EEE d MMM'), hours,
                                    ' · %s' % request.location_id.name if request.location_id else ''),
                'tone': 'amber' if request.state != 'approved' else 'teal', 'warning': '', 'actions': actions,
            })
        return {'key': 'client_requests', 'label': _('Requests'), 'icon': 'fa-inbox',
                'count': self.env['binaryaid.care.client.request'].search_count(domain), 'items': items,
                'empty': _('No client requests are waiting.')}

    def _document_tab(self, domain):
        documents = self.env['binaryaid.care.document'].search(domain, order='expiry_date, id', limit=ATTENTION_LIMIT)
        today = fields.Date.context_today(self)
        items = [{
            'source': 'care_document', 'id': document.id,
            'title': document.client_id.name or document.employee_id.name,
            'subtitle': '%s · %s' % (document.category_id.name, _('Client') if document.client_id else _('Worker')),
            'meta': (_('Expired %s') if document.expiry_date < today else _('Expires %s')) % format_date(self.env, document.expiry_date),
            'tone': 'red' if document.expiry_date < today else 'amber', 'warning': '',
            'actions': [{'name': 'open', 'label': _('Open'), 'style': 'link'}],
        } for document in documents]
        return {'key': 'documents', 'label': _('Documents'), 'icon': 'fa-id-card-o',
                'count': self.env['binaryaid.care.document'].search_count(domain), 'items': items,
                'empty': _('No documents are expired or expiring soon.')}

    def _unfilled_tab(self, domain):
        shifts = self.env['binaryaid.work.shift'].search(domain, order='start, id', limit=ATTENTION_LIMIT)
        tz = self._viewer_tz()
        items = [{
            'source': 'shift', 'id': s.id, 'title': s.client_id.name or s.name,
            'subtitle': s.service_location_id.name or s.location or _('No location'),
            'meta': '%s · %s' % (format_datetime(self.env, s.start, tz=tz, dt_format='EEE d MMM'), self._time_label(s)),
            'tone': 'red', 'warning': '', 'actions': [{'name': 'open', 'label': _('Assign worker'), 'style': 'success'}],
        } for s in shifts]
        return {'key': 'unfilled', 'label': _('Unfilled'), 'icon': 'fa-user-times',
                'count': self.env['binaryaid.work.shift'].search_count(domain), 'items': items,
                'empty': _('Every shift in the next 14 days has a worker.')}

    def _attention_tabs(self, specs):
        tabs = super()._attention_tabs(specs)
        if 'client_requests' in specs:
            tabs.insert(0, self._request_tab(specs['client_requests'][2]))
        if 'unfilled' in specs:
            tabs.insert(0, self._unfilled_tab(specs['unfilled'][2]))
        return tabs

    def _shift_chip(self, shift):
        chip = super()._shift_chip(shift)
        chip['client'] = shift.client_id.name or ''
        return chip

    def _shift_status(self, shift, now):
        if not shift.employee_id:
            return 'unfilled', _('Unfilled'), 'red'
        return super()._shift_status(shift, now)

    def _quick_actions(self, admin):
        actions = super()._quick_actions(admin)
        if self._is_shift_admin():
            actions.insert(1, {'key': 'add_client', 'label': _('Add client'), 'icon': 'fa-address-card-o'})
            actions.append({'key': 'tab:client_requests', 'label': _('Review requests'), 'icon': 'fa-inbox'})
        return actions

    def _own_messages(self):
        recipients = self.env['binaryaid.care.announcement.recipient'].search([
            ('user_id', '=', self.env.uid), ('announcement_id.state', '=', 'sent'),
            ('company_id', '=', self.env.company.id)], order='id desc', limit=5)
        return {
            'unread': self.env['binaryaid.care.announcement.recipient'].search_count([
                ('user_id', '=', self.env.uid), ('announcement_id.state', '=', 'sent'), ('read_on', '=', False)]),
            'items': [{'id': r.announcement_id.id, 'title': r.announcement_id.title, 'read': bool(r.read_on),
                       'needs_ack': r.announcement_id.requires_ack and not r.acknowledged_on,
                       'date': format_datetime(self.env, r.announcement_id.sent_on, dt_format='d MMM, HH:mm')}
                      for r in recipients],
        }

    @api.model
    @api.readonly
    def get_overview(self):
        data = super().get_overview()
        data['messages'] = self._own_messages() if self.env.user.employee_id else None
        for row in (data.get('today') or {}).get('rows', []):
            shift = self.env['binaryaid.work.shift'].browse(row['id'])
            row['client'] = shift.client_id.name or ''
            if not shift.employee_id:
                row.update(employee=_('Unfilled'), initials='?')
        for item in (data.get('schedule') or {}).get('shifts', []):
            # The worker sees client name, times, approved location and the shift plan only.
            shift = self.env['binaryaid.work.shift'].browse(item['id'])
            location = shift.service_location_id.sudo()
            item['client'] = shift.client_id.sudo().name or ''
            item['plan'] = (shift.instructions or '').strip()
            item['address'] = location.address_text() if location else ''
            item['map_url'] = location.map_url or ''
        data['account_url'] = '/my'
        if self.env.user.employee_id and not data['admin']:
            unread = (data.get('messages') or {}).get('unread', 0)
            data['worker_nav'] = [
                {'key': 'work_schedule', 'label': _('My shifts'), 'icon': 'fa-calendar', 'badge': 0},
                {'key': 'team_messages', 'label': _('Team messages'), 'icon': 'fa-bullhorn', 'badge': unread},
                {'key': 'my_leave', 'label': _('Leave'), 'icon': 'fa-plane', 'badge': 0},
                {'key': 'profile', 'label': _('My profile'), 'icon': 'fa-user-o', 'badge': 0},
            ]
        for link in data['shortcuts']:
            if link['key'] == 'discuss':
                link['label'] = _('Chat')
        if self.env.user.employee_id:
            data['shortcuts'].insert(1, {'key': 'team_messages', 'label': _('Team messages'), 'icon': 'fa-bullhorn'})
        if self._is_shift_admin():
            data['shortcuts'].insert(1, {'key': 'clients', 'label': _('Clients'), 'icon': 'fa-address-book-o'})
        return data

    @api.model
    @api.readonly
    def open_section(self, key):
        if key == 'clients' and self._is_shift_admin():
            return self.env['ir.actions.actions']._for_xml_id('binaryaid_care.action_care_client')
        if key == 'team_messages':
            action = self.env['ir.actions.actions']._for_xml_id('binaryaid_care.action_my_announcements')
            return action
        return super().open_section(key)

    @api.model
    def quick_action(self, key, date=None):
        if key == 'add_client':
            self._check_user()
            if not self._is_shift_admin():
                raise AccessError(_('Only roster administrators can add clients.'))
            return {'type': 'ir.actions.act_window', 'name': _('New client'), 'res_model': 'binaryaid.care.client',
                    'views': [(False, 'form')], 'target': 'new', 'context': {'default_company_id': self.env.company.id}}
        return super().quick_action(key, date)

    def _attention_record(self, source, res_id):
        if source == 'care_document':
            specs = self._specifications()
            if 'documents' not in specs:
                raise AccessError(_('This item is not available on your dashboard.'))
            document = self.env['binaryaid.care.document'].search(specs['documents'][2] + [('id', '=', res_id)], limit=1)
            if not document:
                raise AccessError(_('This item is no longer waiting on your dashboard. Refresh to update it.'))
            return document
        if source == 'request':
            if not self._is_shift_admin():
                raise AccessError(_('This item is not available on your dashboard.'))
            request = self.env['binaryaid.care.client.request'].search([
                ('id', '=', res_id), ('company_id', '=', self.env.company.id)], limit=1)
            if not request:
                raise AccessError(_('This request is not available on your dashboard.'))
            return request
        if source == 'message':
            message = self.env['binaryaid.care.announcement'].search([
                ('id', '=', res_id), ('state', '=', 'sent'), ('recipient_ids.user_id', '=', self.env.uid)], limit=1)
            if not message:
                raise AccessError(_('This message is not available to you.'))
            return message
        return super()._attention_record(source, res_id)

    @api.model
    def item_action(self, source, res_id, name):
        if source not in ('care_document', 'request', 'message'):
            return super().item_action(source, res_id, name)
        self._check_user()
        record = self._attention_record(source, res_id)
        if source == 'message':
            record.action_mark_read()
            if name == 'ack':
                return record.action_acknowledge()
            return self._dialog(record, view=self.env.ref('binaryaid_care.view_announcement_read_form').id)
        if name == 'open':
            return self._dialog(record)
        if source == 'request' and name == 'approve':
            return record.action_approve()
        if source == 'request' and name == 'create_shift':
            return record.action_create_shift()
        raise AccessError(_('This action is not available for this item.'))
