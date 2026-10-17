from datetime import timedelta
import logging

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from .template import check_manager

_logger = logging.getLogger(__name__)
# An RPC context cannot manufacture this identity. Protects engine-owned provenance.
ROSTER_TOKEN = object()


class RosterAssignment(models.Model):
    _name = 'binaryaid.roster.assignment'
    _description = 'Effective Dated Employee Roster Assignment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'
    _check_company_auto = True
    _rec_name = 'employee_id'

    _state_write_idx = models.Index('(state, write_date, id)')

    employee_id = fields.Many2one('hr.employee', required=True, check_company=True, ondelete='restrict', index=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    template_id = fields.Many2one('binaryaid.roster.template', required=True, check_company=True, ondelete='restrict')
    policy_id = fields.Many2one('binaryaid.roster.policy', compute='_compute_policy', store=True, readonly=False, precompute=True, check_company=True, ondelete='restrict', tracking=True)
    department_id = fields.Many2one(related='employee_id.department_id', store=True)
    date_start = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    date_end = fields.Date(tracking=True, help='Inclusive last local start date. Empty means ongoing.')
    phase_days = fields.Integer(default=0, help='Rotation offset in cycle days. Zero shares the template anchor; positive values select a later day in the cycle.')
    horizon_days = fields.Integer(default=56, required=True, help='Rolling generation horizon, 7–366 days.')
    auto_publish = fields.Boolean(default=False, tracking=True,
                                 help='Publish only when every validation passes. Failures remain drafts with issues.')
    generated_until = fields.Date(readonly=True, copy=False)
    state = fields.Selection([('draft', 'Draft'), ('active', 'Active'), ('ended', 'Ended')], default='draft', required=True, copy=False, tracking=True)
    shift_ids = fields.One2many('binaryaid.work.shift', 'roster_assignment_id')
    end_reason = fields.Text(readonly=True, copy=False)

    @api.depends('template_id')
    def _compute_policy(self):
        for assignment in self:
            assignment.policy_id = assignment.template_id.policy_id

    @api.model_create_multi
    def create(self, vals_list):
        check_manager(self.env)
        records = super().create(vals_list)
        if any(r.state != 'draft' or r.generated_until or r.end_reason for r in records):
            raise ValidationError(_('Create assignments as drafts. Engine fields cannot be supplied.'))
        return records

    def write(self, vals):
        check_manager(self.env)
        self.check_access('write')
        self.lock_for_update()
        self.invalidate_recordset()
        if self.env.context.get('_roster_internal') is not ROSTER_TOKEN:
            if set(vals) & {'state', 'generated_until', 'end_reason'} or any(r.state != 'draft' for r in self):
                raise ValidationError(_('Activated assignments are fixed. End them with a reason and add a future assignment.'))
        return super().write(vals)

    def unlink(self):
        if any(a.state != 'draft' or a.shift_ids for a in self):
            raise ValidationError(_('Keep assignments and generated shifts for history.'))
        return super().unlink()

    @api.constrains('date_start', 'date_end', 'horizon_days', 'phase_days', 'employee_id', 'template_id', 'policy_id', 'auto_publish')
    def _check_details(self):
        for assignment in self:
            if assignment.date_end and assignment.date_end < assignment.date_start:
                raise ValidationError(_('The end date must not precede the start date.'))
            if not 0 <= assignment.phase_days < assignment.template_id.cycle_weeks * 7:
                raise ValidationError(_('Keep the rotation offset within the pattern cycle.'))
            if not 7 <= assignment.horizon_days <= 366:
                raise ValidationError(_('Use a rolling horizon of 7–366 days.'))
            employee = assignment.employee_id
            if (not employee.active or not employee.user_id.active or employee.user_id.share
                    or not employee.user_id.has_group('binaryaid_work_management.group_work_user')
                    or assignment.company_id not in employee.user_id.company_ids):
                raise ValidationError(_('Assign an active employee linked to a Work Management user in this company.'))
            if assignment.auto_publish and (not assignment.policy_id or assignment.policy_id.state != 'active'):
                raise ValidationError(_('Automatic publication requires an approved review policy.'))

    def action_activate(self):
        check_manager(self.env)
        self.check_access('write')
        self.lock_for_update()
        self.invalidate_recordset()
        employees = self.mapped('employee_id').sorted('id')
        employees.lock_for_update()
        for employee in employees:
            employee.binaryaid_roster_version += 1
        employees.flush_recordset(['binaryaid_roster_version'])
        for assignment in self:
            if assignment.state != 'draft' or assignment.template_id.state != 'active':
                raise ValidationError(_('Activate a draft assignment against a released template.'))
            assignment._check_details()
            if self.search_count([
                    ('employee_id', '=', assignment.employee_id.id), ('state', 'in', ['active', 'ended']), ('id', '!=', assignment.id),
                    ('date_start', '<=', assignment.date_end or '9999-12-31'),
                    '|', ('date_end', '=', False), ('date_end', '>=', assignment.date_start)]):
                raise ValidationError(_('This employee already has a roster assignment covering part of this period.'))
            assignment.with_context(_roster_internal=ROSTER_TOKEN).write({'state': 'active'})
        return True

    def action_generate(self):
        check_manager(self.env)
        self.check_access('read')
        return {'type': 'ir.actions.act_window', 'name': _('Generate Roster Preview'),
                'res_model': 'binaryaid.roster.generate.wizard', 'view_mode': 'form', 'target': 'new',
                'context': {'default_assignment_ids': [(6, 0, self.ids)]}}

    def action_end(self):
        self.ensure_one()
        check_manager(self.env)
        return {'type': 'ir.actions.act_window', 'name': _('End Assignment'),
                'res_model': 'binaryaid.roster.end.wizard', 'view_mode': 'form', 'target': 'new',
                'context': {'default_assignment_id': self.id}}

    def _end_on(self, date, reason):
        self.ensure_one()
        check_manager(self.env)
        self.check_access('write')
        self.lock_for_update()
        self.invalidate_recordset()
        if (self.state != 'active' or date < self.date_start
                or (self.date_end and date > self.date_end) or not reason.strip()):
            raise ValidationError(_('End an active assignment within its dates and provide a reason.'))
        shifts = self.shift_ids.filtered(lambda s: s.roster_occurrence_date > date and s.state != 'cancelled')
        if any(s.start <= fields.Datetime.now() for s in shifts):
            raise ValidationError(_('Do not change historical shifts when ending an assignment.'))
        for shift in shifts:
            shift.write({'change_reason': reason})
            shift.action_cancel()
        today = fields.Date.context_today(self.with_context(tz=self.template_id.timezone))
        self.with_context(_roster_internal=ROSTER_TOKEN).write({'date_end': date, 'state': 'active' if date >= today else 'ended', 'end_reason': reason})
        self.message_post(body=_('Assignment ended on %s: %s', date, reason))

    def _generate(self, date_from, date_to, run):
        self.ensure_one()
        check_manager(self.env)
        self.check_access('write')
        self.lock_for_update()
        self.invalidate_recordset()
        if self.state != 'active':
            raise ValidationError(_('Generate only active assignments.'))
        self._check_details()
        first = max(date_from, self.date_start)
        last = min(date_to, self.date_end or date_to)
        if first > last:
            return
        template = self.template_id
        line_by_day = {}
        for line in template.line_ids:
            line_by_day.setdefault(line.cycle_day, []).append(line)
        existing = self.env['binaryaid.work.shift'].search([
            ('roster_assignment_id', '=', self.id), ('roster_occurrence_date', '>=', first), ('roster_occurrence_date', '<=', last)])
        keys = {(s.roster_occurrence_date, s.roster_line_id.id) for s in existing}
        policy = self.policy_id._snapshot() if self.policy_id else {}
        for day_index in range((last - first).days + 1):
            date = first + timedelta(days=day_index)
            cycle_day = ((date - template.anchor_date).days + self.phase_days) % (template.cycle_weeks * 7)
            for line in line_by_day.get(cycle_day, []):
                if (date, line.id) in keys:
                    run._increment('skipped')
                    continue
                try:
                    with self.env.cr.savepoint():
                        start, end = line._utc_window(date)
                        if end <= fields.Datetime.now():
                            run._increment('skipped')
                            continue
                        if self.env['binaryaid.work.shift'].search_count([
                                ('employee_id', '=', self.employee_id.id), ('state', '!=', 'cancelled'),
                                ('start', '<', end), ('end', '>', start)]):
                            raise ValidationError(_('An existing draft or published shift overlaps this occurrence.'))
                        vals = {
                            'name': line.name, 'company_id': self.company_id.id, 'employee_id': self.employee_id.id,
                            'start': start, 'end': end, 'timezone': template.timezone,
                            'unpaid_break_minutes': line.unpaid_break_minutes,
                            'break_instructions': line.break_instructions, 'instructions': line.instructions,
                            'location': line.location_id.name or False,
                            'roster_location_id': line.location_id.id,
                            'roster_department_id': template.department_id.id or self.employee_id.department_id.id,
                            'roster_assignment_id': self.id, 'roster_line_id': line.id, 'roster_occurrence_date': date,
                            'roster_generation_run_id': run.id,
                            'roster_policy_snapshot': policy,
                            'roster_task_specs': ([{'name': title.strip(), 'description': ''} for title in (template.common_tasks or '').splitlines() if title.strip()]
                                                  + [{'name': r.name, 'description': r.description or ''} for r in line.task_recipe_ids]),
                            'award_reference': policy.get('reference'),
                        }
                        for field in ('notice_hours', 'min_rest_hours', 'weekly_hours_limit'):
                            if policy:
                                vals[field] = policy[field]
                        shift = self.env['binaryaid.work.shift'].with_context(_roster_internal=ROSTER_TOKEN).create(vals)
                        run._increment('created')
                except (ValidationError, UserError) as exc:
                    run._issue(self, date, line, str(exc))
                    continue
                if self.auto_publish:
                    try:
                        with self.env.cr.savepoint():
                            # Automatic publication never supplies a review override.
                            if shift.start <= fields.Datetime.now():
                                raise ValidationError(_('Automatic publication does not backdate a shift that has already started.'))
                            if shift._review_warnings():
                                raise ValidationError('\n'.join(shift._review_warnings()))
                            shift.action_publish()
                    except (ValidationError, UserError) as exc:
                        run._issue(self, date, line, str(exc), shift)
        # This is informational, not a skip cursor: reruns retry missing DST/failed slots.
        self.with_context(_roster_internal=ROSTER_TOKEN).write({'generated_until': max(self.generated_until or last, last)})

    @api.model
    def _cron_generate(self):
        # Bounded per invocation and fair rotation by last processing timestamp.
        assignments = self.with_context(allowed_company_ids=self.env.user.company_ids.ids).search(
            [('state', '=', 'active')], order='write_date, id', limit=100)
        for assignment in assignments:
            today = fields.Date.context_today(assignment.with_context(tz=assignment.template_id.timezone))
            if assignment.date_end and assignment.date_end < today:
                assignment.with_context(_roster_internal=ROSTER_TOKEN).write({'state': 'ended', 'end_reason': _('Effective period completed.')})
                continue
            try:
                with self.env.cr.savepoint():
                    run = self.env['binaryaid.roster.run']._start(assignment.ids, today, today + timedelta(days=assignment.horizon_days - 1), 'automatic')
                    try:
                        with self.env.cr.savepoint():
                            assignment._generate(run.date_from, run.date_to, run)
                    except (ValidationError, UserError) as exc:
                        run._issue(assignment, today, None, str(exc))
                    run._finish()
                    # Failed assignments also rotate, so they cannot starve other employees.
                    assignment.with_context(_roster_internal=ROSTER_TOKEN).write({'generated_until': assignment.generated_until})
            except Exception:
                _logger.exception('Roster generation failed for assignment %s', assignment.id)
                summary = _('Roster generation failed; review the server logs.')
                if not assignment.activity_ids.filtered(lambda a: a.summary == summary):
                    assignment.activity_schedule('mail.mail_activity_data_todo', user_id=assignment.create_uid.id,
                                                 summary=summary)
            if self.env.context.get('cron_id'):
                if not self.env['ir.cron']._commit_progress(1):
                    break


class RosterRun(models.Model):
    _name = 'binaryaid.roster.run'
    _description = 'Roster Generation Run'
    _order = 'id desc'
    _rec_name = 'create_date'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    assignment_ids = fields.Many2many('binaryaid.roster.assignment', readonly=True)
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    source = fields.Selection([('manual', 'Manual'), ('automatic', 'Automatic')], required=True)
    state = fields.Selection([('running', 'Running'), ('complete', 'Complete'), ('review', 'Needs review')], default='running')
    created = fields.Integer()
    skipped = fields.Integer()
    issue_ids = fields.One2many('binaryaid.roster.issue', 'run_id')

    @api.model
    def _start(self, assignments, date_from, date_to, source='manual'):
        check_manager(self.env)
        records = self.env['binaryaid.roster.assignment'].browse(assignments)
        records.check_access('read')
        if len(records.mapped('company_id')) != 1:
            raise ValidationError(_('Generate one company at a time.'))
        if date_to < date_from or (date_to - date_from).days > 365 or len(records) > 100:
            raise ValidationError(_('Generate up to 366 days for at most 100 employees per run.'))
        days = (date_to - date_from).days + 1
        estimate = sum((days // (a.template_id.cycle_weeks * 7) + 2) * len(a.template_id.line_ids) for a in records)
        if estimate > 10000:
            raise ValidationError(_('This preview exceeds 10,000 potential shifts. Split the date range or employee batch.'))
        return self.with_context(_roster_internal=ROSTER_TOKEN).create({
            'company_id': records.company_id.id, 'assignment_ids': [(6, 0, records.ids)],
            'date_from': date_from, 'date_to': date_to, 'source': source})

    def action_open_shifts(self):
        self.ensure_one()
        check_manager(self.env)
        self.check_access('read')
        return {'type': 'ir.actions.act_window', 'name': _('Generated Occurrences'),
                'res_model': 'binaryaid.work.shift', 'view_mode': 'list,calendar,form',
                'domain': [('roster_assignment_id', 'in', self.assignment_ids.ids),
                           ('roster_occurrence_date', '>=', self.date_from), ('roster_occurrence_date', '<=', self.date_to)]}

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('_roster_internal') is not ROSTER_TOKEN:
            raise AccessError(_('Generation runs are maintained by the engine.'))
        return super().create(vals_list)

    def write(self, vals):
        if self.env.context.get('_roster_internal') is not ROSTER_TOKEN:
            raise AccessError(_('Generation runs are maintained by the engine.'))
        return super().write(vals)

    def _increment(self, field):
        self.with_context(_roster_internal=ROSTER_TOKEN).write({field: self[field] + 1})

    def _issue(self, assignment, date, line, message, shift=None):
        self.env['binaryaid.roster.issue'].with_context(_roster_internal=ROSTER_TOKEN).create({
            'run_id': self.id, 'assignment_id': assignment.id, 'date': date,
            'line_id': line.id if line else False, 'message': message, 'shift_id': shift.id if shift else False})

    def _finish(self):
        self.with_context(_roster_internal=ROSTER_TOKEN).write({'state': 'review' if self.issue_ids else 'complete'})


class RosterIssue(models.Model):
    _name = 'binaryaid.roster.issue'
    _description = 'Roster Generation Issue'
    _order = 'id desc'

    run_id = fields.Many2one('binaryaid.roster.run', required=True, ondelete='restrict')
    company_id = fields.Many2one(related='run_id.company_id', store=True)
    assignment_id = fields.Many2one('binaryaid.roster.assignment', required=True, ondelete='restrict')
    date = fields.Date(required=True)
    line_id = fields.Many2one('binaryaid.roster.template.line', ondelete='restrict')
    shift_id = fields.Many2one('binaryaid.work.shift', ondelete='restrict')
    message = fields.Text(required=True)

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('_roster_internal') is not ROSTER_TOKEN:
            raise AccessError(_('Generation issues are maintained by the engine.'))
        return super().create(vals_list)
