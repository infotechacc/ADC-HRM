from odoo import api, fields, models, _
from odoo.exceptions import AccessError
from odoo.tools import format_datetime


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

    def _specifications(self):
        specs = super()._specifications()
        if self._is_shift_admin():
            today_start, horizon_end = self._utc_bounds(fields.Date.context_today(self), 14)
            if 'unpublished' in specs:
                model, label, domain, icon, tone, hint = specs['unpublished']
                specs['unpublished'] = (model, label, domain + [('employee_id', '!=', False)], icon, tone, hint)
            specs['unfilled'] = ('binaryaid.work.shift', _('Unfilled shifts'), [
                ('company_id', '=', self.env.company.id), ('state', '=', 'draft'), ('employee_id', '=', False),
                ('end', '>', today_start), ('start', '<', horizon_end)],
                'fa-user-times', 'red', _('Next 14 days'))
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
        else:
            keys.insert(0, 'messages')
        return keys

    def _enrich_day_rows(self, rows, shifts):
        super()._enrich_day_rows(rows, shifts)
        for row, shift in zip(rows, shifts):
            row['client'] = shift.client_id.name or ''
            if not shift.employee_id:
                row.update(employee=_('Unfilled'), initials='?', unfilled=True)

    def _shift_status(self, shift, now):
        if not shift.employee_id:
            return 'unfilled', _('Unfilled'), 'red'
        return super()._shift_status(shift, now)

    def _quick_actions(self, admin):
        actions = super()._quick_actions(admin)
        if self._is_shift_admin():
            actions.insert(1, {'key': 'add_client', 'label': _('Add client'), 'icon': 'fa-address-card-o'})
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
        for item in (data.get('schedule') or {}).get('shifts', []):
            # The worker sees client name, times, approved location and the shift plan only.
            shift = self.env['binaryaid.work.shift'].browse(item['id'])
            location = shift.service_location_id.sudo()
            item['client'] = shift.client_id.sudo().name or ''
            item['plan'] = (shift.instructions or '').strip()
            item['address'] = location.name or ''
            item['map_url'] = location.map_url or ''
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
        return data

    @api.model
    @api.readonly
    def open_section(self, key):
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
        if source == 'message':
            message = self.env['binaryaid.care.announcement'].search([
                ('id', '=', res_id), ('state', '=', 'sent'), ('recipient_ids.user_id', '=', self.env.uid)], limit=1)
            if not message:
                raise AccessError(_('This message is not available to you.'))
            return message
        return super()._attention_record(source, res_id)

    @api.model
    def item_action(self, source, res_id, name):
        if source != 'message':
            return super().item_action(source, res_id, name)
        self._check_user()
        message = self._attention_record(source, res_id)
        message.action_mark_read()
        if name == 'ack':
            return message.action_acknowledge()
        return self._dialog(message, view=self.env.ref('binaryaid_care.view_announcement_read_form').id)
