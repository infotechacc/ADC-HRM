from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


def check_manager(env):
    if not env.su and not env.user.has_group('binaryaid_work_management.group_work_admin'):
        raise AccessError(_('Only Work Management administrators can manage roster planning.'))


class RosterPolicy(models.Model):
    _name = 'binaryaid.roster.policy'
    _description = 'Versioned Roster Review Policy'
    _inherit = ['mail.thread']
    _check_company_auto = True

    name = fields.Char(required=True, tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    reference = fields.Char(required=True, string='Award / Agreement / Policy Reference', tracking=True)
    employment_type = fields.Selection([('full_time', 'Full time'), ('part_time', 'Part time'),
                                       ('casual', 'Casual'), ('other', 'Other / review required')], required=True, default='other')
    notice_hours = fields.Float(string='Minimum Notice Review (hours)')
    min_rest_hours = fields.Float(string='Minimum Rest Review (hours)')
    weekly_hours_limit = fields.Float(default=38, string='Weekly Hours Review Threshold')
    max_shift_hours = fields.Float(string='Maximum Shift Review (hours)')
    min_engagement_hours = fields.Float(string='Minimum Engagement Review (hours)')
    break_after_hours = fields.Float(string='Unpaid Break Required After (hours)')
    min_unpaid_break_minutes = fields.Integer(string='Minimum Unpaid Break (minutes)')
    approval_note = fields.Text(string='Policy Review Evidence', tracking=True, copy=False)
    state = fields.Selection([('draft', 'Draft'), ('active', 'Approved')], default='draft', required=True, copy=False, tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        check_manager(self.env)
        records = super().create(vals_list)
        if any(r.state != 'draft' for r in records):
            raise ValidationError(_('Create policies as drafts and approve them explicitly.'))
        return records

    def write(self, vals):
        check_manager(self.env)
        self.check_access('write')
        self.lock_for_update()
        self.invalidate_recordset(['state'])
        if 'state' in vals or any(p.state != 'draft' for p in self):
            raise ValidationError(_('Approved policies are immutable. Duplicate one for new terms.'))
        return super().write(vals)

    def unlink(self):
        if any(p.state != 'draft' for p in self):
            raise ValidationError(_('Keep approved policies for roster history.'))
        return super().unlink()

    @api.constrains('notice_hours', 'min_rest_hours', 'weekly_hours_limit', 'max_shift_hours',
                    'min_engagement_hours', 'break_after_hours', 'min_unpaid_break_minutes')
    def _check_thresholds(self):
        for p in self:
            if any(p[name] < 0 for name in p._threshold_fields()):
                raise ValidationError(_('Review thresholds cannot be negative.'))
            if bool(p.break_after_hours) != bool(p.min_unpaid_break_minutes):
                raise ValidationError(_('Specify both the break threshold and its minimum unpaid break.'))

    def _threshold_fields(self):
        return ['notice_hours', 'min_rest_hours', 'weekly_hours_limit', 'max_shift_hours',
                'min_engagement_hours', 'break_after_hours', 'min_unpaid_break_minutes']

    def _snapshot(self):
        self.ensure_one()
        return dict({name: self[name] for name in self._threshold_fields()}, reference=self.reference,
                    name=self.name, employment_type=self.employment_type, policy_id=self.id)

    def action_approve(self):
        check_manager(self.env)
        self.check_access('write')
        self.lock_for_update()
        self.invalidate_recordset()
        for policy in self:
            if policy.state != 'draft' or not (policy.approval_note or '').strip():
                raise ValidationError(_('Record policy review evidence before approval.'))
            super(RosterPolicy, policy).write({'state': 'active'})


class RosterTemplate(models.Model):
    _name = 'binaryaid.roster.template'
    _description = 'Versioned Roster Pattern'
    _inherit = ['mail.thread']
    _check_company_auto = True

    name = fields.Char(required=True, tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    timezone = fields.Selection([(tz, tz) for tz in pytz.all_timezones], required=True, default='Australia/Sydney')
    cycle_weeks = fields.Integer(required=True, default=1, help='1 to 12 weeks; cycle day 0 is Monday of week 1.')
    anchor_date = fields.Date(required=True, help='A Monday representing the start of week 1. Shared assignments keep the same rotation.')
    department_id = fields.Many2one('hr.department', check_company=True)
    policy_id = fields.Many2one('binaryaid.roster.policy', check_company=True, ondelete='restrict')
    previous_version_id = fields.Many2one('binaryaid.roster.template', readonly=True, copy=False, ondelete='restrict')
    common_tasks = fields.Text(string='Tasks for Every Shift', help='One task title per line. Fresh employee tasks are created at publication.')
    line_ids = fields.One2many('binaryaid.roster.template.line', 'template_id', copy=True)
    state = fields.Selection([('draft', 'Draft'), ('active', 'Released'), ('retired', 'Retired')], required=True, default='draft', copy=False, tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        check_manager(self.env)
        records = super().create(vals_list)
        if any(r.state != 'draft' for r in records):
            raise ValidationError(_('Create templates as drafts and release them explicitly.'))
        return records

    def _lock_draft(self):
        check_manager(self.env)
        self.check_access('write')
        self.lock_for_update()
        self.invalidate_recordset(['state'])
        if any(t.state != 'draft' for t in self):
            raise ValidationError(_('Released patterns are immutable. Create a new version for future assignments.'))

    def write(self, vals):
        self._lock_draft()
        if 'state' in vals or 'previous_version_id' in vals:
            raise AccessError(_('Use the release, retire and new version actions.'))
        return super().write(vals)

    def unlink(self):
        self._lock_draft()
        return super().unlink()

    @api.constrains('cycle_weeks', 'anchor_date')
    def _check_cycle(self):
        for t in self:
            if not 1 <= t.cycle_weeks <= 12 or t.anchor_date.weekday() != 0:
                raise ValidationError(_('Use a 1–12 week cycle and a Monday anchor date.'))

    def action_release(self):
        self._lock_draft()
        for template in self:
            if len(template.line_ids) > 500:
                raise ValidationError(_('Keep a pattern within 500 shift definitions.'))
            if not template.line_ids:
                raise ValidationError(_('Add at least one shift to the pattern.'))
            template.line_ids._check_hours()
            if template.policy_id and template.policy_id.state != 'active':
                raise ValidationError(_('Approve the review policy first.'))
            # Check pattern overlaps, including the wrap from the last cycle day to day 0.
            spans = [(l.cycle_day * 24 + l.start_hour,
                      l.cycle_day * 24 + int(l.end_day_offset) * 24 + l.end_hour) for l in template.line_ids]
            cycle = template.cycle_weeks * 7 * 24
            for i, (start, end) in enumerate(spans):
                for j, (other_start, other_end) in enumerate(spans):
                    if any(start < other_end + offset and end > other_start + offset
                           for offset in (-cycle, 0, cycle) if i != j or offset):
                        raise ValidationError(_('Pattern shifts overlap, including across a cycle boundary.'))
            super(RosterTemplate, template).write({'state': 'active'})

    def action_retire(self):
        check_manager(self.env)
        self.check_access('write')
        self.lock_for_update()
        for t in self:
            if t.state != 'active':
                raise ValidationError(_('Only released templates can be retired.'))
        return super().write({'state': 'retired'})

    def action_new_version(self):
        self.ensure_one()
        check_manager(self.env)
        new = self.copy({'name': _('%s (new version)', self.name), 'state': 'draft', 'previous_version_id': self.id})
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': new.id, 'view_mode': 'form'}

    def action_add_workweek(self):
        self.ensure_one()
        self._lock_draft()
        if self.line_ids:
            raise ValidationError(_('The workweek starter is only available for an empty pattern.'))
        self.env['binaryaid.roster.template.line'].create([
            {'template_id': self.id, 'name': _('Day shift'), 'cycle_day': day,
             'start_hour': 9, 'end_hour': 17, 'unpaid_break_minutes': 30} for day in range(5)])
        return True

    def action_assign(self):
        self.ensure_one()
        check_manager(self.env)
        return {'type': 'ir.actions.act_window', 'name': _('Assign Schedule to Employees'),
                'res_model': 'binaryaid.roster.assign.wizard', 'view_mode': 'form', 'target': 'new',
                'context': {'default_template_id': self.id, 'default_company_id': self.company_id.id}}


class RosterTemplateLine(models.Model):
    _name = 'binaryaid.roster.template.line'
    _description = 'Roster Cycle Shift'
    _order = 'cycle_day, start_hour, id'
    _check_company_auto = True

    name = fields.Char(required=True)
    template_id = fields.Many2one('binaryaid.roster.template', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='template_id.company_id', store=True)
    cycle_day = fields.Integer(required=True, default=0, help='0 = Monday week 1; 7 = Monday week 2.')
    cycle_label = fields.Char(compute='_compute_cycle_label')
    start_hour = fields.Float(required=True, default=9)
    end_hour = fields.Float(required=True, default=17)
    end_day_offset = fields.Selection([('0', 'Same day'), ('1', 'Next day')], default='0', required=True)
    unpaid_break_minutes = fields.Integer(default=30)
    break_instructions = fields.Text()
    instructions = fields.Text()
    location_id = fields.Many2one('hr.work.location', check_company=True)
    task_recipe_ids = fields.One2many('binaryaid.roster.task.recipe', 'line_id', copy=True)

    @api.depends('cycle_day')
    def _compute_cycle_label(self):
        weekdays = [_('Monday'), _('Tuesday'), _('Wednesday'), _('Thursday'), _('Friday'), _('Saturday'), _('Sunday')]
        for line in self:
            line.cycle_label = _('Week %s · %s', line.cycle_day // 7 + 1, weekdays[line.cycle_day % 7])

    @api.model_create_multi
    def create(self, vals_list):
        check_manager(self.env)
        defaults = self.default_get(['template_id'])
        for vals in vals_list:
            self.env['binaryaid.roster.template'].browse(vals.get('template_id') or defaults.get('template_id'))._lock_draft()
        return super().create(vals_list)

    def write(self, vals):
        (self.mapped('template_id') | self.env['binaryaid.roster.template'].browse(vals.get('template_id')))._lock_draft()
        return super().write(vals)

    def unlink(self):
        self.mapped('template_id')._lock_draft()
        return super().unlink()

    @api.constrains('cycle_day', 'start_hour', 'end_hour', 'end_day_offset', 'unpaid_break_minutes', 'template_id')
    def _check_hours(self):
        for line in self:
            duration = int(line.end_day_offset) * 24 + line.end_hour - line.start_hour
            if (not 0 <= line.cycle_day < line.template_id.cycle_weeks * 7
                    or not 0 <= line.start_hour < 24 or not 0 <= line.end_hour < 24
                    or not 0 < duration <= 24 or not 0 <= line.unpaid_break_minutes < duration * 60
                    or any(abs(h * 60 - round(h * 60)) > .00001 for h in (line.start_hour, line.end_hour))):
                raise ValidationError(_('Use valid cycle days, minute-precision times and a positive shift of at most 24 hours after breaks.'))

    def _utc_window(self, date):
        self.ensure_one()
        tz = pytz.timezone(self.template_id.timezone)
        start = datetime.combine(date, time.min) + timedelta(minutes=round(self.start_hour * 60))
        end = datetime.combine(date + timedelta(days=int(self.end_day_offset)), time.min) + timedelta(minutes=round(self.end_hour * 60))
        try:
            return (tz.localize(start, is_dst=None).astimezone(pytz.UTC).replace(tzinfo=None),
                    tz.localize(end, is_dst=None).astimezone(pytz.UTC).replace(tzinfo=None))
        except (pytz.AmbiguousTimeError, pytz.NonExistentTimeError) as exc:
            raise ValidationError(_('DST makes this local shift time ambiguous or nonexistent; create a reviewed manual exception.')) from exc


class RosterTaskRecipe(models.Model):
    _name = 'binaryaid.roster.task.recipe'
    _description = 'Reusable Shift Task Definition'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    description = fields.Html()
    line_id = fields.Many2one('binaryaid.roster.template.line', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='line_id.company_id', store=True)

    @api.model_create_multi
    def create(self, vals_list):
        check_manager(self.env)
        defaults = self.default_get(['line_id'])
        for vals in vals_list:
            self.env['binaryaid.roster.template.line'].browse(vals.get('line_id') or defaults.get('line_id')).template_id._lock_draft()
        return super().create(vals_list)

    def write(self, vals):
        lines = self.mapped('line_id') | self.env['binaryaid.roster.template.line'].browse(vals.get('line_id'))
        lines.mapped('template_id')._lock_draft()
        return super().write(vals)

    def unlink(self):
        self.mapped('line_id.template_id')._lock_draft()
        return super().unlink()
