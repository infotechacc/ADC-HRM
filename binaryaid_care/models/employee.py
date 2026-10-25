from odoo import api, fields, models, _


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    binaryaid_employee_code = fields.Char(string='Employee ID', groups='hr.group_hr_user', tracking=True, copy=False)
    binaryaid_employment_type = fields.Selection(
        [('full_time', 'Full time'), ('part_time', 'Part time'), ('casual', 'Casual'), ('contractor', 'Contractor')],
        string='Employment type', groups='hr.group_hr_user', tracking=True)
    binaryaid_employment_status = fields.Selection(
        [('active', 'Active'), ('onboarding', 'Onboarding'), ('suspended', 'Suspended'), ('ended', 'Employment ended')],
        string='Employment status', default='active', groups='hr.group_hr_user', tracking=True)
    binaryaid_document_ids = fields.One2many('binaryaid.care.document', 'employee_id', string='Worker documents',
                                             groups='hr.group_hr_user')
    binaryaid_document_issue_count = fields.Integer(compute='_compute_binaryaid_document_issues',
                                                    groups='hr.group_hr_user', string='Document issues')
    binaryaid_client_shift_ids = fields.One2many('binaryaid.work.shift', 'employee_id', string='Client assignments',
                                                 domain=[('client_id', '!=', False)], groups='hr.group_hr_user')

    _binaryaid_code_unique = models.UniqueIndex('(company_id, binaryaid_employee_code) WHERE binaryaid_employee_code IS NOT NULL')

    def _compute_binaryaid_document_issues(self):
        required = self.env['binaryaid.care.document.category'].search([('applies_to', '=', 'employee'), ('required', '=', True)])
        for employee in self:
            valid = employee.binaryaid_document_ids.filtered(lambda d: d.expiry_state in ('valid', 'expiring')).category_id
            expiring = employee.binaryaid_document_ids.filtered(lambda d: d.expiry_state in ('expiring', 'expired'))
            employee.binaryaid_document_issue_count = len(required - valid) + len(expiring)

    def action_binaryaid_prepare_documents(self):
        categories = self.env['binaryaid.care.document.category'].search([('applies_to', '=', 'employee')])
        for employee in self:
            missing = categories - employee.sudo().binaryaid_document_ids.category_id
            self.env['binaryaid.care.document'].create([
                {'employee_id': employee.id, 'category_id': category.id, 'company_id': employee.company_id.id}
                for category in missing])
        return True

    def action_binaryaid_documents(self):
        self.ensure_one()
        self.action_binaryaid_prepare_documents()
        return {'type': 'ir.actions.act_window', 'name': _('Documents of %s', self.name),
                'res_model': 'binaryaid.care.document', 'view_mode': 'list,form',
                'domain': [('employee_id', '=', self.id)], 'context': {'default_employee_id': self.id}}

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        if self.env.user.has_group('hr.group_hr_user'):
            employees.action_binaryaid_prepare_documents()
        return employees

    def write(self, vals):
        result = super().write(vals)
        if vals.get('active') is False or vals.get('binaryaid_employment_status') == 'ended':
            # Deactivated employees immediately lose access. Staff accounts with HR or roster
            # administration rights are left to an administrator to avoid locking out managers.
            users = self.user_id.filtered(lambda u: u.active and not u.has_group('hr.group_hr_user'))
            users.sudo().write({'active': False})
        return result

