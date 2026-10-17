from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import Form, HttpCase, TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestWorkScheduling(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login='roster_manager', groups='binaryaid_work_management.group_work_admin')
        cls.alice = new_test_user(cls.env, login='roster_alice', groups='binaryaid_work_management.group_work_user', tz='Australia/Sydney')
        cls.bob = new_test_user(cls.env, login='roster_bob', groups='binaryaid_work_management.group_work_user,project.group_project_manager')
        cls.employee = cls.env['hr.employee'].create({'name': 'Roster Alice', 'user_id': cls.alice.id})
        cls.other = cls.env['hr.employee'].create({'name': 'Roster Bob', 'user_id': cls.bob.id})
        cls.shifts = cls.env['binaryaid.work.shift'].with_user(cls.manager)

    def shift(self, **kwargs):
        vals = dict(name='Morning shift', employee_id=self.employee.id,
                    start='2027-01-11 22:00:00', end='2027-01-12 06:00:00', unpaid_break_minutes=30)
        vals.update(kwargs)
        return self.shifts.create(vals)

    def test_publication_and_isolation(self):
        shift = self.shift()
        self.assertFalse(self.shifts.with_user(self.alice).search([]))
        shift.action_publish()
        self.assertEqual(shift.planned_hours, 7.5)
        self.assertEqual(shift.with_user(self.alice).name, 'Morning shift')
        self.assertTrue(shift.with_user(self.alice).read())
        with Form(shift.with_user(self.alice), view='binaryaid_work_scheduling.view_shift_form') as form:
            self.assertEqual(form.name, 'Morning shift')
        self.assertFalse(self.shifts.with_user(self.bob).search([]))
        with self.assertRaises(AccessError):
            shift.with_user(self.bob).read(['name'])
        with self.assertRaises(AccessError):
            shift.with_user(self.alice).write({'name': 'Forged'})
        with self.assertRaises(AccessError):
            shift.with_user(self.alice).action_cancel()
        with self.assertRaises(AccessError):
            shift.with_user(self.alice).copy()

    def test_overlap_and_adjacent(self):
        self.shift().action_publish()
        overlap = self.shift(start='2027-01-12 05:00:00', end='2027-01-12 10:00:00')
        with self.assertRaises(ValidationError):
            overlap.action_publish()
        self.shift(start='2027-01-12 06:00:00', end='2027-01-12 10:00:00').action_publish()
        self.shift(employee_id=self.other.id).action_publish()

    def test_tasks_reuse_existing_work(self):
        task = self.env['project.task'].with_user(self.manager).create({
            'name': 'Prepare equipment', 'binaryaid_employee_id': self.employee.id})
        shift = self.shift(task_ids=[Command.set(task.ids)])
        shift.action_publish()
        task.with_user(self.alice).action_binaryaid_complete()
        self.assertEqual(shift.task_ids.state, '1_done')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.shift(employee_id=self.other.id, task_ids=[Command.set(task.ids)])

    def test_revision_retains_history(self):
        shift = self.shift()
        shift.action_publish()
        with self.assertRaises(ValidationError):
            shift.write({'start': '2027-01-11 21:00:00'})
        with self.assertRaises(ValidationError):
            shift.action_revise()
        shift.write({'change_reason': 'Consulted employee about new start time'})
        shift.action_revise()
        self.assertFalse(self.shifts.with_user(self.alice).search([('id', '=', shift.id)]))
        with self.assertRaises(ValidationError):
            shift.unlink()
        shift.write({'start': '2027-01-11 21:00:00'})
        shift.action_publish()
        shift.write({'change_reason': 'Site closure discussed with employee'})
        shift.action_cancel()
        self.assertEqual(shift.with_user(self.alice).state, 'cancelled')
        self.assertTrue(shift.message_ids)

    def test_thresholds_require_review(self):
        shift = self.shift(weekly_hours_limit=7)
        with self.assertRaises(ValidationError):
            shift.action_publish()
        shift.write({'review_note': 'Additional hours reviewed and agreed'})
        shift.action_publish()
        second = self.shift(start='2027-01-12 07:00:00', end='2027-01-12 09:00:00', min_rest_hours=10)
        self.assertTrue(second._review_warnings())
        with self.assertRaises(ValidationError):
            second.action_publish()

    def test_invalid_values_and_status_bypass(self):
        for vals in ({'end': '2027-01-11 21:00:00'}, {'unpaid_break_minutes': -1},
                     {'unpaid_break_minutes': 480}, {'weekly_hours_limit': -1}, {'state': 'published'}):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                self.shift(**vals)
        shift = self.shift()
        with self.assertRaises(AccessError):
            shift.write({'state': 'published'})

    def test_company_isolation(self):
        company = self.env['res.company'].create({'name': 'Roster Other Company'})
        self.manager.write({'company_ids': [Command.link(company.id)]})
        self.bob.write({'company_ids': [Command.link(company.id)]})
        employee = self.env['hr.employee'].create({'name': 'Other company Bob', 'user_id': self.bob.id, 'company_id': company.id})
        shift = self.shifts.with_context(allowed_company_ids=[company.id]).create({
            'name': 'Other company', 'employee_id': employee.id, 'company_id': company.id,
            'start': '2027-01-11 22:00:00', 'end': '2027-01-12 06:00:00'})
        self.assertFalse(self.shifts.with_context(allowed_company_ids=[self.env.company.id]).search([('id', '=', shift.id)]))

    def test_dashboard_and_views(self):
        overview = self.env['binaryaid.hrms.dashboard'].with_user(self.alice).get_overview()
        self.assertIn('schedule', overview)
        action = self.env['binaryaid.hrms.dashboard'].with_user(self.alice).open_section('work_schedule')
        self.assertEqual(action['res_model'], 'binaryaid.work.shift')
        with Form(self.shifts, view='binaryaid_work_scheduling.view_shift_form') as form:
            form.name = 'Form shift'
            form.employee_id = self.employee
            form.start = '2027-01-11 22:00:00'
            form.end = '2027-01-12 06:00:00'
        self.assertEqual(form.record.state, 'draft')

    def test_dashboard_only_own_published_shifts(self):
        now = fields.Datetime.now()
        shift = self.shift(start=now - timedelta(minutes=30), end=now + timedelta(hours=2))
        self.shift(employee_id=self.other.id, start=now, end=now + timedelta(hours=2)).action_publish()
        dashboard = self.env['binaryaid.hrms.dashboard'].with_user(self.alice)
        self.assertFalse(dashboard.get_overview()['schedule']['shifts'])
        shift.action_publish()
        data = dashboard.get_overview()['schedule']['shifts']
        self.assertEqual([item['id'] for item in data], shift.ids)

    def test_notice_and_dst_elapsed_hours(self):
        shift = self.shift(start='2020-01-01 00:00:00', end='2020-01-01 08:00:00', notice_hours=168)
        with self.assertRaises(ValidationError):
            shift.action_publish()
        # Sydney 2027-04-04 01:00 AEDT to 04:00 AEST spans four actual hours.
        dst = self.shift(start='2027-04-03 14:00:00', end='2027-04-03 18:00:00', unpaid_break_minutes=0)
        self.assertEqual(dst.planned_hours, 4)

    def test_context_cannot_bypass_draft_creation(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.shifts.with_context(default_state='published').create({
                'name': 'Context bypass', 'employee_id': self.employee.id,
                'start': '2027-01-11 22:00:00', 'end': '2027-01-12 06:00:00'})


@tagged('post_install', '-at_install')
class TestScheduleBrowser(HttpCase):
    def test_employee_dashboard_and_calendar(self):
        user = new_test_user(self.env, login='roster_browser', groups='binaryaid_work_management.group_work_user', tz='Australia/Sydney')
        employee = self.env['hr.employee'].create({'name': 'Browser Employee', 'user_id': user.id})
        now = fields.Datetime.now()
        shift = self.env['binaryaid.work.shift'].create({
            'name': 'Browser roster shift', 'employee_id': employee.id,
            'start': now - timedelta(minutes=30), 'end': now + timedelta(hours=2)})
        shift.action_publish()
        self.browser_js('/odoo', """
          (async () => {
            const waitFor = async (selector) => {
                for (let i = 0; i < 200; i++) {
                    const el = document.querySelector(selector);
                    if (el) return el;
                    await new Promise(resolve => setTimeout(resolve, 100));
                }
                throw new Error('Missing element: ' + selector);
            };
            await waitFor('.ba_dashboard table');
            if (!document.querySelector('.ba_dashboard').textContent.includes('Browser roster shift')) {
                throw new Error('Published shift missing from dashboard');
            }
            const button = [...document.querySelectorAll('.ba_dashboard button')]
                .find(el => el.textContent.includes('Open weekly calendar'));
            button.click();
            await waitFor('.o_calendar_view');
            const event = await waitFor('.fc-event');
            event.click();
            const view = await waitFor('.o_cw_popover_edit');
            view.click();
            await waitFor('.o_dialog .o_form_view');
            console.log('test successful');
          })().catch(error => console.error(error));
        """, login=user.login, timeout=60)
