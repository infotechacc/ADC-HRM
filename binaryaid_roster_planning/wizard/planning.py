from datetime import timedelta

import pytz

from odoo import api, fields, models, Command, _
from odoo.exceptions import ValidationError

from ..models.assignment import ROSTER_TOKEN
from ..models.template import check_manager


def window_action(model, ids, name):
    return {'type': 'ir.actions.act_window', 'name': name, 'res_model': model,
            'view_mode': 'list,form', 'domain': [('id', 'in', ids)]}


class AssignWizard(models.TransientModel):
    _name = 'binaryaid.roster.assign.wizard'
    _description = 'Bulk Effective Dated Roster Assignment'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    template_id = fields.Many2one('binaryaid.roster.template', required=True, check_company=True, domain="[('state', '=', 'active')]")
    policy_id = fields.Many2one('binaryaid.roster.policy', check_company=True, domain="[('state', '=', 'active')]", help='Optional override for this employee group; otherwise use the pattern default.')
    department_id = fields.Many2one('hr.department', check_company=True)
    employee_ids = fields.Many2many('hr.employee', required=True, check_company=True)
    date_start = fields.Date(required=True, default=fields.Date.context_today)
    date_end = fields.Date()
    phase_days = fields.Integer(default=0, string='Rotation Offset (days)')
    horizon_days = fields.Integer(default=56, required=True)
    auto_publish = fields.Boolean(default=False)

    def action_assign(self):
        self.ensure_one()
        check_manager(self.env)
        self.check_access('read')
        if not self.employee_ids or len(self.employee_ids) > 100:
            raise ValidationError(_('Select 1–100 employees per bulk assignment.'))
        self.employee_ids.check_access('read')
        if any(e.company_id != self.company_id for e in self.employee_ids):
            raise ValidationError(_('Select employees in the assignment company.'))
        with self.env.cr.savepoint():
            assignments = self.env['binaryaid.roster.assignment'].create([
                {'company_id': self.company_id.id, 'template_id': self.template_id.id, 'employee_id': e.id,
                 'date_start': self.date_start, 'date_end': self.date_end,
                 'horizon_days': self.horizon_days, 'phase_days': self.phase_days, 'auto_publish': self.auto_publish,
                 **({'policy_id': self.policy_id.id} if self.policy_id else {})}
                for e in self.employee_ids])
            assignments.action_activate()
        return window_action(assignments._name, assignments.ids, _('Employee Schedule Assignments'))


