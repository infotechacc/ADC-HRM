from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from odoo.addons.binaryaid_care.models.tools import distance_m, get_param

EXCEPTION_KINDS = [
    ('gps_failure', 'GPS unavailable'),
    ('wrong_location', 'Not at the stored location'),
    ('connectivity', 'No connection at the time'),
    ('missed_clock_in', 'Missed sign in'),
    ('missed_clock_out', 'Missed sign out'),
]


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    in_mode = fields.Selection(selection_add=[('binaryaid_gps', 'GPS verified'), ('binaryaid_exception', 'Approved exception')],
                               ondelete={'binaryaid_gps': 'set default', 'binaryaid_exception': 'set default'})
    out_mode = fields.Selection(selection_add=[('binaryaid_gps', 'GPS verified'), ('binaryaid_exception', 'Approved exception')],
                                ondelete={'binaryaid_gps': 'set default', 'binaryaid_exception': 'set default'})
    binaryaid_shift_id = fields.Many2one('binaryaid.work.shift', string='Shift', index=True, readonly=True)
    binaryaid_client_id = fields.Many2one(related='binaryaid_shift_id.client_id', string='Client')
    binaryaid_in_distance_m = fields.Float(string='Sign in distance (m)', readonly=True, digits=(10, 1))
    binaryaid_out_distance_m = fields.Float(string='Sign out distance (m)', readonly=True, digits=(10, 1))
    binaryaid_in_accuracy_m = fields.Float(string='Sign in GPS accuracy (m)', readonly=True, digits=(10, 1))
    binaryaid_out_accuracy_m = fields.Float(string='Sign out GPS accuracy (m)', readonly=True, digits=(10, 1))
    binaryaid_exception_ids = fields.One2many('binaryaid.care.attendance.exception', 'attendance_id', string='Exceptions')


class AttendanceException(models.Model):
    _name = 'binaryaid.care.attendance.exception'
    _description = 'Attendance Exception'
    _inherit = ['mail.thread']
    _order = 'state_priority, create_date desc, id desc'

    name = fields.Char(readonly=True, copy=False, default=lambda self: _('New'))
    employee_id = fields.Many2one('hr.employee', required=True, readonly=True, index=True)
    user_id = fields.Many2one(related='employee_id.user_id', store=True, index=True)
    company_id = fields.Many2one(related='shift_id.company_id', store=True)
    shift_id = fields.Many2one('binaryaid.work.shift', required=True, readonly=True, ondelete='restrict', index=True)
    client_id = fields.Many2one(related='shift_id.client_id')
    kind = fields.Selection(EXCEPTION_KINDS, required=True, readonly=True)
    clock_type = fields.Selection([('in', 'Sign in'), ('out', 'Sign out')], required=True, readonly=True)
    requested_time = fields.Datetime(required=True, readonly=True, help='Time the worker says they signed in or out.')
    reason = fields.Text(required=True, readonly=True)
    latitude = fields.Float(digits=(10, 7), readonly=True)
    longitude = fields.Float(digits=(10, 7), readonly=True)
    accuracy_m = fields.Float(readonly=True, string='GPS accuracy (m)')
    distance_m = fields.Float(readonly=True, string='Distance from location (m)', digits=(10, 1))
    state = fields.Selection([('submitted', 'To review'), ('approved', 'Approved'), ('rejected', 'Rejected')],
                             default='submitted', required=True, readonly=True, tracking=True)
    state_priority = fields.Integer(compute='_compute_state_priority', store=True)
    approved_time = fields.Datetime(tracking=True, help='Time recorded on approval; defaults to the requested time.')
    review_note = fields.Text(tracking=True)
    reviewer_id = fields.Many2one('res.users', readonly=True, tracking=True)
    attendance_id = fields.Many2one('hr.attendance', readonly=True, ondelete='set null')

    @api.depends('state')
    def _compute_state_priority(self):
        for record in self:
            record.state_priority = 0 if record.state == 'submitted' else 1

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise AccessError(_('Report exceptions from the dashboard clock.'))
        for vals in vals_list:
            vals['name'] = self.env['ir.sequence'].next_by_code('binaryaid.care.attendance.exception') or _('New')
        return super().create(vals_list)

    def _check_reviewer(self):
        if not self.env.user.has_group('binaryaid_work_management.group_work_admin'):
            raise AccessError(_('Only roster administrators review attendance exceptions.'))

    def write(self, vals):
        if not self.env.su:
            self._check_reviewer()
            if set(vals) - {'approved_time', 'review_note'} or self.filtered(lambda e: e.state != 'submitted'):
                raise AccessError(_('Reviewed exceptions are kept unchanged.'))
        return super().write(vals)

    def action_approve(self):
        self._check_reviewer()
        for record in self:
            if record.state != 'submitted':
                raise UserError(_('%s was already reviewed.', record.name))
            when = record.approved_time or record.requested_time
            shift = record.shift_id
            late = timedelta(minutes=int(get_param(self.env, 'clock_out_late_minutes')))
            early = timedelta(minutes=int(get_param(self.env, 'clock_in_early_minutes')))
            if not (shift.start - early <= when <= shift.end + late):
                raise ValidationError(_('The approved time must be within the shift clock window.'))
            Attendance = self.env['hr.attendance'].sudo()
            record.employee_id.sudo().lock_for_update()
            if record.clock_type == 'in':
                attendance = Attendance.create({
                    'employee_id': record.employee_id.id, 'check_in': when, 'binaryaid_shift_id': shift.id,
                    'in_mode': 'binaryaid_exception', 'in_location': _('Approved exception %s', record.name)})
            else:
                attendance = Attendance.search([('employee_id', '=', record.employee_id.id), ('check_out', '=', False),
                                                ('binaryaid_shift_id', '=', shift.id)], limit=1)
                if not attendance:
                    raise ValidationError(_('There is no open sign in for this shift. Approve a missed sign in first.'))
                if when <= attendance.check_in:
                    raise ValidationError(_('Sign out must be after sign in.'))
                attendance.write({'check_out': when, 'out_mode': 'binaryaid_exception',
                                  'out_location': _('Approved exception %s', record.name)})
            record.sudo().write({'state': 'approved', 'reviewer_id': self.env.uid, 'approved_time': when,
                                 'attendance_id': attendance.id})
            record.sudo().message_post(body=_('Approved by %s.', self.env.user.name))
        return True

    def action_reject(self):
        self._check_reviewer()
        for record in self:
            if record.state != 'submitted':
                raise UserError(_('%s was already reviewed.', record.name))
            if not (record.review_note or '').strip():
                raise UserError(_('Add a review note explaining the rejection.'))
            record.sudo().write({'state': 'rejected', 'reviewer_id': self.env.uid})
            if record.user_id:
                record.sudo().message_notify(partner_ids=record.user_id.partner_id.ids, subject=_('Attendance exception'),
                                             body=_('Your attendance exception %s was not approved.', record.name))
        return True


