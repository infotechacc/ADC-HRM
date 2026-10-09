from odoo import api, fields, models, Command, _
from odoo.exceptions import AccessError, ValidationError


class ProjectTask(models.Model):
    _inherit = 'project.task'

    binaryaid_employee_id = fields.Many2one(
        'hr.employee', string='Assigned Employee', index=True, copy=False,
        check_company=True, ondelete='restrict')
    binaryaid_work_log_ids = fields.One2many('binaryaid.work.log', 'task_id', string='Daily Work History')
    binaryaid_is_admin = fields.Boolean(compute='_compute_binaryaid_is_admin')
    binaryaid_work_date = fields.Date(
        string='Work Date', default=fields.Date.context_today, index=True, copy=False)
    binaryaid_latest_note = fields.Text(string='Latest Work Note', compute='_compute_binaryaid_latest_note')

    @api.depends('binaryaid_work_log_ids')
    def _compute_binaryaid_latest_note(self):
        grouped = self.env['binaryaid.work.log']._read_group(
            [('task_id', 'in', self.ids), ('event', '=', 'note')], ['task_id'], ['id:max'])
        notes = self.env['binaryaid.work.log'].browse([log_id for task, log_id in grouped])
        by_task = {note.task_id.id: note.note for note in notes}
        for task in self:
            task.binaryaid_latest_note = by_task.get(task.id, False)

    @api.depends_context('uid')
    def _compute_binaryaid_is_admin(self):
        for task in self:
            task.binaryaid_is_admin = self._binaryaid_admin()

    def _binaryaid_admin(self):
        return self.env.su or self.env.user.has_group('binaryaid_work_management.group_work_admin')

    @api.constrains('binaryaid_employee_id', 'company_id', 'project_id', 'parent_id')
    def _check_binaryaid_assignment(self):
        for task in self.filtered('binaryaid_employee_id'):
            employee = task.binaryaid_employee_id
            user = employee.user_id
            if not employee.active or not user or not user.active or user.share:
                raise ValidationError(_('Assign work to an active employee linked to an active internal user.'))
            if not user.has_group('binaryaid_work_management.group_work_user'):
                raise ValidationError(_('Enable the Work Management User role on the employee’s user account first.'))
            if task.company_id != employee.company_id or task.company_id not in user.company_ids:
                raise ValidationError(_('The task and employee must belong to the same company, accessible to the employee’s user.'))
            if task.project_id or task.parent_id:
                raise ValidationError(_('Employee work items are standalone tasks; project and parent tasks must be empty.'))

    @api.model_create_multi
    def create(self, vals_list):
        defaults = self.default_get(['binaryaid_employee_id'])
        prepared = []
        for incoming in vals_list:
            vals = dict(incoming)
            employee_id = vals.get('binaryaid_employee_id', defaults.get('binaryaid_employee_id'))
            if employee_id:
                vals.setdefault('binaryaid_work_date', self.env.context.get('default_binaryaid_work_date') or fields.Date.context_today(self))
                if not vals['binaryaid_work_date']:
                    raise ValidationError(_('Select a Work Date.'))
                if self._binaryaid_admin():
                    employee = self.env['hr.employee'].browse(employee_id)
                    employee.check_access('read')
                else:
                    # Resolve ownership before reading private employee data. Do not grant HR access.
                    employee = self.env['hr.employee'].sudo().search([
                        ('id', '=', employee_id), ('user_id', '=', self.env.uid),
                        ('company_id', 'in', self.env.companies.ids)], limit=1)
                    if not employee:
                        raise AccessError(_('Employees may only add work for themselves.'))
                vals.update(binaryaid_employee_id=employee.id, company_id=employee.company_id.id,
                            user_ids=[Command.set(employee.user_id.ids)], project_id=False, parent_id=False)
                if vals.get('state', '01_in_progress') != '01_in_progress':
                    raise ValidationError(_('New work must start In Progress.'))
            prepared.append(vals)
        tasks = super().create(prepared)
        for task in tasks.filtered('binaryaid_employee_id'):
            # Native private tasks add their creator as an assignee. HR work has one employee.
            super(ProjectTask, task).write({'user_ids': [Command.set(task.binaryaid_employee_id.user_id.ids)]})
            task._binaryaid_log('assigned', _('Work assigned'))
        return tasks

    def write(self, vals):
        self.check_access('write')
        work = self.filtered('binaryaid_employee_id')
        if work and 'state' in vals:
            work.lock_for_update()
            work.invalidate_recordset(['state'])
        if 'binaryaid_employee_id' in vals:
            if not self._binaryaid_admin():
                raise AccessError(_('Only Work Management administrators can assign work.'))
            if work:
                raise ValidationError(_('Keep the original assignment for reliable history. Archive it and create a new assignment instead.'))
            if vals['binaryaid_employee_id']:
                raise ValidationError(_('Create employee assignments from Work Management rather than converting existing tasks.'))
        if work:
            if 'binaryaid_work_date' in vals:
                raise AccessError(_('Choose the Work Date before saving. Saved work dates cannot be changed.'))
            if not self._binaryaid_admin():
                if set(vals) - {'description', 'state'}:
                    raise AccessError(_('Employees may update descriptions, add daily notes, and complete their assigned work.'))
                if any(task.state == '1_done' for task in work):
                    raise AccessError(_('Completed work can only be reopened by a Work Management administrator.'))
                if 'state' in vals and vals['state'] != '1_done':
                    raise AccessError(_('Employees may only mark work as completed.'))
            if set(vals) & {'user_ids', 'company_id', 'project_id', 'parent_id', 'child_ids', 'recurring_task', 'repeat_interval', 'is_template'}:
                raise ValidationError(_('The employee assignment and standalone task structure cannot be changed.'))
            if 'state' in vals and vals['state'] not in ('01_in_progress', '1_done'):
                raise ValidationError(_('Work items support In Progress and Done.'))
        changed = work.filtered(lambda task: 'state' in vals and task.state != vals['state'])
        result = super().write(vals)
        for task in changed:
            task._binaryaid_log('completed' if task.state == '1_done' else 'reopened',
                               _('Work completed') if task.state == '1_done' else _('Work reopened'))
        return result

    def unlink(self):
        if self.filtered('binaryaid_employee_id'):
            raise AccessError(_('Archive work items instead of deleting their history.'))
        return super().unlink()

    def _binaryaid_log(self, event, note, work_date=None):
        self.ensure_one()
        self.check_access('write')
        if not self.binaryaid_employee_id:
            raise ValidationError(_('Select an employee work item.'))
        # Private method: callers cannot forge completion events through RPC.
        # Elevation is limited to creating immutable history after task authorization.
        return self.env['binaryaid.work.log'].sudo().create({
            'task_id': self.id, 'employee_id': self.binaryaid_employee_id.id,
            'user_id': self.binaryaid_employee_id.user_id.id, 'company_id': self.company_id.id,
            'author_id': self.env.uid, 'work_date': work_date or self.binaryaid_work_date,
            'event': event, 'note': note,
        })

    def action_binaryaid_complete(self):
        if any(not task.binaryaid_employee_id for task in self):
            raise ValidationError(_('Select employee work items.'))
        self.write({'state': '1_done'})

    def action_binaryaid_reopen(self):
        if not self._binaryaid_admin():
            raise AccessError(_('Only Work Management administrators can reopen work.'))
        self.write({'state': '01_in_progress'})

    def action_binaryaid_update(self):
        self.ensure_one()
        self.check_access('write')
        return {'type': 'ir.actions.act_window', 'name': _('Add Daily Work Note'),
                'res_model': 'binaryaid.work.update', 'view_mode': 'form', 'target': 'new',
                'context': {'default_task_id': self.id, 'default_work_date': self.binaryaid_work_date}}