class GenerateWizard(models.TransientModel):
    _name = 'binaryaid.roster.generate.wizard'
    _description = 'Preview Roster Generation'

    assignment_ids = fields.Many2many('binaryaid.roster.assignment', 'ba_roster_generate_assignment_rel', required=True)
    date_from = fields.Date(required=True, default=fields.Date.context_today)
    date_to = fields.Date(required=True, default=lambda self: fields.Date.add(fields.Date.context_today(self), days=55))
    estimated_occurrences = fields.Integer(compute='_compute_estimate', string='Upper Bound of Occurrences')

    @api.depends('assignment_ids', 'date_from', 'date_to')
    def _compute_estimate(self):
        for wizard in self:
            days = max(0, (wizard.date_to - wizard.date_from).days + 1) if wizard.date_from and wizard.date_to else 0
            wizard.estimated_occurrences = sum((days // (a.template_id.cycle_weeks * 7) + 2) * len(a.template_id.line_ids)
                                               for a in wizard.assignment_ids)

    def action_generate(self):
        self.ensure_one()
        check_manager(self.env)
        self.check_access('read')
        if not self.assignment_ids:
            raise ValidationError(_('Select active assignments.'))
        run = self.env['binaryaid.roster.run']._start(self.assignment_ids.ids, self.date_from, self.date_to)
        for assignment in self.assignment_ids.sorted('id'):
            assignment._generate(self.date_from, self.date_to, run)
        run._finish()
        return run.action_open_shifts()


class EndWizard(models.TransientModel):
    _name = 'binaryaid.roster.end.wizard'
    _description = 'End Roster Assignment'

    assignment_id = fields.Many2one('binaryaid.roster.assignment', required=True)
    date_end = fields.Date(required=True, default=fields.Date.context_today)
    reason = fields.Text(required=True)

    def action_end(self):
        self.ensure_one()
        check_manager(self.env)
        self.assignment_id._end_on(self.date_end, self.reason or '')
        return {'type': 'ir.actions.act_window_close'}


class PublishWizard(models.TransientModel):
    _name = 'binaryaid.roster.publish.wizard'
    _description = 'Review and Publish Roster Batch'

    shift_ids = fields.Many2many('binaryaid.work.shift', required=True)
    review_note = fields.Text(string='Review / Consultation Evidence', help='Applied to every selected draft; does not replace required employee consultation or consent.')

    def action_publish(self):
        self.ensure_one()
        check_manager(self.env)
        self.shift_ids.check_access('write')
        if not self.shift_ids or len(self.shift_ids) > 500:
            raise ValidationError(_('Select 1–500 draft shifts per publication batch.'))
        with self.env.cr.savepoint():
            if self.review_note:
                self.shift_ids.write({'review_note': self.review_note})
            self.shift_ids.action_publish()
        return {'type': 'ir.actions.act_window_close'}


class CoverWizard(models.TransientModel):
    _name = 'binaryaid.roster.cover.wizard'
    _description = 'Atomic Shift Replacement or Swap'
    _check_company_auto = True

    shift_id = fields.Many2one('binaryaid.work.shift', required=True)
    company_id = fields.Many2one(related='shift_id.company_id')
    mode = fields.Selection([('replace', 'Replacement / Cover'), ('swap', 'Swap Two Shifts')], default='replace', required=True)
    employee_id = fields.Many2one('hr.employee', string='Replacement Employee', check_company=True)
    swap_shift_id = fields.Many2one('binaryaid.work.shift', check_company=True)
    policy_id = fields.Many2one('binaryaid.roster.policy', check_company=True, domain="[('state', '=', 'active')]", string='Coverage Policy Override')
    reason = fields.Text(required=True, string='Reason and Consultation / Consent Evidence')
    review_note = fields.Text(string='Threshold Exception Review')

    def _replacement_values(self, original, employee):
        date = pytz.UTC.localize(original.start).astimezone(pytz.timezone(original.timezone)).date()
        assignment = self.env['binaryaid.roster.assignment'].search([
            ('employee_id', '=', employee.id), ('state', 'in', ['active', 'ended']), ('date_start', '<=', date),
            '|', ('date_end', '=', False), ('date_end', '>=', date)], limit=1)
        policy = self.policy_id or assignment.policy_id
        if not policy or policy.state != 'active':
            raise ValidationError(_('Select an approved coverage policy, or assign an approved policy to the receiving employee’s roster.'))
        if policy.company_id != original.company_id:
            raise ValidationError(_('Coverage policy and shift must belong to the same company.'))
        specs = original.roster_task_specs or [
            {'name': t.name, 'description': t.description or ''} for t in original.task_ids]
        vals = {
            'name': original.name, 'employee_id': employee.id, 'company_id': original.company_id.id,
            'start': original.start, 'end': original.end, 'timezone': original.timezone,
            'unpaid_break_minutes': original.unpaid_break_minutes, 'break_instructions': original.break_instructions,
            'instructions': original.instructions, 'location': original.location,
            'roster_location_id': original.roster_location_id.id, 'roster_department_id': original.roster_department_id.id,
            'roster_replacement_for_id': original.id, 'roster_exception': True,
            'roster_policy_snapshot': policy._snapshot(), 'roster_task_specs': specs,
            'review_note': self.review_note, 'award_reference': policy.reference,
        }
        vals.update({key: policy[key] for key in ('notice_hours', 'min_rest_hours', 'weekly_hours_limit')})
        return vals

    def action_apply(self):
        self.ensure_one()
        check_manager(self.env)
        self.check_access('read')
        if not (self.reason or '').strip():
            raise ValidationError(_('Record the reason and consultation/consent evidence.'))
        sources = self.shift_id
        if self.mode == 'swap':
            if not self.swap_shift_id or self.swap_shift_id == self.shift_id:
                raise ValidationError(_('Select a different published shift to swap.'))
            sources |= self.swap_shift_id
        elif not self.employee_id:
            raise ValidationError(_('Select a replacement employee.'))
        sources.check_access('write')
        sources.sorted('id').lock_for_update()
        sources.invalidate_recordset()
        if any(s.state != 'published' or s.start <= fields.Datetime.now() for s in sources):
            raise ValidationError(_('Replace or swap future published shifts only.'))
        if len(sources.company_id) != 1:
            raise ValidationError(_('Swap within one company.'))
        targets = [(self.shift_id, self.employee_id)] if self.mode == 'replace' else [
            (self.shift_id, self.swap_shift_id.employee_id), (self.swap_shift_id, self.shift_id.employee_id)]
        employees = sources.employee_id | self.employee_id
        employees.check_access('read')
        employees.sorted('id').lock_for_update()
        for employee in employees:
            employee.binaryaid_roster_version += 1
        employees.flush_recordset(['binaryaid_roster_version'])
        for source, employee in targets:
            if employee == source.employee_id or employee.company_id != source.company_id:
                raise ValidationError(_('Choose a different employee in the same company.'))
            if self.env['binaryaid.work.shift'].search_count([
                    ('employee_id', '=', employee.id), ('id', 'not in', sources.ids), ('state', '!=', 'cancelled'),
                    ('start', '<', source.end), ('end', '>', source.start)]):
                raise ValidationError(_('The receiving employee already has an overlapping draft or published shift.'))
        with self.env.cr.savepoint():
            values = [self._replacement_values(source, employee) for source, employee in targets]
            sources.write({'change_reason': self.reason})
            sources.action_cancel()
            replacements = self.env['binaryaid.work.shift'].with_context(_roster_internal=ROSTER_TOKEN).create(values)
            replacements.action_publish()
            for shift in replacements:
                shift._roster_event('coverage', self.reason)
                shift.with_context(mail_notify_force_send=False).message_post(body=_('Coverage / swap approved: %s', self.reason))
        return window_action(replacements._name, replacements.ids, _('Approved Coverage Shifts'))


class ActualWizard(models.TransientModel):
    _name = 'binaryaid.roster.actual.wizard'
    _description = 'Reconcile Native Attendance with a Shift'

    shift_id = fields.Many2one('binaryaid.work.shift', required=True)
    employee_id = fields.Many2one(related='shift_id.employee_id')
    attendance_ids = fields.Many2many('hr.attendance', string='Closed Attendance Sessions')
    is_void = fields.Boolean(string='Reverse Previous Approval')
    reason = fields.Text(required=True, string='Approval / Correction / Reversal Reason')

    def action_approve(self):
        self.ensure_one()
        check_manager(self.env)
        shift = self.shift_id
        shift.check_access('write')
        shift.lock_for_update()
        shift.invalidate_recordset()
        if shift.state != 'published' or shift.end > fields.Datetime.now() or not (self.reason or '').strip():
            raise ValidationError(_('Reconcile a completed published shift and provide a reason.'))
        actual_model = self.env['binaryaid.roster.actual']
        attendances = self.attendance_ids
        if self.is_void:
            latest = actual_model.search([('shift_id', '=', shift.id)], limit=1)
            if not latest or latest.is_void:
                raise ValidationError(_('There is no current approval to reverse.'))
            attendances = self.env['hr.attendance']
        else:
            if not attendances:
                raise ValidationError(_('Select closed attendance sessions.'))
            attendances.check_access('write')
            attendances.sorted('id').lock_for_update()
            attendances.invalidate_recordset()
            if any(a.employee_id != shift.employee_id or not a.check_out or a.check_out > fields.Datetime.now()
                   or a.check_in >= shift.end or a.check_out <= shift.start for a in attendances):
                raise ValidationError(_('Select this employee’s closed attendance sessions intersecting the shift.'))
            # Serialize approvals for this employee without changing attendance source data.
            employee = shift.employee_id
            employee.lock_for_update()
            employee.binaryaid_roster_version += 1
            employee.flush_recordset(['binaryaid_roster_version'])
            other_shifts = actual_model.search([('attendance_ids', 'in', attendances.ids), ('shift_id', '!=', shift.id)]).shift_id
            for other in other_shifts:
                latest = actual_model.search([('shift_id', '=', other.id)], limit=1)
                if not latest.is_void and latest.attendance_ids & attendances:
                    raise ValidationError(_('An attendance session is already approved against another shift. Reverse or correct that approval first.'))
        record = actual_model.with_context(_roster_internal=ROSTER_TOKEN).create({
            'shift_id': shift.id, 'employee_id': shift.employee_id.id, 'company_id': shift.company_id.id,
            'user_id': shift.user_id.id, 'author_id': self.env.uid, 'is_void': self.is_void,
            'attendance_ids': [Command.set(attendances.ids)], 'hours': sum(attendances.mapped('worked_hours')),
            'reason': self.reason, 'snapshot': {'sessions': [
                {'id': a.id, 'check_in': str(a.check_in), 'check_out': str(a.check_out), 'native_worked_hours': a.worked_hours}
                for a in attendances], 'planned_hours_at_approval': shift.planned_hours}})
        shift._roster_event('actual_reversed' if self.is_void else 'actual_approved', self.reason)
        shift.with_context(mail_notify_force_send=False).message_post(body=_('Actual-work reconciliation: %s hours. %s', record.hours, self.reason))
        return {'type': 'ir.actions.act_window_close'}
