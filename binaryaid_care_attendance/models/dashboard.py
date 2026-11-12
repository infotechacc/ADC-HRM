from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import format_datetime

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
            # Operational figures only.
            return ['shifts_today', 'attendance', 'unfilled', 'missing_signout',
                    'exceptions', 'leave', 'timesheets', 'recruitment']
        return super()._card_keys(admin)

    def _quick_actions(self, admin):
        actions = super()._quick_actions(admin)
        if admin:
            actions.append({'key': 'shift_reports', 'label': _('Shift reports'), 'icon': 'fa-file-text-o'})
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
            'address': shift.service_location_id.name or '',
            'map_url': shift.service_location_id.map_url or '', 'plan': (shift.instructions or '').strip(),
            'latitude': shift.service_location_id.latitude, 'longitude': shift.service_location_id.longitude,
            'radius': shift.service_location_id.radius_m or 0,
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
        if key == 'shift_reports':
            self._check_user()
            if not self._is_admin():
                raise AccessError(_('Only administrators can view all shift reports.'))
            return 'binaryaid_care_attendance.action_shift_reports'
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

    @api.model
    @api.readonly
    def care_is_signed_in(self):
        employee = self.env.user.employee_id
        return bool(employee and self.env['hr.attendance'].sudo().search_count(
            [('employee_id', '=', employee.id), ('check_out', '=', False)], limit=1))