class CareClock(models.AbstractModel):
    """Server-side clock rules. Workers never write attendance directly."""
    _name = 'binaryaid.care.clock'
    _description = 'Care Clock Service'

    def _employee(self):
        employee = self.env.user.employee_id
        if not employee:
            raise AccessError(_('Your login is not linked to an employee.'))
        return employee

    def _own_shift(self, shift_id):
        shift = self.env['binaryaid.work.shift'].sudo().search([
            ('id', '=', shift_id), ('user_id', '=', self.env.uid), ('state', '=', 'published'),
            ('company_id', 'in', self.env.companies.ids)], limit=1)
        if not shift:
            raise AccessError(_('This shift is not assigned to you or is not published.'))
        return shift

    def _window(self):
        return (timedelta(minutes=int(get_param(self.env, 'clock_in_early_minutes'))),
                timedelta(minutes=int(get_param(self.env, 'clock_out_late_minutes'))))

    def _open_attendance(self, employee):
        return self.env['hr.attendance'].sudo().search([('employee_id', '=', employee.id), ('check_out', '=', False)], limit=1)

    def current_shift(self):
        """Shift the worker can act on now: an open GPS sign in, else the next shift inside its window."""
        employee = self.env.user.employee_id
        if not employee:
            return None, None
        open_attendance = self._open_attendance(employee)
        if open_attendance.binaryaid_shift_id:
            return open_attendance.binaryaid_shift_id, open_attendance
        now = fields.Datetime.now()
        early, late = self._window()
        shift = self.env['binaryaid.work.shift'].sudo().search([
            ('user_id', '=', self.env.uid), ('state', '=', 'published'), ('company_id', '=', self.env.company.id),
            ('start', '<=', now + early), ('end', '>', now)], order='start', limit=1)
        return shift, open_attendance

    def _verify_position(self, shift, latitude, longitude, accuracy):
        location = shift.service_location_id
        if not location or not location.has_coordinates():
            raise ValidationError(_('This shift has no verified location coordinates. Report an exception instead.'))
        if latitude is None or longitude is None:
            raise ValidationError(_('Your location could not be read. Try again outside, or report an exception.'))
        max_accuracy = int(get_param(self.env, 'gps_max_accuracy_m'))
        if accuracy and accuracy > max_accuracy:
            raise ValidationError(_('Your GPS reading is not precise enough (±%(acc)d m). Wait a moment and try again, '
                                    'or report an exception.', acc=accuracy))
        distance = distance_m(latitude, longitude, location.latitude, location.longitude)
        radius = location.radius_m or 50
        if distance > radius:
            raise ValidationError(_('You are about %(dist)d m from %(place)s. Sign in and out are accepted within '
                                    '%(radius)d m. Move closer or report an exception.',
                                    dist=distance, place=location.name, radius=radius))
        return distance

    def clock_in(self, shift_id, latitude, longitude, accuracy=0.0):
        employee = self._employee()
        shift = self._own_shift(shift_id)
        employee.sudo().lock_for_update()  # serialises duplicate taps for this employee
        open_attendance = self._open_attendance(employee)
        if open_attendance:
            if open_attendance.binaryaid_shift_id == shift:
                return {'status': 'already', 'message': _('You are already signed in for this shift.')}
            raise ValidationError(_('You are already signed in. Sign out of your active attendance first.'))
        now = fields.Datetime.now()
        early, late = self._window()
        if not (shift.start - early <= now < shift.end):
            raise ValidationError(_('Sign in opens %(minutes)d minutes before the shift starts and closes at its end.',
                                    minutes=early.total_seconds() // 60))
        if self.env['hr.attendance'].sudo().search_count([('binaryaid_shift_id', '=', shift.id)]):
            raise ValidationError(_('This shift already has a sign in. Report an exception if this is a mistake.'))
        distance = self._verify_position(shift, latitude, longitude, accuracy)
        self.env['hr.attendance'].sudo().create({
            'employee_id': employee.id, 'check_in': now, 'binaryaid_shift_id': shift.id, 'in_mode': 'binaryaid_gps',
            'in_latitude': latitude, 'in_longitude': longitude, 'binaryaid_in_distance_m': distance,
            'binaryaid_in_accuracy_m': accuracy or 0.0,
            'in_location': _('%(dist)d m from %(place)s', dist=distance, place=shift.service_location_id.name)})
        return {'status': 'ok', 'message': _('Signed in to %s.', shift.client_id.name or shift.name)}

    def clock_out(self, shift_id, latitude, longitude, accuracy, check_out_time):
        """Called inside the note submission transaction."""
        employee = self._employee()
        shift = self._own_shift(shift_id)
        employee.sudo().lock_for_update()
        attendance = self.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee.id), ('check_out', '=', False), ('binaryaid_shift_id', '=', shift.id)], limit=1)
        if not attendance:
            raise ValidationError(_('You are not signed in to this shift.'))
        early, late = self._window()
        now = fields.Datetime.now()
        if now > shift.end + late:
            raise ValidationError(_('Sign out closed %d minutes after the shift end. Report a missed sign out.',
                                    late.total_seconds() // 60))
        distance = self._verify_position(shift, latitude, longitude, accuracy)
        attendance.write({
            'check_out': max(check_out_time, attendance.check_in + timedelta(seconds=1)), 'out_mode': 'binaryaid_gps',
            'out_latitude': latitude, 'out_longitude': longitude, 'binaryaid_out_distance_m': distance,
            'binaryaid_out_accuracy_m': accuracy or 0.0,
            'out_location': _('%(dist)d m from %(place)s', dist=distance, place=shift.service_location_id.name)})
        return attendance

    def report_exception(self, shift_id, kind, reason, clock_type, requested_time=None,
                         latitude=None, longitude=None, accuracy=0.0):
        employee = self._employee()
        shift = self._own_shift(shift_id)
        if kind not in dict(EXCEPTION_KINDS):
            raise ValidationError(_('Choose what went wrong.'))
        if not (reason or '').strip():
            raise ValidationError(_('Explain what happened so the reviewer can approve it.'))
        Exception_ = self.env['binaryaid.care.attendance.exception'].sudo()
        if Exception_.search_count([('shift_id', '=', shift.id), ('clock_type', '=', clock_type), ('state', '=', 'submitted')]):
            raise ValidationError(_('An exception for this shift is already waiting for review.'))
        when = fields.Datetime.to_datetime(requested_time) if requested_time else fields.Datetime.now()
        distance = 0.0
        location = shift.service_location_id
        if latitude is not None and longitude is not None and location and location.has_coordinates():
            distance = distance_m(latitude, longitude, location.latitude, location.longitude)
        record = Exception_.create({
            'employee_id': employee.id, 'shift_id': shift.id, 'kind': kind, 'clock_type': clock_type,
            'requested_time': when, 'reason': reason.strip()[:2000], 'latitude': latitude or 0.0,
            'longitude': longitude or 0.0, 'accuracy_m': accuracy or 0.0, 'distance_m': distance})
        return record
