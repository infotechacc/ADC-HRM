from datetime import timedelta

import pytz

from odoo import api, fields, models, Command, _
from odoo.exceptions import AccessError, ValidationError

from .assignment import ROSTER_TOKEN


class WorkShift(models.Model):
    _inherit = 'binaryaid.work.shift'

    @api.model
    def action_employee_shift_history(self):
        self._check_manager()
        self.check_access('read')
        return {'type': 'ir.actions.act_window', 'name': _('Employee Shift History'),
                'res_model': self._name, 'view_mode': 'list,form',
                'views': [(self.env.ref('binaryaid_roster_planning.view_employee_shift_history_list').id, 'list'),
                          (self.env.ref('binaryaid_work_scheduling.view_shift_form').id, 'form')],
                'search_view_id': self.env.ref('binaryaid_roster_planning.view_employee_shift_history_search').id,
                'domain': [('company_id', '=', self.env.company.id), ('end', '<=', fields.Datetime.now()),
                           ('state', 'in', ['published', 'cancelled'])],
                'context': dict(self.env.context, search_default_employee=1)}

    roster_assignment_id = fields.Many2one('binaryaid.roster.assignment', readonly=True, copy=False, ondelete='restrict', index=True, groups='binaryaid_work_management.group_work_admin')
    roster_generation_run_id = fields.Many2one('binaryaid.roster.run', readonly=True, copy=False, ondelete='restrict', groups='binaryaid_work_management.group_work_admin')
    roster_line_id = fields.Many2one('binaryaid.roster.template.line', readonly=True, copy=False, ondelete='restrict', groups='binaryaid_work_management.group_work_admin')
    roster_occurrence_date = fields.Date(readonly=True, copy=False, index=True)
    roster_policy_snapshot = fields.Json(readonly=True, copy=False, groups='binaryaid_work_management.group_work_admin')
    roster_task_specs = fields.Json(readonly=True, copy=False, groups='binaryaid_work_management.group_work_admin')
    roster_tasks_materialized = fields.Boolean(readonly=True, copy=False)
    roster_generated_task_ids = fields.Many2many('project.task', 'binaryaid_roster_shift_generated_task_rel', readonly=True, copy=False)
    roster_exception = fields.Boolean(readonly=True, copy=False, string='Employee-specific Exception')
    roster_replacement_for_id = fields.Many2one('binaryaid.work.shift', readonly=True, copy=False, ondelete='restrict', index=True)
    roster_department_id = fields.Many2one('hr.department', check_company=True, string='Department')
    roster_location_id = fields.Many2one('hr.work.location', check_company=True, string='Work Location')
    roster_event_ids = fields.One2many('binaryaid.roster.event', 'shift_id', string='Roster Audit')
    roster_actual_ids = fields.One2many('binaryaid.roster.actual', 'shift_id', string='Actual Work Approvals')
    roster_actual_hours = fields.Float(compute='_compute_roster_actual', string='Approved Actual Hours')
    roster_actual_approved = fields.Boolean(compute='_compute_roster_actual')

    _employee_state_start_idx = models.Index('(employee_id, state, start)')
    _employee_state_end_idx = models.Index('(employee_id, state, "end")')

    _occurrence_unique = models.Constraint(
        'UNIQUE(roster_assignment_id, roster_line_id, roster_occurrence_date)',
        'A roster occurrence already exists. Cancelled and changed occurrences must not be regenerated.')

    def _protected_roster_fields(self):
        return {'roster_generation_run_id', 'roster_assignment_id', 'roster_line_id', 'roster_occurrence_date', 'roster_policy_snapshot',
                'roster_task_specs', 'roster_tasks_materialized', 'roster_generated_task_ids',
                'roster_exception', 'roster_replacement_for_id'}

    @api.model_create_multi
    def create(self, vals_list):
        protected = self._protected_roster_fields()
        if self.env.context.get('_roster_internal') is not ROSTER_TOKEN:
            defaults = self.default_get(list(protected))
            if any(any(vals.get(k, defaults.get(k)) for k in protected) for vals in vals_list):
                raise AccessError(_('Roster provenance is maintained by the planning engine.'))
        shifts = super().create(vals_list)
        shifts._roster_event('created')
        return shifts

    def write(self, vals):
        internal = self.env.context.get('_roster_internal') is ROSTER_TOKEN
        if not internal and set(vals) & self._protected_roster_fields():
            raise AccessError(_('Roster provenance and history cannot be edited.'))
        if set(vals) & {'employee_id', 'company_id'}:
            for shift in self:
                if shift.published_at or shift.roster_assignment_id or shift.roster_replacement_for_id:
                    raise ValidationError(_('Use a replacement or swap to change responsibility; preserve the original employee.'))
        for shift in self:
            if shift.roster_policy_snapshot and set(vals) & {'award_reference', 'notice_hours', 'min_rest_hours', 'weekly_hours_limit'}:
                raise ValidationError(_('Generated shifts retain their policy snapshot; assign a new policy version for future shifts.'))
            if 'start' in vals and shift.roster_generated_task_ids:
                old_date = pytz.UTC.localize(shift.start).astimezone(pytz.timezone(shift.timezone)).date()
                new_date = pytz.UTC.localize(fields.Datetime.to_datetime(vals['start'])).astimezone(pytz.timezone(shift.timezone)).date()
                if old_date != new_date:
                    raise ValidationError(_('Replace a published task-bearing shift to move it to another work date.'))
        if not internal and any(s.roster_assignment_id for s in self) and set(vals) - {'change_reason', 'review_note'}:
            vals = dict(vals, roster_exception=True)
        result = super().write(vals)
        if set(vals) - {'change_reason'}:
            self._roster_event('edited')
        return result

    def unlink(self):
        if any(s.roster_assignment_id or s.roster_replacement_for_id or s.roster_event_ids for s in self):
            raise ValidationError(_('Keep roster records for history; cancel instead of deleting them.'))
        return super().unlink()

    @api.depends('roster_actual_ids')
    def _compute_roster_actual(self):
        for shift in self:
            latest = self.env['binaryaid.roster.actual'].search([('shift_id', '=', shift._origin.id)], order='id desc', limit=1) if shift._origin.id else self.env['binaryaid.roster.actual']
            shift.roster_actual_hours = latest.hours if latest and not latest.is_void else 0
            shift.roster_actual_approved = bool(latest and not latest.is_void)

    def _roster_event(self, event, reason=None):
        # Elevation is confined to append-only event creation after authorization.
        self.check_access('read')
        for shift in self:
            self.env['binaryaid.roster.event'].sudo().create({
                'shift_id': shift.id, 'company_id': shift.company_id.id,
                'employee_id': shift.employee_id.id, 'user_id': shift.user_id.id,
                'author_id': self.env.uid, 'event': event, 'reason': reason,
                'snapshot': {'name': shift.name, 'employee': shift.employee_name,
                             'start': str(shift.start), 'end': str(shift.end), 'state': shift.state,
                             'timezone': shift.timezone, 'planned_hours': shift.planned_hours,
                             'unpaid_break_minutes': shift.unpaid_break_minutes,
                             'break_instructions': shift.break_instructions, 'location': shift.location,
                             'instructions': shift.instructions, 'task_ids': shift.task_ids.ids,
                             'tasks': [{'id': t.id, 'name': t.name, 'work_date': str(t.binaryaid_work_date), 'state': t.state} for t in shift.task_ids]},
            })

    def _roster_transition_write(self, vals):
        reasons = {s.id: s.change_reason for s in self}
        result = super()._roster_transition_write(vals)
        for shift in self:
            shift._roster_event(vals.get('state', 'transition'), reasons[shift.id])
            if reasons[shift.id]:
                shift.with_context(mail_notify_force_send=False).message_post(body=_('Roster transition reason: %s', reasons[shift.id]))
        return result

    def _review_warnings(self):
        warnings = super()._review_warnings()
        policy = self.roster_policy_snapshot or {}
        elapsed = (self.end - self.start).total_seconds() / 3600
        if policy.get('max_shift_hours') and elapsed > policy['max_shift_hours']:
            warnings.append(_('Shift duration exceeds the policy review threshold.'))
        if policy.get('min_engagement_hours') and self.planned_hours < policy['min_engagement_hours']:
            warnings.append(_('Planned paid hours are below the minimum engagement review threshold.'))
        if (policy.get('break_after_hours') and elapsed > policy['break_after_hours']
                and self.unpaid_break_minutes < policy['min_unpaid_break_minutes']):
            warnings.append(_('Unpaid break duration is below the policy review threshold.'))
        self.check_access('read')
        # Private eligibility check: no leave reasons or other employees' data are returned.
        if self.env['resource.calendar.leaves'].sudo().search_count([
                ('resource_id', '=', False), ('company_id', 'in', [False, self.company_id.id]),
                ('calendar_id', 'in', [False, self.employee_id.resource_calendar_id.id]),
                ('date_from', '<', self.end), ('date_to', '>', self.start), ('time_type', '=', 'leave')], limit=1):
            warnings.append(_('This shift intersects configured public holiday / calendar time off.'))
        return warnings

    def _check_publication_eligibility(self):
        for shift in self:
            if shift.end <= fields.Datetime.now():
                raise ValidationError(_('Do not publish a shift that has already ended.'))
            # Limit privileged leave access to this already-authorized employee/company/window.
            leave_domain = [('employee_id', '=', shift.employee_id.id), ('company_id', '=', shift.company_id.id), ('state', '=', 'validate')]
            tz = pytz.timezone(shift.timezone)
            first_date = pytz.UTC.localize(shift.start).astimezone(tz).date()
            last_date = pytz.UTC.localize(shift.end - timedelta(microseconds=1)).astimezone(tz).date()
            full_day = [('request_unit_hours', '=', False), ('request_unit_half', '=', False),
                        ('request_date_from', '<=', last_date), ('request_date_to', '>=', first_date)]
            leaves = self.env['hr.leave'].sudo()
            if (leaves.search_count(leave_domain + [('date_from', '<', shift.end), ('date_to', '>', shift.start)], limit=1)
                    or leaves.search_count(leave_domain + full_day, limit=1)):
                raise ValidationError(_('The employee has approved time off during this shift.'))

    def _materialize_tasks(self):
        for shift in self:
            if shift.roster_task_specs and not shift.roster_tasks_materialized:
                date = pytz.UTC.localize(shift.start).astimezone(pytz.timezone(shift.timezone)).date()
                tasks = self.env['project.task'].with_context(mail_notify_force_send=False).create([
                    {'name': spec['name'], 'description': spec.get('description', ''),
                     'binaryaid_employee_id': shift.employee_id.id, 'binaryaid_work_date': date}
                    for spec in shift.roster_task_specs])
                shift.with_context(_roster_internal=ROSTER_TOKEN).write({
                    'roster_tasks_materialized': True, 'roster_generated_task_ids': [Command.set(tasks.ids)],
                    'task_ids': [Command.link(t.id) for t in tasks]})

    def action_publish(self):
        self._check_manager()
        self.check_access('write')
        self.lock_for_update()
        self.invalidate_recordset()
        self._check_publication_eligibility()
        # Atomic even when called from the generator: failed publication rolls back task creation.
        with self.env.cr.savepoint():
            self._materialize_tasks()
            return super().action_publish()

    def action_cancel(self):
        self._check_manager()
        self.check_access('write')
        self.lock_for_update()
        self.invalidate_recordset()
        for shift in self:
            if shift.start <= fields.Datetime.now():
                raise ValidationError(_('Cancel future shifts only. Record historical corrections through actual-work approvals.'))
            if shift.state == 'draft' and (shift.change_reason or '').strip():
                shift.with_context(mail_notify_force_send=False).message_post(body=_('Draft cancelled: %s', shift.change_reason))
                shift._roster_transition_write({'state': 'cancelled', 'change_reason': False})
            else:
                super(WorkShift, shift).action_cancel()
            shift.roster_generated_task_ids.write({'active': False})
        return True

    def action_revise(self):
        if any(s.start <= fields.Datetime.now() for s in self):
            raise ValidationError(_('Keep past roster plans fixed. Record actual-work corrections separately.'))
        return super().action_revise()

    def action_cover(self):
        self.ensure_one()
        self._check_manager()
        self.check_access('read')
        return {'type': 'ir.actions.act_window', 'name': _('Replace or Swap Shift'),
                'res_model': 'binaryaid.roster.cover.wizard', 'view_mode': 'form', 'target': 'new',
                'context': {'default_shift_id': self.id}}

    def action_approve_actual(self):
        self.ensure_one()
        self._check_manager()
        return {'type': 'ir.actions.act_window', 'name': _('Reconcile Actual Attendance'),
                'res_model': 'binaryaid.roster.actual.wizard', 'view_mode': 'form', 'target': 'new',
                'context': {'default_shift_id': self.id}}
