from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import format_datetime

from odoo.addons.binaryaid_hrms_dashboard.models.dashboard import ATTENTION_LIMIT

from odoo.addons.binaryaid_care.models.tools import get_param

from .attendance import EXCEPTION_KINDS


class HrmsDashboard(models.AbstractModel):
    _inherit = 'binaryaid.hrms.dashboard'

    def _specifications(self):
        specs = super()._specifications()
        company = self.env.company.id
        if self._is_shift_admin():
            specs['exceptions'] = ('binaryaid.care.attendance.exception', _('Clock exceptions'), [
                ('company_id', '=', company), ('state', '=', 'submitted')], 'fa-map-marker', 'red', _('Awaiting review'))
            specs['missing_notes'] = ('binaryaid.work.shift', _('Missing notes'), [
                ('company_id', '=', company), ('state', '=', 'published'), ('end', '<=', fields.Datetime.now()),
                ('end', '>=', fields.Datetime.now() - timedelta(days=14)), ('care_note_status', '!=', 'submitted')],
                'fa-sticky-note-o', 'amber', _('Ended shifts, last 14 days'))
        if self.env.user.has_group('binaryaid_care.group_care_reviewer'):
            specs['incidents'] = ('binaryaid.care.incident', _('Open incidents'), [
                ('company_id', '=', company), ('state', '!=', 'closed')], 'fa-exclamation-triangle', 'red', _('Restricted review'))
        return specs

    def _card_keys(self, admin):
        if admin:
            # Operational figures only; drafts, notes, documents and incidents are in Action items.
            return ['shifts_today', 'attendance', 'unfilled', 'client_requests', 'missing_signout',
                    'exceptions', 'leave', 'timesheets', 'recruitment']
        return super()._card_keys(admin)

    def _exception_tab(self, domain):
        records = self.env['binaryaid.care.attendance.exception'].search(domain, limit=ATTENTION_LIMIT)
        tz = self._viewer_tz()
        kinds = dict(EXCEPTION_KINDS)
        items = [{
            'source': 'clock_exception', 'id': r.id, 'title': r.employee_id.name,
            'subtitle': '%s · %s' % (kinds[r.kind], _('sign in') if r.clock_type == 'in' else _('sign out')),
            'meta': '%s%s' % (format_datetime(self.env, r.requested_time, tz=tz, dt_format='EEE d MMM, HH:mm'),
                              ' · %d m away' % r.distance_m if r.distance_m else ''),
            'tone': 'red', 'warning': '',
            'actions': [{'name': 'approve', 'label': _('Approve'), 'style': 'success'},
                        {'name': 'open', 'label': _('Review'), 'style': 'link'}],
        } for r in records]
        return {'key': 'exceptions', 'label': _('Clock'), 'icon': 'fa-map-marker',
                'count': self.env['binaryaid.care.attendance.exception'].search_count(domain), 'items': items,
                'empty': _('No clock exceptions are waiting.')}

    def _missing_notes_tab(self, domain):
        shifts = self.env['binaryaid.work.shift'].search(domain, order='end desc', limit=ATTENTION_LIMIT)
        tz = self._viewer_tz()
        items = [{
            'source': 'shift', 'id': s.id, 'title': s.employee_name, 'subtitle': s.client_id.name or s.name,
            'meta': '%s · %s' % (format_datetime(self.env, s.start, tz=tz, dt_format='EEE d MMM'), self._time_label(s)),
            'tone': 'amber', 'warning': '', 'actions': [{'name': 'open', 'label': _('Shift'), 'style': 'link'}],
        } for s in shifts]
        return {'key': 'missing_notes', 'label': _('Notes'), 'icon': 'fa-sticky-note-o',
                'count': self.env['binaryaid.work.shift'].search_count(domain), 'items': items,
                'empty': _('Every recent shift has a submitted note.')}

    def _incident_tab(self, domain):
        incidents = self.env['binaryaid.care.incident'].search(domain, order='occurred_at desc', limit=ATTENTION_LIMIT)
        tz = self._viewer_tz()
        states = dict(self.env['binaryaid.care.incident']._fields['state'].selection)
        # Reference, category and severity only: incident details never appear on overview cards.
        items = [{
            'source': 'incident', 'id': i.id, 'title': '%s · %s' % (i.name, i.category_id.name),
            'subtitle': '%s · %s' % (dict(i._fields['severity'].selection)[i.severity], states[i.state]),
            'meta': format_datetime(self.env, i.occurred_at, tz=tz, dt_format='EEE d MMM, HH:mm'),
            'tone': 'red' if i.severity in ('high', 'critical') else 'amber', 'warning': '',
            'actions': [{'name': 'open', 'label': _('Review'), 'style': 'link'}],
        } for i in incidents]
        return {'key': 'incidents', 'label': _('Incidents'), 'icon': 'fa-exclamation-triangle',
                'count': self.env['binaryaid.care.incident'].search_count(domain), 'items': items,
                'empty': _('No open incidents.')}

    def _attention_tabs(self, specs):
        tabs = super()._attention_tabs(specs)
        if 'exceptions' in specs:
            tabs.insert(1, self._exception_tab(specs['exceptions'][2]))
        if 'missing_notes' in specs:
            tabs.append(self._missing_notes_tab(specs['missing_notes'][2]))
        if 'incidents' in specs:
            tabs.append(self._incident_tab(specs['incidents'][2]))
        return tabs

    def _quick_actions(self, admin):
        actions = super()._quick_actions(admin)
        if not admin and self.env.user.employee_id:
            actions.insert(0, {'key': 'report_incident', 'label': _('Report incident'), 'icon': 'fa-exclamation-triangle'})
        return actions

    def _clock_payload(self):
        clock = self.env['binaryaid.care.clock']
        shift, attendance = clock.current_shift()
        early = int(get_param(self.env, 'clock_in_early_minutes'))
        if not shift:
            return {'action': False, 'early': early}
        signed_in = bool(attendance and attendance.binaryaid_shift_id == shift)
        tz = self._viewer_tz()
        note = self.env['binaryaid.care.shift.note'].sudo().search([('shift_id', '=', shift.id)], limit=1)
        pending = self.env['binaryaid.care.attendance.exception'].sudo().search_count(
            [('shift_id', '=', shift.id), ('state', '=', 'submitted')])
        return {
            'action': 'out' if signed_in else ('blocked' if attendance else 'in'),
            'shift_id': shift.id, 'title': shift.client_id.name or shift.name, 'time_label': self._time_label(shift),
            'location': shift.service_location_id.name or shift.location or '',
            'address': shift.service_location_id.address_text() if shift.service_location_id else '',
            'map_url': shift.service_location_id.map_url or '', 'plan': (shift.instructions or '').strip(),
            'early': early,
            'since': format_datetime(self.env, attendance.check_in, tz=tz, dt_format='HH:mm') if signed_in else '',
            'note_draft': note.state == 'draft' if note else False, 'pending_exception': bool(pending),
            'kinds': [{'key': k, 'label': label} for k, label in EXCEPTION_KINDS],
        }

    @api.model
    @api.readonly
    def get_overview(self):
        data = super().get_overview()
        data['clock'] = self._clock_payload() if (not data['admin'] and self.env.user.employee_id) else None
        if data.get('worker_nav') is not None:
            data['worker_nav'].insert(1, {'key': 'my_incidents', 'label': _('Incident forms'),
                                          'icon': 'fa-exclamation-triangle', 'badge': 0})
        return data

    @api.model
    @api.readonly
    def open_section(self, key):
        if key == 'my_incidents':
            return self.env['ir.actions.actions']._for_xml_id('binaryaid_care_attendance.action_my_incidents')
        return super().open_section(key)

    @api.model
    def quick_action(self, key, date=None):
        if key == 'report_incident':
            self._check_user()
            return {'type': 'ir.actions.act_window', 'name': _('Report an incident'), 'res_model': 'binaryaid.care.incident',
                    'views': [(self.env.ref('binaryaid_care_attendance.view_incident_report_form').id, 'form')],
                    'target': 'new', 'context': {'default_company_id': self.env.company.id}}
        return super().quick_action(key, date)

    # Worker clock RPCs ------------------------------------------------------------
    @api.model
    def care_clock_in(self, shift_id, latitude=None, longitude=None, accuracy=0.0):
        self._check_user()
        return self.env['binaryaid.care.clock'].clock_in(shift_id, latitude, longitude, accuracy)

    @api.model
    def care_note_form(self, shift_id):
        """Open (or resume) the note for the shift being signed out; records the Clock Out tap time."""
        self._check_user()
        shift = self.env['binaryaid.care.clock']._own_shift(shift_id)
        note = self.env['binaryaid.care.shift.note']._for_shift(shift)
        if note.state == 'draft':
            note.sudo().write({'clock_out_requested_on': fields.Datetime.now()})
        return note._form_payload()

    @api.model
    def care_save_note_draft(self, shift_id, answers):
        self._check_user()
        shift = self.env['binaryaid.care.clock']._own_shift(shift_id)
        note = self.env['binaryaid.care.shift.note']._for_shift(shift)
        if note.state != 'draft':
            raise UserError(_('This note was already submitted.'))
        note._store_answers(answers)
        return True

    @api.model
    def care_clock_out(self, shift_id, answers, latitude=None, longitude=None, accuracy=0.0, token=None):
        """Save the note and complete attendance together; a repeated token returns the first result."""
        self._check_user()
        Note = self.env['binaryaid.care.shift.note'].sudo()
        if token and Note.search_count([('submission_token', '=', token), ('user_id', '=', self.env.uid)]):
            return {'status': 'already', 'message': _('Your note and sign out were already saved.')}
        shift = self.env['binaryaid.care.clock']._own_shift(shift_id)
        note = self.env['binaryaid.care.shift.note']._for_shift(shift)
        if note.state != 'draft':
            raise UserError(_('This note was already submitted.'))
        note._store_answers(answers)
        # Draft answers survive a failed sign out: only the savepoint below is rolled back,
        # and the recoverable error is returned instead of raised so the draft is committed.
        try:
            with self.env.cr.savepoint():
                self.env['binaryaid.care.clock'].clock_out(shift_id, latitude, longitude, accuracy, note._clock_out_time())
                note._submit(token)
        except (ValidationError, UserError) as error:
            return {'status': 'error', 'draft_saved': True, 'message': error.args[0]}
        return {'status': 'ok', 'message': _('Shift completed. Your note was submitted.')}

    @api.model
    def care_report_exception(self, shift_id, kind, reason, clock_type, requested_time=None,
                              latitude=None, longitude=None, accuracy=0.0, answers=None):
        """Exception route for GPS, location, connectivity or missed events. A sign out exception also submits the note."""
        self._check_user()
        clock = self.env['binaryaid.care.clock']
        shift = clock._own_shift(shift_id)
        with self.env.cr.savepoint():
            if clock_type == 'out':
                note = self.env['binaryaid.care.shift.note']._for_shift(shift)
                if note.state == 'draft':
                    note._store_answers(answers or {})
                    note._submit()
            record = clock.report_exception(shift_id, kind, reason, clock_type, requested_time, latitude, longitude, accuracy)
        return {'status': 'ok', 'message': _('Exception %s sent for review.', record.name)}

    def _attention_record(self, source, res_id):
        if source in ('clock_exception', 'incident'):
            specs = self._specifications()
            key = 'exceptions' if source == 'clock_exception' else 'incidents'
            if key not in specs:
                raise AccessError(_('This item is not available on your dashboard.'))
            model, label, domain = specs[key][:3]
            record = self.env[model].search(domain + [('id', '=', res_id)], limit=1)
            if not record:
                raise AccessError(_('This item is no longer waiting on your dashboard. Refresh to update it.'))
            return record
        return super()._attention_record(source, res_id)

    @api.model
    def item_action(self, source, res_id, name):
        if source not in ('clock_exception', 'incident'):
            return super().item_action(source, res_id, name)
        self._check_user()
        record = self._attention_record(source, res_id)
        if name == 'open':
            return self._dialog(record)
        if source == 'clock_exception' and name == 'approve':
            return record.action_approve()
        raise AccessError(_('This action is not available for this item.'))

    @api.model
    @api.readonly
    def care_is_signed_in(self):
        employee = self.env.user.employee_id
        return bool(employee and self.env['hr.attendance'].sudo().search_count(
            [('employee_id', '=', employee.id), ('check_out', '=', False)], limit=1))
