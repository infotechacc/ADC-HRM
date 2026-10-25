from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, HttpCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestDashboard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login='dashboard_manager', groups='binaryaid_work_management.group_work_admin')
        cls.alice = new_test_user(cls.env, login='dashboard_alice', groups='binaryaid_work_management.group_work_user')
        cls.bob = new_test_user(cls.env, login='dashboard_bob', groups='binaryaid_work_management.group_work_user')
        cls.staff = new_test_user(cls.env, login='dashboard_staff', groups='base.group_user')
        cls.portal = new_test_user(cls.env, login='dashboard_portal', groups='base.group_portal')
        cls.employee = cls.env['hr.employee'].create({'name': 'Dashboard Alice', 'user_id': cls.alice.id})
        cls.other_employee = cls.env['hr.employee'].create({'name': 'Dashboard Bob', 'user_id': cls.bob.id})
        cls.task = cls.env['project.task'].with_user(cls.manager).create({'name': 'Dashboard own task', 'binaryaid_employee_id': cls.employee.id})
        cls.other_task = cls.env['project.task'].with_user(cls.manager).create({'name': 'Dashboard other task', 'binaryaid_employee_id': cls.other_employee.id})
        cls.dashboard = cls.env['binaryaid.hrms.dashboard']

    def test_employee_summary_and_drilldowns(self):
        dashboard = self.dashboard.with_user(self.alice)
        self.task.with_user(self.alice).action_binaryaid_complete()
        data = dashboard.get_overview()
        cards = {card['key']: card['value'] for card in data['cards']}
        self.assertEqual(cards['work_today'], 1)
        self.assertEqual(cards['work_open'], 0)
        self.assertEqual(cards['work_done'], 1)
        self.assertEqual(data['completion_percent'], 100)
        self.assertEqual([row['id'] for row in data['recent_work']], self.task.ids)
        self.assertNotIn('employees', cards)
        self.assertTrue({'my_work', 'discuss', 'profile'}.issubset({link['key'] for link in data['shortcuts']}))
        self.assertFalse(data['admin'])
        self.assertFalse(data['attention'])
        for key in ('work_today', 'work_done'):
            action = dashboard.open_section(key)
            self.assertEqual(self.env['project.task'].with_user(self.alice).search(action['domain']), self.task.with_user(self.alice))
        self.assertEqual(dashboard.open_work(self.task.id)['res_id'], self.task.id)
        for key in ('employees', 'employee_work', 'history', 'invented'):
            with self.assertRaises(AccessError):
                dashboard.open_section(key)
        with self.assertRaises(AccessError):
            dashboard.open_work(self.other_task.id)
        with self.assertRaises(AccessError):
            dashboard.quick_action('add_employee')
        with self.assertRaises(AccessError):
            dashboard.item_action('document', self.employee.id, 'open')
        self.assertEqual(dashboard.open_section('profile')['res_model'], 'res.users')

    def test_manager_and_active_company(self):
        dashboard = self.dashboard.with_user(self.manager)
        data = dashboard.get_overview()
        self.assertTrue(data['manager'])
        self.assertTrue(data['admin'])
        self.assertIn('employees', {link['key'] for link in data['shortcuts']})
        self.assertEqual(dashboard.open_section('employees')['res_model'], 'hr.employee')
        self.assertTrue({'employee_work', 'history'}.issubset({link['key'] for link in data['shortcuts']}))
        self.assertEqual(dashboard.open_section('employee_work')['res_model'], 'binaryaid.work.employee')
        self.assertEqual(dashboard.open_section('history')['res_model'], 'binaryaid.work.log')
        company = self.env['res.company'].create({'name': 'Dashboard other company'})
        self.manager.company_ids = [Command.link(company.id)]
        other = dashboard.with_company(company).get_overview()
        self.assertFalse(other['recent_work'])
        self.assertEqual(other['month_total'], 0)
        with self.assertRaises(AccessError):
            dashboard.with_company(company).open_work(self.task.id)

    def test_no_work_role_and_portal(self):
        dashboard = self.dashboard.with_user(self.staff)
        data = dashboard.get_overview()
        self.assertFalse(data['can_work'])
        self.assertFalse(data['recent_work'])
        self.assertNotIn('work_today', {card['key'] for card in data['cards']})
        self.assertEqual(dashboard.open_section('discuss')['tag'], 'mail.action_discuss')
        with self.assertRaises(AccessError):
            dashboard.open_work(self.task.id)
        with self.assertRaises(AccessError):
            self.dashboard.with_user(self.portal).get_overview()
        with self.assertRaises(AccessError):
            self.dashboard.with_user(self.portal).open_section('discuss')

    def test_backdated_month(self):
        previous_month = fields.Date.subtract(fields.Date.start_of(fields.Date.context_today(self.task), 'month'), days=1)
        task = self.env['project.task'].with_user(self.manager).create({
            'name': 'Last month work', 'binaryaid_employee_id': self.employee.id, 'binaryaid_work_date': previous_month})
        task.with_user(self.alice).action_binaryaid_complete()
        data = self.dashboard.with_user(self.alice).get_overview()
        self.assertEqual(data['month_total'], 1)
        self.assertEqual(data['month_done'], 0)


@tagged('post_install', '-at_install')
class TestDashboardLanding(HttpCase):
    def test_internal_home_action(self):
        user = new_test_user(self.env, login='dashboard_login', password='dashboard_login', groups='base.group_user')
        user.action_id = self.env.ref('mail.action_discuss').id
        self.authenticate(user.login, 'dashboard_login')
        result = self.url_open('/web/session/get_session_info', data='{"jsonrpc":"2.0","method":"call","params":{},"id":1}', headers={'Content-Type': 'application/json'}).json()
        self.assertEqual(result['result']['home_action_id'], self.env.ref('binaryaid_hrms_dashboard.action_dashboard').id)
        self.assertEqual(user.action_id.id, self.env.ref('mail.action_discuss').id)
