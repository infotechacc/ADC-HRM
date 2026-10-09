from odoo import api, fields, models, tools, _
from odoo.exceptions import UserError


class WorkEmployee(models.Model):
    _name = 'binaryaid.work.employee'
    _description = 'Work Management Employee'
    _auto = False
    _order = 'name, id'

    name = fields.Char(readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    user_id = fields.Many2one('res.users', readonly=True)
    active = fields.Boolean(readonly=True)

    @api.model
    def action_my_work(self):
        employee = self.search([
            ('user_id', '=', self.env.uid), ('company_id', '=', self.env.company.id)], limit=1)
        if not employee:
            raise UserError(_('Your user account must be linked to an active employee in the selected company.'))
        action = employee.action_open_work()
        action.update(name=_('My Work History'), display_name=_('My Work History'))
        return action

    def init(self):
        # Read-only projection of existing employees: no duplicate employee records.
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute('''
            CREATE VIEW binaryaid_work_employee AS
            SELECT id, name, company_id, user_id, active FROM hr_employee
        ''')

    def action_open_work(self):
        self.ensure_one()
        self.check_access('read')
        action = self.env['ir.actions.actions']._for_xml_id('binaryaid_work_management.action_work_items')
        action.update(
            name=_('%s — Daily Work', self.name),
            display_name=_('%s — Daily Work', self.name),
            domain=[('binaryaid_employee_id', '=', self.id)],
            context={'default_binaryaid_employee_id': self.id,
                     'group_by': ['binaryaid_work_date:day']})
        return action
