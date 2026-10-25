from odoo import api, fields, models, _
from odoo.exceptions import AccessError
from odoo.tools import format_date

ATTENTION_LIMIT = 8


class HrmsDashboard(models.AbstractModel):
    _name = 'binaryaid.hrms.dashboard'
    _description = 'HRMS Dashboard'

    def _check_user(self):
        if not self.env.user.has_group('base.group_user'):
            raise AccessError(_('The HRMS Dashboard is available to internal users only.'))

    def _can_read(self, model):
        return model in self.env and self.env[model].has_access('read')

    def _is_admin(self):
        """Administration view: roster managers and HR officers."""
        user = self.env.user
        return (user.has_group('binaryaid_work_management.group_work_admin')
                or user.has_group('hr.group_hr_user'))

    def _can_approve_leave(self):
        return 'hr.leave' in self.env and self.env.user.has_group('hr_holidays.group_hr_holidays_user')

    def _work_domain(self):
        domain = [('binaryaid_employee_id', '!=', False), ('company_id', '=', self.env.company.id)]
        if not self.env.user.has_group('binaryaid_work_management.group_work_admin'):
            domain.append(('binaryaid_employee_id.user_id', '=', self.env.uid))
        return domain

    def _document_alert_domain(self):
        """Native identity documents expiring inside the company notice period, or already expired."""
        limit = fields.Date.add(fields.Date.context_today(self),
                                days=self.env.company.work_permit_expiration_notice_period or 60)
        return [('company_id', '=', self.env.company.id), '|',
                ('work_permit_expiration_date', '<=', limit), ('visa_expire', '<=', limit)]

    def _leave_domain(self):
        return [('company_id', '=', self.env.company.id), ('state', 'in', ['confirm', 'validate1'])]

    def _specifications(self):
        """Server-owned drilldown definitions; counts, attention lists and actions share the domains.

        Values: (model, label, domain, icon, tone, hint). Extensions add their own keys.
        """
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
            specs['documents'] = ('hr.employee', _('Document alerts'), self._document_alert_domain(), 'fa-id-card-o', 'red', _('Visa or work permit expiring'))
        if self._can_read('hr.attendance'):
            specs['attendance'] = ('hr.attendance', _('Working now'), [('employee_id.company_id', '=', company), ('check_out', '=', False)], 'fa-clock-o', 'green', _('Currently signed in'))
        if self._can_read('hr.leave'):
            if self._can_approve_leave():
                specs['leave'] = ('hr.leave', _('Leave to review'), self._leave_domain(), 'fa-calendar-minus-o', 'amber', _('Awaiting a decision'))
            else:
                specs['leave'] = ('hr.leave', _('My pending leave'), self._leave_domain() + [('employee_id.user_id', '=', self.env.uid)], 'fa-calendar-minus-o', 'amber', _('Awaiting approval'))
        if self._can_read('hr.applicant'):
            specs['recruitment'] = ('hr.applicant', _('Open applications'), [('company_id', '=', company), ('date_closed', '=', False), ('job_id', '!=', False)], 'fa-user-plus', 'purple', _('Active recruitment applications'))
        return specs

    def _card_keys(self, admin):
        """Metrics shown, in order. Other specifications remain reachable as drilldowns."""
        if admin:
            return ['shifts_today', 'attendance', 'unpublished', 'missing_signout', 'leave',
                    'timesheets', 'documents', 'recruitment']
        return ['work_today', 'work_open', 'work_done', 'leave']

    # ------------------------------------------------------------------
    # Attention inbox: bounded lists of records that need a decision.
    # Each item exposes only named actions that item_action() re-validates.
    # ------------------------------------------------------------------
    def _attention_tabs(self, specs):
        tabs = []
        if 'leave' in specs and self._can_approve_leave():
            tabs.append(self._leave_tab(specs['leave'][2]))
        if 'documents' in specs:
            tabs.append(self._document_tab(specs['documents'][2]))
        return tabs

    def _leave_tab(self, domain):
        leaves = self.env['hr.leave'].search(domain, order='date_from, id', limit=ATTENTION_LIMIT)
        items = []
        for leave in leaves:
            actions = []
            if leave.can_approve or leave.can_validate:
                actions.append({'name': 'approve', 'label': _('Approve'), 'style': 'success'})
            if leave.can_refuse:
                actions.append({'name': 'refuse', 'label': _('Refuse'), 'style': 'danger'})
            actions.append({'name': 'open', 'label': _('Review'), 'style': 'link'})
            items.append({
                'source': 'leave', 'id': leave.id, 'title': leave.employee_id.name,
                'subtitle': leave.holiday_status_id.name,
                'meta': '%s – %s · %s' % (format_date(self.env, leave.request_date_from, date_format='d MMM'),
                                          format_date(self.env, leave.request_date_to, date_format='d MMM'),
                                          leave.duration_display),
                'tone': 'amber', 'warning': '', 'actions': actions,
            })
        return {'key': 'leave', 'label': _('Leave'), 'icon': 'fa-calendar-minus-o',
                'count': self.env['hr.leave'].search_count(domain), 'items': items,
                'empty': _('No leave requests are waiting for you.')}

    def _document_tab(self, domain):
        today = fields.Date.context_today(self)
        employees = self.env['hr.employee'].search(domain, limit=ATTENTION_LIMIT)
        items = []
        for employee in employees:
            dates = [(label, date) for label, date in ((_('Work permit'), employee.work_permit_expiration_date),
                                                      (_('Visa'), employee.visa_expire)) if date]
            label, date = min(dates, key=lambda pair: pair[1])
            expired = date < today
            items.append({
                'source': 'document', 'id': employee.id, 'title': employee.name,
                'subtitle': label,
                'meta': (_('Expired %s') if expired else _('Expires %s')) % format_date(self.env, date),
                'tone': 'red' if expired else 'amber', 'warning': '',
                'actions': [{'name': 'open', 'label': _('Open profile'), 'style': 'link'}],
            })
        return {'key': 'documents', 'label': _('Documents'), 'icon': 'fa-id-card-o',
                'count': self.env['hr.employee'].search_count(domain), 'items': items,
                'empty': _('No visa or work permit expiries in the notice period.')}

    def _quick_actions(self, admin):
        """Create/review shortcuts that open as dialogs over the dashboard."""
        actions = []
        if admin and self.env.user.has_group('hr.group_hr_user'):
            actions.append({'key': 'add_employee', 'label': _('Add employee'), 'icon': 'fa-user-plus'})
        if not admin and 'hr.leave' in self.env and self.env.user.employee_id:
            actions.append({'key': 'request_leave', 'label': _('Request leave'), 'icon': 'fa-calendar-plus-o'})
        return actions

    @api.model
    @api.readonly
    def get_overview(self):
        specs = self._specifications()
        user = self.env.user
        today = fields.Date.context_today(self)
        can_work = user.has_group('binaryaid_work_management.group_work_user')
        manager = user.has_group('binaryaid_work_management.group_work_admin')
        admin = self._is_admin()
        hour = fields.Datetime.context_timestamp(self, fields.Datetime.now()).hour
        data = {
            'user_name': user.name, 'company_name': self.env.company.name,
            'greeting': _('Good morning') if hour < 12 else _('Good afternoon') if hour < 18 else _('Good evening'),
            'today_label': format_date(self.env, today, date_format='EEEE, d MMMM y'),
            'month_label': format_date(self.env, today, date_format='MMMM y'),
            'manager': manager, 'admin': admin, 'can_work': can_work, 'has_employee': False,
            'cards': [], 'recent_work': [], 'attention': [],
            'quick_actions': self._quick_actions(admin),
            'month_total': 0, 'month_done': 0, 'completion_percent': 0,
            'shortcuts': [{'key': 'discuss', 'label': _('Team messages'), 'icon': 'fa-comments-o'}],
        }
        for key in [key for key in self._card_keys(admin) if key in specs]:
            model, label, domain, icon, tone, hint = specs[key]
            data['cards'].append({'key': key, 'label': label, 'value': self.env[model].search_count(domain),
                                  'icon': icon, 'color': tone, 'hint': hint})
        if admin:
            data['attention'] = self._attention_tabs(specs)
        if 'hr.leave' in self.env and user.employee_id and not admin:
            data['shortcuts'].append({'key': 'my_leave', 'label': _('My leave'), 'icon': 'fa-calendar-minus-o'})
        if admin and 'employees' in specs:
            data['shortcuts'].append({'key': 'employees', 'label': _('Employees'), 'icon': 'fa-users'})
        data['shortcuts'].append({'key': 'profile', 'label': _('My profile'), 'icon': 'fa-user-circle-o'})
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
        if key == 'profile':
            return self.env['res.users'].browse(self.env.uid).action_get()
        if key == 'my_leave' and 'hr.leave' in self.env:
            return self.env['ir.actions.actions']._for_xml_id('hr_holidays.hr_leave_action_new_request')
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
    def quick_action(self, key, date=None):
        """Dialog actions for creation shortcuts; rights are enforced again when saving."""
        self._check_user()
        if key == 'add_employee' and self.env.user.has_group('hr.group_hr_user'):
            return {'type': 'ir.actions.act_window', 'name': _('New employee'), 'res_model': 'hr.employee',
                    'views': [(False, 'form')], 'target': 'new', 'context': {'default_company_id': self.env.company.id}}
        if key == 'request_leave' and 'hr.leave' in self.env and self.env.user.employee_id:
            return {'type': 'ir.actions.act_window', 'name': _('Request leave'), 'res_model': 'hr.leave',
                    'views': [(False, 'form')], 'target': 'new',
                    'context': {'default_employee_id': self.env.user.employee_id.id}}
        raise AccessError(_('This dashboard action is not available to you.'))

    def _dialog(self, record, name=None, view=False):
        return {'type': 'ir.actions.act_window', 'name': name or record.display_name, 'res_model': record._name,
                'res_id': record.id, 'views': [(view, 'form')], 'target': 'new'}

    def _attention_record(self, source, res_id):
        """Re-find an inbox record through the same server-owned domain that listed it."""
        specs = self._specifications()
        key = {'leave': 'leave', 'document': 'documents'}.get(source)
        if key not in specs or (source == 'leave' and not self._can_approve_leave()):
            raise AccessError(_('This item is not available on your dashboard.'))
        model, label, domain = specs[key][:3]
        record = self.env[model].search(domain + [('id', '=', res_id)], limit=1)
        if not record:
            raise AccessError(_('This item is no longer waiting on your dashboard. Refresh to update it.'))
        return record

    @api.model
    def item_action(self, source, res_id, name):
        """Run an inline inbox action. Returns an action to open, or True after a direct change."""
        self._check_user()
        record = self._attention_record(source, res_id)
        if name == 'open':
            return self._dialog(record)
        if source == 'leave' and name == 'approve':
            record.action_approve()
            return True
        if source == 'leave' and name == 'refuse':
            record.action_refuse()
            return True
        raise AccessError(_('This action is not available for this item.'))

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
