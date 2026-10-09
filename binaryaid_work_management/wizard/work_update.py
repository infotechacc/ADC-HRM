from odoo import fields, models, _
from odoo.exceptions import ValidationError


class WorkUpdate(models.TransientModel):
    _name = 'binaryaid.work.update'
    _description = 'Add Daily Work Note'

    task_id = fields.Many2one('project.task', required=True, readonly=True)
    work_date = fields.Date(required=True, default=fields.Date.context_today)
    note = fields.Text(required=True, string='Work Details')

    def action_submit(self):
        self.ensure_one()
        self.check_access('write')
        task = self.task_id
        task.check_access('write')
        if not task.binaryaid_employee_id or not self.note or not self.note.strip():
            raise ValidationError(_('Select an employee work item and enter work details.'))
        if self.work_date > fields.Date.context_today(self):
            raise ValidationError(_('Daily work notes cannot be dated in the future.'))
        if self.work_date < task.binaryaid_work_date:
            raise ValidationError(_('The note date cannot be before the task’s Work Date.'))
        task._binaryaid_log('note', self.note.strip(), self.work_date)
        return {'type': 'ir.actions.act_window_close'}
