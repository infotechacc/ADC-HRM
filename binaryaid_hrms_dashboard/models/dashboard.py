from odoo import api, fields, models, _
from odoo.exceptions import AccessError
from odoo.tools import format_date


class HrmsDashboard(models.AbstractModel):
    _name = 'binaryaid.hrms.dashboard'
    _description = 'HRMS Dashboard'

    def _check_user(self):
        if not self.env.user.has_group('base.group_user'):
            raise AccessError(_('The HRMS Dashboard is available to internal users only.'))

    def _can_read(self, model):
        return model in self.env and self.env[model].has_access('read')

    def _work_domain(self):
        domain = [('binaryaid_employee_id', '!=', False), ('company_id', '=', self.env.company.id)]
        if not self.env.user.has_group('binaryaid_work_management.group_work_admin'):
            domain.append(('binaryaid_employee_id.user_id', '=', self.env.uid))
        return domain

    def _specifications(self):
        """Server-owned drilldown definitions; both counts and actions share the domains."""
        self._check_user()
        company = self.env.company.id
        today = fields.Date.context_today(self)
        month = fields.Date.start_of(today, 'month')
        next_month = fields.Date.add(month, months=1)
        specs = {}
        if self.env.user.has_group('binaryaid_work_management.group_work_user'):
            domain = self._work_domain()
            specs.update({
                'work_today': ('project.task', _('Work for today'), domain + [('binaryaid_work_date', '=', today)], 'fa-calendar-check-o', 'purple', _('Scheduled for your local date')),
                'work_open': ('project.task', _('Open work'), domain + [('state', '!=', '1_done')], 'fa-tasks', 'amber', _('Across all work dates')),
                'work_done': ('project.task', _('Completed this month'), domain + [('state', '=', '1_done'), ('binaryaid_work_date', '>=', month), ('binaryaid_work_date', '<', next_month)], 'fa-check-circle-o', 'teal', _('Based on Work Date')),
            })
        if self.env.user.has_group('hr.group_hr_user'):
            specs['employees'] = ('hr.employee', _('Active employees'), [('company_id', '=', company)], 'fa-users', 'blue', _('In the active company'))
        if self._can_read('hr.attendance'):
            specs['attendance'] = ('hr.attendance', _('Currently checked in'), [('employee_id.company_id', '=', company), ('check_out', '=', False)], 'fa-clock-o', 'blue', _('Attendance records you can access'))
        if self._can_read('hr.leave'):
            specs['leave'] = ('hr.leave', _('Time off awaiting approval'), [('company_id', '=', company), ('state', 'in', ['confirm', 'validate1'])], 'fa-calendar-minus-o', 'amber', _('Requests visible to your role'))
        if self._can_read('hr.applicant'):
            specs['recruitment'] = ('hr.applicant', _('Open applications'), [('company_id', '=', company), ('date_closed', '=', False), ('job_id', '!=', False)], 'fa-user-plus', 'purple', _('Active recruitment applications'))
        return specs

    @api.model
    @api.readonly
    def get_overview(self):
        specs = self._specifications()
        user = self.env.user
        today = fields.Date.context_today(self)
        can_work = user.has_group('binaryaid_work_management.group_work_user')
        manager = user.has_group('binaryaid_work_management.group_work_admin')
        data = {
            'user_name': user.name, 'company_name': self.env.company.name,
            'today_label': format_date(self.env, today, date_format='EEEE, d MMMM y'),
            'month_label': format_date(self.env, today, date_format='MMMM y'),
            'manager': manager, 'can_work': can_work, 'has_employee': False,
            'cards': [], 'recent_work': [],
            'month_total': 0, 'month_done': 0, 'completion_percent': 0,
            'shortcuts': [{'key': 'discuss', 'label': _('Discuss'), 'icon': 'fa-comments-o'}],
        }
        for key, (model, label, domain, icon, color, hint) in specs.items():
            data['cards'].append({'key': key, 'label': label, 'value': self.env[model].search_count(domain),
                                  'icon': icon, 'color': color, 'hint': hint})
        if not can_work:
            return data
        data['has_employee'] = bool(self.env['binaryaid.work.employee'].search_count([
            ('user_id', '=', user.id), ('company_id', '=', self.env.company.id)], limit=1))
        if data['has_employee']:
            data['shortcuts'].insert(0, {'key': 'my_work', 'label': _('My Work History'), 'icon': 'fa-list-alt'})
        if manager:
            data['shortcuts'].insert(0, {'key': 'employee_work', 'label': _('Employee Work'), 'icon': 'fa-users'})
            data['shortcuts'].insert(1, {'key': 'history', 'label': _('Daily Work History'), 'icon': 'fa-history'})
        domain = self._work_domain()
        month = fields.Date.start_of(today, 'month')
        groups = self.env['project.task']._read_group(
            domain + [('binaryaid_work_date', '>=', month), ('binaryaid_work_date', '<', fields.Date.add(month, months=1))],
            ['state'], ['__count'])
        data['month_total'] = sum(count for state, count in groups)
        data['month_done'] = sum(count for state, count in groups if state == '1_done')
        if data['month_total']:
            data['completion_percent'] = round(100 * data['month_done'] / data['month_total'])
        tasks = self.env['project.task'].search(domain, order='binaryaid_work_date desc, id desc', limit=6)
        for task in tasks:
            data['recent_work'].append({
                'id': task.id, 'name': task.name, 'employee': task.binaryaid_employee_id.name if manager else '',
                'date': format_date(self.env, task.binaryaid_work_date), 'done': task.state == '1_done',
                'status': _('Completed') if task.state == '1_done' else _('In progress'),
            })
        return data

    @api.model
    @api.readonly
    def open_section(self, key):
        specs = self._specifications()
        user = self.env.user
        if key == 'discuss':
            return self.env['ir.actions.actions']._for_xml_id('mail.action_discuss')
        if key == 'my_work' and user.has_group('binaryaid_work_management.group_work_user'):
            return self.env['binaryaid.work.employee'].action_my_work()
        if key in ('employee_work', 'history') and user.has_group('binaryaid_work_management.group_work_admin'):
            xmlid = 'action_work_employees' if key == 'employee_work' else 'action_work_history'
            return self.env['ir.actions.actions']._for_xml_id('binaryaid_work_management.' + xmlid)
        if key not in specs:
            raise AccessError(_('You do not have access to this dashboard section.'))
        model, label, domain = specs[key][:3]
        if model == 'project.task':
            action = self.env['ir.actions.actions']._for_xml_id('binaryaid_work_management.action_work_items')
            context = {'group_by': ['binaryaid_work_date:day']}
            own_employee = self.env['binaryaid.work.employee'].search([
                ('user_id', '=', user.id), ('company_id', '=', self.env.company.id)], limit=1)
            if own_employee:
                context['default_binaryaid_employee_id'] = own_employee.id
            action.update(name=label, display_name=label, domain=domain, context=context)
            return action
        return {'type': 'ir.actions.act_window', 'name': label, 'res_model': model,
                'view_mode': 'list,form', 'views': [(False, 'list'), (False, 'form')], 'domain': domain}

    @api.model
    @api.readonly
    def open_work(self, task_id):
        self._check_user()
        if not self.env.user.has_group('binaryaid_work_management.group_work_user'):
            raise AccessError(_('You do not have access to Work Management.'))
        task = self.env['project.task'].search(self._work_domain() + [('id', '=', task_id)], limit=1)
        if not task:
            raise AccessError(_('This work item is not available to you.'))
        return {'type': 'ir.actions.act_window', 'name': task.name, 'res_model': 'project.task',
                'res_id': task.id, 'views': [(self.env.ref('binaryaid_work_management.view_work_form').id, 'form')]}
