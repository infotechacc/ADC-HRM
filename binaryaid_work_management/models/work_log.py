from odoo import api, fields, models, _
from odoo.exceptions import AccessError


class WorkLog(models.Model):
    _name = 'binaryaid.work.log'
    _description = 'Employee Daily Work History'
    _order = 'work_date desc, id desc'
    _rec_name = 'note'
    _check_company_auto = True

    task_id = fields.Many2one('project.task', required=True, index=True, ondelete='restrict', check_company=True)
    employee_id = fields.Many2one('hr.employee', required=True, index=True, ondelete='restrict', check_company=True)
    user_id = fields.Many2one('res.users', required=True, index=True, ondelete='restrict')
    company_id = fields.Many2one('res.company', required=True, index=True)
    author_id = fields.Many2one('res.users', required=True, ondelete='restrict', string='Recorded By')
    work_date = fields.Date(required=True, index=True)
    event = fields.Selection([('assigned', 'Assigned'), ('note', 'Work Note'),
                              ('completed', 'Completed'), ('reopened', 'Reopened')], required=True, index=True)
    note = fields.Text(required=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise AccessError(_('Use Add Daily Work Note or the task completion action to record history.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('Work history is immutable. Add a new note to record a correction.'))

    def unlink(self):
        raise AccessError(_('Work history cannot be deleted.'))
