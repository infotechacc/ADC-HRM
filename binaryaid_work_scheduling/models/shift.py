from datetime import timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class WorkShift(models.Model):
    _name = 'binaryaid.work.shift'
    _description = 'Employee Work Shift'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start, id'
    _check_company_auto = True

    name = fields.Char(required=True, tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    employee_id = fields.Many2one('hr.employee', required=True, check_company=True, ondelete='restrict', tracking=True)
    employee_name = fields.Char(related='employee_id.name', store=True)
    user_id = fields.Many2one(related='employee_id.user_id', store=True, index=True)
    start = fields.Datetime(required=True, index=True, tracking=True)
    end = fields.Datetime(required=True, tracking=True)
    timezone = fields.Selection([(tz, tz) for tz in pytz.all_timezones], required=True,
                                default='Australia/Sydney', tracking=True)
    unpaid_break_minutes = fields.Integer(default=0, tracking=True)
    break_instructions = fields.Text(help='Specify timing and duration of paid and unpaid breaks.', tracking=True)
    planned_hours = fields.Float(compute='_compute_hours', store=True, string='Planned Paid Hours')
    location = fields.Char(tracking=True)
    instructions = fields.Text(tracking=True)
    task_ids = fields.Many2many('project.task', string='Shift Tasks', check_company=True, tracking=True,
                               domain="[('binaryaid_employee_id', '=', employee_id), ('company_id', '=', company_id)]")
    state = fields.Selection([('draft', 'Draft'), ('published', 'Published'), ('cancelled', 'Cancelled')],
                             required=True, default='draft', tracking=True, copy=False, index=True)
    published_at = fields.Datetime(readonly=True, copy=False)
    change_reason = fields.Text(string='Change / Cancellation Reason', tracking=True, copy=False)
    award_reference = fields.Char(string='Award / Agreement Reference', tracking=True)
    notice_hours = fields.Float(string='Notice Review Threshold (hours)', default=0, tracking=True)
    min_rest_hours = fields.Float(string='Rest Review Threshold (hours)', default=0, tracking=True)
    weekly_hours_limit = fields.Float(string='Weekly Hours Review Threshold', default=38, tracking=True)
    review_note = fields.Text(string='Manager Review / Consultation', tracking=True)

    @api.depends('start', 'end', 'unpaid_break_minutes')
    def _compute_hours(self):
        for shift in self:
            shift.planned_hours = ((shift.end - shift.start).total_seconds() / 3600
                                   - shift.unpaid_break_minutes / 60) if shift.start and shift.end else 0

    def _check_manager(self):
        if not self.env.su and not self.env.user.has_group('binaryaid_work_management.group_work_admin'):
            raise AccessError(_('Only Work Management administrators can manage shifts.'))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_manager()
        for vals in vals_list:
            if vals.get('state', 'draft') != 'draft' or vals.get('published_at'):
                raise ValidationError(_('Create shifts as drafts, then publish them.'))
        shifts = super().create(vals_list)
        if any(s.state != 'draft' or s.published_at for s in shifts):
            raise ValidationError(_('Create shifts as drafts, then publish them.'))
        return shifts

    def write(self, vals):
        self._check_manager()
        self.check_access('write')
        self.lock_for_update()
        self.invalidate_recordset(['state'])
        if set(vals) & {'state', 'published_at'}:
            raise AccessError(_('Use the publish, revise or cancel actions to change shift status.'))
        if self.filtered(lambda s: s.state != 'draft') and set(vals) - {'change_reason'}:
            raise ValidationError(_('Revise a published shift before changing its details.'))
        return super().write(vals)

    def unlink(self):
        self._check_manager()
        if any(s.state != 'draft' or s.published_at for s in self):
            raise ValidationError(_('Keep previously published shifts for history; cancel them instead.'))
        return super().unlink()

    @api.constrains('start', 'end', 'unpaid_break_minutes', 'employee_id', 'task_ids',
                    'company_id', 'notice_hours', 'min_rest_hours', 'weekly_hours_limit')
    def _check_details(self):
        for shift in self:
            if shift.end <= shift.start or shift.unpaid_break_minutes < 0 or shift.planned_hours <= 0:
                raise ValidationError(_('End must follow start and unpaid breaks must leave positive paid hours.'))
            if min(shift.notice_hours, shift.min_rest_hours, shift.weekly_hours_limit) < 0:
                raise ValidationError(_('Review thresholds cannot be negative.'))
            employee = shift.employee_id
            if (not employee.active or not employee.user_id.active or employee.user_id.share
                    or not employee.user_id.has_group('binaryaid_work_management.group_work_user')
                    or shift.company_id not in employee.user_id.company_ids):
                raise ValidationError(_('Select an active employee with an active Work Management user in this company.'))
            for task in shift.task_ids:
                task.check_access('read')
                if task.binaryaid_employee_id != employee or task.company_id != shift.company_id:
                    raise ValidationError(_('Shift tasks must belong to the same employee and company.'))

    def _review_warnings(self):
        self.ensure_one()
        warnings = []
        now = fields.Datetime.now()
        if self.notice_hours and (self.start - now).total_seconds() / 3600 < self.notice_hours:
            warnings.append(_('Publication is inside the configured notice period.'))
        # UTC storage, employee workplace timezone for the Monday-to-Sunday roster week.
        tz = pytz.timezone(self.timezone)
        local = pytz.UTC.localize(self.start).astimezone(tz)
        monday = local.date() - timedelta(days=local.weekday())
        week_start = tz.localize(fields.Datetime.to_datetime(monday)).astimezone(pytz.UTC).replace(tzinfo=None)
        week_end = tz.localize(fields.Datetime.to_datetime(monday + timedelta(days=7))).astimezone(pytz.UTC).replace(tzinfo=None)
        others = self.search([('employee_id', '=', self.employee_id.id), ('state', '=', 'published'), ('id', '!=', self.id)])
        if self.min_rest_hours:
            for other in others:
                gap = ((self.start - other.end) if other.end <= self.start else (other.start - self.end)).total_seconds() / 3600
                if 0 <= gap < self.min_rest_hours:
                    warnings.append(_('An adjacent shift is inside the configured rest period.'))
                    break
        # Count full shifts by local start date; see README for overnight boundary limitations.
        total = self.planned_hours + sum(s.planned_hours for s in others if week_start <= s.start < week_end)
        if self.weekly_hours_limit and total > self.weekly_hours_limit:
            warnings.append(_('Planned hours exceed the configured weekly review threshold.'))
        return warnings

    def action_publish(self):
        self._check_manager()
        self.check_access('write')
        self.lock_for_update()
        self.invalidate_recordset()
        # Serialize publication by employee, including concurrent new shifts.
        employees = self.mapped('employee_id').sorted('id')
        employees.lock_for_update()
        # A row change also invalidates old REPEATABLE READ snapshots: concurrent
        # publications retry instead of checking overlaps against a stale roster.
        for employee in employees:
            employee.binaryaid_roster_version += 1
        employees.flush_recordset(['binaryaid_roster_version'])
        for shift in self:
            if shift.state != 'draft':
                raise ValidationError(_('Only draft shifts can be published.'))
            shift._check_details()
            conflict = self.search_count([('employee_id', '=', shift.employee_id.id), ('id', '!=', shift.id),
                                          ('state', '=', 'published'), ('start', '<', shift.end), ('end', '>', shift.start)])
            if conflict:
                raise ValidationError(_('This employee already has an overlapping published shift.'))
            warnings = shift._review_warnings()
            if warnings and not (shift.review_note or '').strip():
                raise ValidationError('\n'.join(warnings) + '\n' + _('Record a manager review before publishing.'))
            super(WorkShift, shift).write({'state': 'published', 'published_at': fields.Datetime.now()})
            shift.message_post(body=_('Shift published. %s', ' '.join(warnings)),
                               partner_ids=shift.user_id.partner_id.ids)
        return True

    def _change_publication(self, state):
        self._check_manager()
        self.check_access('write')
        self.lock_for_update()
        self.invalidate_recordset()
        for shift in self:
            if shift.state != 'published' or not (shift.change_reason or '').strip():
                raise ValidationError(_('Provide a reason on a published shift before revising or cancelling it.'))
            shift.message_post(body=_('Shift %s: %s', state, shift.change_reason), partner_ids=shift.user_id.partner_id.ids)
            super(WorkShift, shift).write({'state': state, 'review_note': False, 'change_reason': False})
        return True

    def action_revise(self):
        return self._change_publication('draft')

    def action_cancel(self):
        return self._change_publication('cancelled')


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    binaryaid_roster_version = fields.Integer(default=0, readonly=True, copy=False, groups='hr.group_hr_user')
