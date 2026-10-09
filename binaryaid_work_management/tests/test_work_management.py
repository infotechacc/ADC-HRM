from odoo import Command, fields
from odoo.tests import TransactionCase, tagged, new_test_user, Form
from odoo.exceptions import AccessError, ValidationError


@tagged('post_install', '-at_install')
class TestWorkManagement(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = new_test_user(cls.env, login='test_work_admin', groups='binaryaid_work_management.group_work_admin')
        cls.alice = new_test_user(cls.env, login='test_work_alice', groups='binaryaid_work_management.group_work_user')
        cls.bob = new_test_user(cls.env, login='test_work_bob', groups='binaryaid_work_management.group_work_user,project.group_project_manager')
        cls.employee = cls.env['hr.employee'].create({'name': 'Work Test Alice', 'user_id': cls.alice.id, 'company_id': cls.env.company.id})
        cls.bob_employee = cls.env['hr.employee'].create({'name': 'Work Test Bob', 'user_id': cls.bob.id, 'company_id': cls.env.company.id})
        cls.task = cls.env['project.task'].with_user(cls.admin).create({'name': 'Test Assignment', 'binaryaid_employee_id': cls.employee.id})

    def test_assignment_and_isolation(self):
        self.assertEqual(self.task.user_ids, self.alice)
        self.assertIn(self.task.id, self.env['project.task'].with_user(self.alice).search([]).ids)
        self.assertNotIn(self.task.id, self.env['project.task'].with_user(self.bob).search([]).ids)
        with self.assertRaises(AccessError):
            self.task.with_user(self.bob).read(['name'])
        report = self.env['report.project.task.user'].with_user(self.bob)
        self.assertFalse(report.search([('task_id', '=', self.task.id)]))
        self.assertFalse(self.env['binaryaid.work.log'].with_user(self.bob).search([('task_id', '=', self.task.id)]))

    def test_notes_and_completion(self):
        wizard = self.env['binaryaid.work.update'].with_user(self.alice).create({
            'task_id': self.task.id, 'note': 'Implemented the first part', 'work_date': fields.Date.today()})
        wizard.action_submit()
        self.task.with_user(self.alice).write({'description': '<p>Details updated</p>'})
        self.task.with_user(self.alice).action_binaryaid_complete()
        logs = self.task.binaryaid_work_log_ids
        self.assertEqual(set(logs.mapped('event')), {'assigned', 'note', 'completed'})
        self.assertEqual(logs.filtered(lambda log: log.event == 'completed').author_id, self.alice)
        self.assertEqual(self.task.state, '1_done')
        with self.assertRaises(AccessError):
            self.task.with_user(self.alice).write({'state': '01_in_progress'})
        self.task.action_binaryaid_reopen()
        self.assertEqual(self.task.state, '01_in_progress')
        self.assertEqual(len(self.task.binaryaid_work_log_ids.filtered(lambda log: log.event == 'reopened')), 1)

    def test_employee_cannot_assign_or_modify_history(self):
        with self.assertRaises(AccessError):
            self.env['project.task'].with_user(self.alice).create({'name': 'Unauthorized', 'binaryaid_employee_id': self.bob_employee.id})
        for values in ({'user_ids': [Command.set(self.bob.ids)]}, {'binaryaid_employee_id': False}, {'name': 'Changed'}, {'active': False}):
            with self.assertRaises(AccessError):
                self.task.with_user(self.alice).write(values)
        with self.assertRaises(AccessError):
            self.task.with_user(self.alice).unlink()
        with self.assertRaises(AccessError):
            self.task.binaryaid_work_log_ids.with_user(self.admin).write({'note': 'Forged'})
        with self.assertRaises(AccessError):
            self.env['binaryaid.work.log'].with_user(self.alice).create({'task_id': self.task.id})

    def test_wizard_cannot_target_another_employee(self):
        wizard = self.env['binaryaid.work.update'].with_user(self.bob).create({'task_id': self.task.id, 'note': 'Unauthorized'})
        with self.assertRaises(AccessError):
            wizard.action_submit()

    def test_standard_project_task_unchanged(self):
        task = self.env['project.task'].with_user(self.alice).create({'name': 'Ordinary private task'})
        task.write({'description': 'Native task', 'state': '1_done'})
        self.assertFalse(task.binaryaid_employee_id)
        self.assertFalse(task.binaryaid_work_log_ids)
        task.unlink()

    def test_work_form_and_employee_navigation(self):
        with Form(self.env['project.task'].with_user(self.admin), view='binaryaid_work_management.view_work_form') as form:
            form.name = 'Created through employee work form'
            form.binaryaid_employee_id = self.employee
        task = form.record
        self.assertEqual(task.binaryaid_employee_id, self.employee)
        view = self.env['project.task'].with_user(self.alice).get_view(
            self.env.ref('binaryaid_work_management.view_work_form').id, 'form')
        self.assertNotIn('create="false"', view['arch'].split('<sheet>')[0])
        self.assertIn(('binaryaid_employee_id', '=', self.employee.id),
                      self.employee.with_user(self.admin).action_binaryaid_work()['domain'])
        with self.assertRaises(AccessError):
            self.employee.with_user(self.alice).action_binaryaid_work_history()

    def test_employee_directory_and_self_created_work(self):
        directory = self.env['binaryaid.work.employee'].with_user(self.alice)
        self.assertEqual(directory.search([]).ids, self.employee.ids)
        with self.assertRaises(AccessError):
            directory.browse(self.bob_employee.id).action_open_work()
        admin_directory = directory.with_user(self.admin)
        self.assertIn(self.bob_employee.id, admin_directory.search([]).ids)
        action = directory.browse(self.employee.id).action_open_work()
        self.assertEqual(action['context']['group_by'], ['binaryaid_work_date:day'])
        self.assertEqual(action['domain'], [('binaryaid_employee_id', '=', self.employee.id)])
        with Form(self.env['project.task'].with_user(self.alice).with_context(**action['context']),
                  view='binaryaid_work_management.view_work_form') as form:
            form.name = 'Employee adds own work'
            form.description = '<p>Self planned work</p>'
        task = form.record
        self.assertEqual(task.binaryaid_employee_id, self.employee)
        self.assertEqual(task.user_ids, self.alice)
        self.assertEqual(task.create_uid, self.alice)
        self.assertTrue(task.binaryaid_work_date)
        self.assertEqual(task.binaryaid_work_log_ids.event, 'assigned')
        task.action_binaryaid_complete()

    def test_work_date_and_latest_note(self):
        self.assertEqual(self.task.binaryaid_work_date,
                         fields.Date.context_today(self.task))
        self.task._binaryaid_log('note', 'First note')
        self.task._binaryaid_log('note', 'Second note')
        self.assertEqual(self.task.with_user(self.alice).binaryaid_latest_note, 'Second note')
        with self.assertRaises(AccessError):
            self.task.write({'binaryaid_work_date': '2000-01-01'})
        groups = self.env['project.task'].with_user(self.alice)._read_group(
            [('binaryaid_employee_id', '=', self.employee.id)], ['binaryaid_work_date:day'], ['__count'])
        self.assertEqual(sum(count for day, count in groups), 1)

    def test_backdated_work_and_history(self):
        previous_date = fields.Date.subtract(fields.Date.context_today(self.task), days=7)
        action = self.env['binaryaid.work.employee'].with_user(self.alice).action_my_work()
        with Form(self.env['project.task'].with_user(self.alice).with_context(**action['context']),
                  view='binaryaid_work_management.view_work_form') as form:
            self.assertEqual(form.binaryaid_work_date, fields.Date.context_today(self.task))
            form.name = 'Work performed last week'
            form.binaryaid_work_date = previous_date
        task = form.record
        self.assertEqual(task.binaryaid_work_date, previous_date)
        note_action = task.action_binaryaid_update()
        wizard = self.env['binaryaid.work.update'].with_user(self.alice).with_context(
            **note_action['context']).create({'note': 'Completed earlier; recorded today'})
        self.assertEqual(wizard.work_date, previous_date)
        wizard.action_submit()
        task.action_binaryaid_complete()
        self.assertEqual(set(task.binaryaid_work_log_ids.mapped('work_date')), {previous_date})
        self.assertTrue(all(log.create_date.date() >= previous_date for log in task.binaryaid_work_log_ids))
        view = self.env['project.task'].get_view(self.env.ref('binaryaid_work_management.view_work_form').id, 'form')
        self.assertNotIn('name="date_deadline"', view['arch'])

    def test_invalid_dates_and_idempotent_completion(self):
        wizard = self.env['binaryaid.work.update'].with_user(self.alice).create({
            'task_id': self.task.id, 'note': 'Future', 'work_date': fields.Date.add(fields.Date.today(), days=1)})
        with self.assertRaises(ValidationError):
            wizard.action_submit()
        self.task.action_binaryaid_complete()
        self.task.action_binaryaid_complete()
        self.assertEqual(len(self.task.binaryaid_work_log_ids.filtered(lambda log: log.event == 'completed')), 1)

    def test_company_isolation(self):
        company = self.env['res.company'].create({'name': 'Work Test Other Company'})
        user = new_test_user(self.env, login='test_work_other_company', groups='binaryaid_work_management.group_work_user',
                             company_id=company.id, company_ids=[Command.set(company.ids)])
        employee = self.env['hr.employee'].create({'name': 'Other Company Worker', 'user_id': user.id, 'company_id': company.id})
        task = self.env['project.task'].sudo().with_company(company).create({'name': 'Other company task', 'binaryaid_employee_id': employee.id})
        self.assertFalse(self.env['project.task'].with_user(self.admin).search([('id', '=', task.id)]))
        self.assertFalse(self.env['binaryaid.work.log'].with_user(self.admin).search([('task_id', '=', task.id)]))
        self.assertFalse(self.env['binaryaid.work.employee'].with_user(self.admin).search([('id', '=', employee.id)]))
