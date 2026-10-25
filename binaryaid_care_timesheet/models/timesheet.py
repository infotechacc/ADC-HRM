import csv
import io
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import format_datetime

from odoo.addons.binaryaid_care.models.tools import fortnight_start, get_param


def check_admin(env):
    if not env.su and not env.user.has_group('binaryaid_work_management.group_work_admin'):
        raise AccessError(_('Only roster administrators can review timesheets.'))


class CareTimesheet(models.Model):
    _name = 'binaryaid.care.timesheet'
    _description = 'Fortnightly Timesheet'
    _inherit = ['mail.thread']
    _order = 'period_start desc, employee_id'
    _check_company_auto = True

    name = fields.Char(compute='_compute_name', store=True)
    employee_id = fields.Many2one('hr.employee', required=True, readonly=True, index=True, check_company=True)
    user_id = fields.Many2one(related='employee_id.user_id', store=True, index=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True, default=lambda self: self.env.company)
    period_start = fields.Date(required=True, readonly=True, index=True)
    period_end = fields.Date(compute='_compute_period_end', store=True)
    state = fields.Selection([('draft', 'Open'), ('review', 'In review'), ('approved', 'Approved'), ('locked', 'Locked')],
                             default='draft', required=True, readonly=True, tracking=True, index=True)
    line_ids = fields.One2many('binaryaid.care.timesheet.line', 'timesheet_id', string='Shifts', readonly=True)
    planned_hours = fields.Float(compute='_compute_totals', store=True, string='Planned')
    actual_hours = fields.Float(compute='_compute_totals', store=True, string='Actual')
    adjusted_hours = fields.Float(compute='_compute_totals', store=True, string='Adjusted',
                                  help='Actual hours after reviewer adjustments, all rows.')
    approved_hours = fields.Float(compute='_compute_totals', store=True, string='Approved',
                                  help='Complete rows only. Incomplete and unresolved rows are excluded.')
    issue_count = fields.Integer(compute='_compute_totals', store=True, string='Rows needing attention')
    reviewer_id = fields.Many2one('res.users', readonly=True, tracking=True)
    approved_on = fields.Datetime(readonly=True)
    locked_on = fields.Datetime(readonly=True)

    _unique_period = models.Constraint('UNIQUE(employee_id, period_start)', 'One timesheet per employee and fortnight.')

    @api.depends('employee_id', 'period_start')
    def _compute_name(self):
        for sheet in self:
            sheet.name = '%s – %s' % (sheet.employee_id.name or '', sheet.period_start or '')

    @api.depends('period_start')
    def _compute_period_end(self):
        for sheet in self:
            sheet.period_end = sheet.period_start and sheet.period_start + timedelta(days=13)

    @api.depends('line_ids.planned_hours', 'line_ids.actual_hours', 'line_ids.effective_hours',
                 'line_ids.approved_hours', 'line_ids.status')
    def _compute_totals(self):
        for sheet in self:
            lines = sheet.line_ids
            sheet.planned_hours = sum(lines.mapped('planned_hours'))
            sheet.actual_hours = sum(lines.mapped('actual_hours'))
            sheet.adjusted_hours = sum(lines.mapped('effective_hours'))
            sheet.approved_hours = sum(lines.mapped('approved_hours'))
            sheet.issue_count = len(lines.filtered(lambda l: l.status != 'complete'))

    def _period_bounds(self):
        self.ensure_one()
        tz = pytz.timezone(self.env.user.tz or 'Australia/Sydney')
        start = tz.localize(datetime.combine(self.period_start, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
        end = tz.localize(datetime.combine(self.period_start + timedelta(days=14), time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
        return start, end

    @api.model
    def _generate(self, period_start, employees=None):
        """Create or refresh open timesheets for everyone with published shifts in the fortnight."""
        check_admin(self.env)
        period_start = fortnight_start(self.env, period_start)
        probe = self.new({'period_start': period_start})
        start, end = probe._period_bounds()
        domain = [('state', '=', 'published'), ('start', '>=', start), ('start', '<', end),
                  ('company_id', '=', self.env.company.id)]
        if employees:
            domain.append(('employee_id', 'in', employees.ids))
        shifts = self.env['binaryaid.work.shift'].search(domain)
        sheets = self.browse()
        for employee in shifts.employee_id:
            sheet = self.search([('employee_id', '=', employee.id), ('period_start', '=', period_start)], limit=1)
            if not sheet:
                sheet = self.create({'employee_id': employee.id, 'period_start': period_start,
                                     'company_id': self.env.company.id})
            if sheet.state in ('draft', 'review'):
                sheet._refresh_lines()
            sheets |= sheet
        return sheets

    def _refresh_lines(self):
        """Rebuild rows from shifts and attendance. Reviewer adjustments and corrections are kept."""
        for sheet in self:
            if sheet.state not in ('draft', 'review'):
                raise UserError(_('Approved or locked timesheets cannot be refreshed.'))
            start, end = sheet._period_bounds()
            shifts = self.env['binaryaid.work.shift'].search([
                ('employee_id', '=', sheet.employee_id.id), ('state', '=', 'published'),
                ('start', '>=', start), ('start', '<', end)])
            existing = {line.shift_id.id: line for line in sheet.line_ids}
            for shift in shifts:
                values = sheet._line_values(shift)
                if shift.id in existing:
                    existing.pop(shift.id).sudo().write(values)
                else:
                    self.env['binaryaid.care.timesheet.line'].sudo().create(dict(values, timesheet_id=sheet.id, shift_id=shift.id))
            # Shifts cancelled since the last refresh leave the timesheet unless adjusted by a reviewer.
            for line in existing.values():
                if not line.has_adjustment:
                    line.sudo().unlink()

    def _line_values(self, shift):
        attendances = self.env['hr.attendance'].sudo().search([
            ('employee_id', '=', shift.employee_id.id), '|', ('binaryaid_shift_id', '=', shift.id),
            '&', ('binaryaid_shift_id', '=', False), '&', ('check_in', '<', shift.end),
            '|', ('check_out', '=', False), ('check_out', '>', shift.start)], order='check_in')
        open_attendance = attendances.filtered(lambda a: not a.check_out)
        exceptions = self.env['binaryaid.care.attendance.exception'].sudo().search_count(
            [('shift_id', '=', shift.id), ('state', '=', 'submitted')])
        note_status = shift.care_note_status
        issues = []
        if not attendances:
            issues.append(_('No clock events'))
        if open_attendance:
            issues.append(_('Missing sign out'))
        if note_status != 'submitted':
            issues.append(_('Shift note not submitted'))
        if exceptions:
            issues.append(_('Exception awaiting review'))
        breaks = shift.unpaid_break_minutes / 60 if get_param(self.env, 'apply_unpaid_breaks') == 'True' else 0.0
        closed = attendances - open_attendance
        return {
            'planned_hours': round(shift.planned_hours, 2),
            'actual_check_in': attendances[:1].check_in or False,
            'actual_check_out': closed and max(closed.mapped('check_out')) or False,
            # Raw clock duration: native worked_hours deducts calendar lunch breaks, which must
            # only apply once ADC agrees its break rules (see the unpaid breaks setting).
            'actual_hours': round(sum((a.check_out - a.check_in).total_seconds() / 3600 for a in closed), 2),
            'break_hours': round(breaks, 2),
            'clock_event_count': len(attendances),
            'note_submitted': note_status == 'submitted',
            'open_exception': bool(exceptions),
            'issues': ', '.join(issues),
            'incomplete': bool(not attendances or open_attendance or note_status != 'submitted'),
        }

    def _check_editable(self):
        if self.filtered(lambda s: s.state in ('approved', 'locked')):
            raise UserError(_('Approved or locked timesheets cannot change. Reset an approved timesheet to review first.'))

    def action_refresh(self):
        check_admin(self.env)
        self._refresh_lines()
        return True

    def action_submit_review(self):
        check_admin(self.env)
        self._check_editable()
        self._refresh_lines()
        self.write({'state': 'review'})
        return True

    def action_approve(self):
        check_admin(self.env)
        for sheet in self:
            if sheet.state not in ('draft', 'review'):
                raise UserError(_('%s is already approved.', sheet.name))
            sheet._refresh_lines()
            sheet.write({'state': 'approved', 'reviewer_id': self.env.uid, 'approved_on': fields.Datetime.now()})
            excluded = sheet.line_ids.filtered(lambda l: l.status != 'complete')
            sheet.message_post(body=_('Approved %(hours).2f hours. %(count)s row(s) excluded as incomplete or unresolved.',
                                      hours=sheet.approved_hours, count=len(excluded)))
        return True

    def action_reset_review(self):
        check_admin(self.env)
        if self.filtered(lambda s: s.state != 'approved'):
            raise UserError(_('Only approved, unlocked timesheets can be reopened.'))
        self.write({'state': 'review', 'approved_on': False})
        return True

    def action_lock(self):
        check_admin(self.env)
        if self.filtered(lambda s: s.state != 'approved'):
            raise UserError(_('Approve the timesheet before locking it.'))
        self.write({'state': 'locked', 'locked_on': fields.Datetime.now()})
        return True

    def write(self, vals):
        if not self.env.su and self.filtered(lambda s: s.state == 'locked') and set(vals) - {'message_main_attachment_id'}:
            raise AccessError(_('Locked timesheets cannot change.'))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda s: s.state in ('approved', 'locked')):
            raise UserError(_('Approved and locked timesheets are kept.'))
        return super().unlink()

    def action_export_csv(self):
        """Approved timesheets only, with employee, shift, client and time references. Does not run payroll."""
        check_admin(self.env)
        sheets = self.filtered(lambda s: s.state in ('approved', 'locked'))
        if not sheets:
            raise UserError(_('Select approved or locked timesheets to export.'))
        tz = self.env.user.tz or 'Australia/Sydney'
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(['Employee ID', 'Employee', 'Fortnight start', 'Shift reference', 'Shift', 'Client ID', 'Client',
                         'Planned start', 'Planned end', 'Actual sign in', 'Actual sign out', 'Planned hours',
                         'Actual hours', 'Adjusted hours', 'Approved hours', 'Adjustment reason', 'Status'])

        def stamp(value):
            return format_datetime(self.env, value, tz=tz, dt_format='yyyy-MM-dd HH:mm') if value else ''

        for sheet in sheets:
            for line in sheet.line_ids.sorted('planned_start'):
                shift = line.shift_id
                writer.writerow([
                    sheet.employee_id.sudo().binaryaid_employee_code or '', sheet.employee_id.name, sheet.period_start,
                    'SHIFT-%s' % shift.id, shift.name, shift.client_id.reference or '', shift.client_id.name or '',
                    stamp(line.planned_start), stamp(line.planned_end), stamp(line.actual_check_in), stamp(line.actual_check_out),
                    '%.2f' % line.planned_hours, '%.2f' % line.actual_hours, '%.2f' % line.effective_hours,
                    '%.2f' % line.approved_hours, line.adjustment_reason or '', dict(line._fields['status'].selection)[line.status]])
        data = buffer.getvalue().encode('utf-8-sig')
        attachment = self.env['ir.attachment'].create({
            'name': 'approved-timesheets-%s.csv' % fields.Date.context_today(self),
            'raw': data, 'mimetype': 'text/csv', 'res_model': self._name, 'res_id': sheets[:1].id})
        sheets.message_post(body=_('Approved timesheet export generated by %s.', self.env.user.name))
        return {'type': 'ir.actions.act_url', 'url': '/web/content/%s?download=true' % attachment.id, 'target': 'self'}

    @api.model
    def _cron_generate(self):
        today = fields.Date.context_today(self)
        current = fortnight_start(self.env, today)
        for company in self.env['res.company'].search([]):
            env_self = self.with_company(company)
            env_self._generate(current - timedelta(days=14))
            env_self._generate(current)


class CareTimesheetLine(models.Model):
    _name = 'binaryaid.care.timesheet.line'
    _description = 'Fortnightly Timesheet Row'
    _order = 'planned_start, id'

    timesheet_id = fields.Many2one('binaryaid.care.timesheet', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='timesheet_id.company_id', store=True)
    employee_id = fields.Many2one(related='timesheet_id.employee_id', store=True)
    timesheet_state = fields.Selection(related='timesheet_id.state', store=True, string='Timesheet status')
    shift_id = fields.Many2one('binaryaid.work.shift', required=True, ondelete='restrict', index=True)
    client_id = fields.Many2one(related='shift_id.client_id', store=True)
    planned_start = fields.Datetime(related='shift_id.start', store=True)
    planned_end = fields.Datetime(related='shift_id.end', store=True)
    planned_hours = fields.Float(readonly=True, string='Planned')
    actual_check_in = fields.Datetime(readonly=True, string='Signed in')
    actual_check_out = fields.Datetime(readonly=True, string='Signed out')
    actual_hours = fields.Float(readonly=True, string='Actual', help='Signed-in duration from the original attendance, before any break deduction.')
    break_hours = fields.Float(readonly=True, string='Unpaid break')
    clock_event_count = fields.Integer(readonly=True, string='Clock events')
    note_submitted = fields.Boolean(readonly=True, string='Note')
    open_exception = fields.Boolean(readonly=True, string='Exception open')
    incomplete = fields.Boolean(readonly=True)
    issues = fields.Char(readonly=True)
    has_adjustment = fields.Boolean(readonly=True)
    adjusted_hours = fields.Float(readonly=True, string='Adjusted')
    adjustment_reason = fields.Text(readonly=True)
    adjusted_by_id = fields.Many2one('res.users', readonly=True)
    correction_state = fields.Selection([('none', 'None'), ('requested', 'Requested'), ('resolved', 'Resolved')],
                                        default='none', readonly=True, string='Correction')
    correction_note = fields.Text(readonly=True)
    status = fields.Selection([('complete', 'Complete'), ('incomplete', 'Incomplete'), ('unresolved', 'Unresolved')],
                              compute='_compute_hours', store=True)
    effective_hours = fields.Float(compute='_compute_hours', store=True, string='Adjusted / actual')
    approved_hours = fields.Float(compute='_compute_hours', store=True, string='Approved')

    @api.depends('incomplete', 'open_exception', 'correction_state', 'has_adjustment', 'adjusted_hours',
                 'actual_hours', 'break_hours')
    def _compute_hours(self):
        for line in self:
            if line.open_exception or line.correction_state == 'requested':
                line.status = 'unresolved'
            elif line.incomplete and not line.has_adjustment:
                line.status = 'incomplete'
            else:
                line.status = 'complete'
            line.effective_hours = line.adjusted_hours if line.has_adjustment else max(line.actual_hours - line.break_hours, 0.0)
            line.approved_hours = line.effective_hours if line.status == 'complete' else 0.0

    def _check_open(self):
        if self.timesheet_id.filtered(lambda s: s.state in ('approved', 'locked')):
            raise UserError(_('Reopen the timesheet before changing its rows.'))

    def write(self, vals):
        if not self.env.su:
            raise AccessError(_('Use the adjust and correction actions to change timesheet rows.'))
        return super().write(vals)

    def _adjust(self, hours, reason):
        check_admin(self.env)
        self._check_open()
        if hours < 0 or hours > 24:
            raise ValidationError(_('Adjusted hours must be between 0 and 24.'))
        if not (reason or '').strip():
            raise ValidationError(_('Give a reason for the adjustment.'))
        for line in self:
            line.sudo().write({'has_adjustment': True, 'adjusted_hours': hours, 'adjustment_reason': reason.strip(),
                               'adjusted_by_id': self.env.uid})
            line.timesheet_id.message_post(body=_('%(shift)s adjusted from %(old).2f to %(new).2f h: %(reason)s',
                                                  shift=line.shift_id.display_name, old=line.actual_hours, new=hours, reason=reason))

    def _clear_adjustment(self):
        check_admin(self.env)
        self._check_open()
        self.sudo().write({'has_adjustment': False, 'adjusted_hours': 0.0, 'adjustment_reason': False, 'adjusted_by_id': False})

    def _request_correction(self, note):
        self._check_open()
        for line in self:
            if not self.env.user.has_group('binaryaid_work_management.group_work_admin') and line.employee_id.user_id != self.env.user:
                raise AccessError(_('You can request corrections for your own timesheet only.'))
            if not (note or '').strip():
                raise ValidationError(_('Describe the correction needed.'))
            line.sudo().write({'correction_state': 'requested', 'correction_note': note.strip()})
            sheet = line.timesheet_id.sudo()
            sheet.message_post(body=_('Correction requested by %(user)s for %(shift)s: %(note)s',
                                      user=self.env.user.name, shift=line.shift_id.display_name, note=note))
            if line.employee_id.user_id and line.employee_id.user_id != self.env.user:
                sheet.message_notify(partner_ids=line.employee_id.user_id.partner_id.ids, subject=_('Timesheet correction'),
                                     body=_('Your coordinator asked for a correction to a shift in your timesheet.'))

    def action_resolve_correction(self):
        check_admin(self.env)
        self._check_open()
        self.sudo().write({'correction_state': 'resolved'})
        return True

    def action_adjust(self):
        self.ensure_one()
        check_admin(self.env)
        return {'type': 'ir.actions.act_window', 'name': _('Adjust hours'), 'res_model': 'binaryaid.care.timesheet.adjust',
                'view_mode': 'form', 'target': 'new', 'context': {'default_line_id': self.id, 'default_hours': self.effective_hours}}

    def action_request_correction(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Request correction'),
                'res_model': 'binaryaid.care.timesheet.correction', 'view_mode': 'form', 'target': 'new',
                'context': {'default_line_id': self.id}}

    def action_open_shift(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'binaryaid.work.shift', 'res_id': self.shift_id.id,
                'view_mode': 'form', 'target': 'new'}
