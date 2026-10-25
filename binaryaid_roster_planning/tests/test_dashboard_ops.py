from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestDashboardOperations(TransactionCase):
    """Administrator dashboard figures, inbox lists and inline actions."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = new_test_user(cls.env, login='ops_admin', groups=','.join([
            'binaryaid_work_management.group_work_admin', 'hr.group_hr_user',
            'hr_attendance.group_hr_attendance_manager', 'hr_holidays.group_hr_holidays_user']))
        cls.alice = new_test_user(cls.env, login='ops_alice', groups='binaryaid_work_management.group_work_user')
        cls.bob = new_test_user(cls.env, login='ops_bob', groups='binaryaid_work_management.group_work_user')
        cls.employee = cls.env['hr.employee'].create({'name': 'Ops Alice', 'user_id': cls.alice.id})
        cls.other = cls.env['hr.employee'].create({'name': 'Ops Bob', 'user_id': cls.bob.id})
        cls.shifts = cls.env['binaryaid.work.shift'].with_user(cls.admin)
        cls.dashboard = cls.env['binaryaid.hrms.dashboard']

    def shift(self, employee, start, end, **vals):
        return self.shifts.create(dict({'name': 'Ops shift', 'employee_id': employee.id,
                                        'start': start, 'end': end, 'timezone': 'UTC'}, **vals))

    def overview(self, user=None):
        data = self.dashboard.with_user(user or self.admin).with_context(tz='UTC').get_overview()
        return data, {card['key']: card['value'] for card in data['cards']}, {tab['key']: tab for tab in data['attention']}

    def test_admin_today_board_and_publication(self):
        now = fields.Datetime.now()
        before = self.overview()[1]
        running = self.shift(self.employee, now - timedelta(minutes=30), now + timedelta(hours=2))
        running.action_publish()
        self.env['hr.attendance'].create({'employee_id': self.employee.id, 'check_in': now - timedelta(minutes=25)})
        draft = self.shift(self.other, now + timedelta(days=2), now + timedelta(days=2, hours=4), name='Draft ops')
        data, cards, tabs = self.overview()
        self.assertTrue(data['admin'])
        self.assertEqual(cards['shifts_today'], before['shifts_today'] + 1)
        self.assertEqual(cards['unpublished'], before['unpublished'] + 1)
        self.assertEqual(len(data['coverage']['days']), 14)
        row = next(r for r in data['today']['rows'] if r['id'] == running.id)
        self.assertEqual(row['status'], 'on_shift')
        self.assertIn(draft.id, [item['id'] for item in tabs['unpublished']['items']])
        self.assertTrue({'create_shift', 'add_employee'}.issubset({a['key'] for a in data['quick_actions']}))
        dashboard = self.dashboard.with_user(self.admin)
        self.assertEqual(dashboard.item_action('shift', draft.id, 'open')['target'], 'new')
        self.assertTrue(dashboard.item_action('shift', draft.id, 'publish'))
        self.assertEqual(draft.state, 'published')
        self.assertEqual(self.overview()[1]['unpublished'], before['unpublished'])
        action = dashboard.with_context(tz='Australia/Sydney').quick_action('create_shift', '2027-01-11')
        self.assertEqual(action['target'], 'new')
        self.assertEqual(action['context']['default_start'], '2027-01-10 22:00:00')

    def test_missing_signout_and_timesheet_review(self):
        now = fields.Datetime.now()
        attendance = self.env['hr.attendance'].create({'employee_id': self.other.id, 'check_in': now - timedelta(hours=10)})
        ended = self.shift(self.employee, now - timedelta(hours=9), now - timedelta(hours=1))
        ended._roster_transition_write({'state': 'published', 'published_at': now - timedelta(days=1)})
        data, cards, tabs = self.overview()
        self.assertIn(attendance.id, [item['id'] for item in tabs['missing_signout']['items']])
        self.assertGreaterEqual(cards['missing_signout'], 1)
        dashboard = self.dashboard.with_user(self.admin)
        # The fortnightly timesheet add-on replaces per-shift reconciliation as the review queue.
        if 'binaryaid.care.timesheet' not in self.env:
            self.assertIn(ended.id, [item['id'] for item in tabs['timesheets']['items']])
            self.assertGreaterEqual(cards['timesheets'], 1)
            self.assertEqual(dashboard.item_action('timesheet', ended.id, 'reconcile')['res_model'], 'binaryaid.roster.actual.wizard')
        self.assertEqual(dashboard.item_action('attendance', attendance.id, 'open')['res_model'], 'hr.attendance')
        attendance.check_out = now
        with self.assertRaises(AccessError):
            dashboard.item_action('attendance', attendance.id, 'open')

    def test_leave_inbox_flags_roster_conflicts(self):
        start = fields.Datetime.now() + timedelta(days=3)
        shift = self.shift(self.employee, start.replace(hour=9, minute=0, second=0), start.replace(hour=17, minute=0, second=0))
        shift.action_publish()
        leave_type = self.env['hr.leave.type'].create({'name': 'Ops leave', 'requires_allocation': False,
                                                      'leave_validation_type': 'hr'})
        day = start.date()
        conflicting = self.env['hr.leave'].create({'holiday_status_id': leave_type.id, 'employee_id': self.employee.id,
                                                   'request_date_from': day, 'request_date_to': day})
        free = self.env['hr.leave'].create({'holiday_status_id': leave_type.id, 'employee_id': self.other.id,
                                            'request_date_from': day, 'request_date_to': day})
        items = {item['id']: item for item in self.overview()[2]['leave']['items']}
        self.assertTrue(items[conflicting.id]['warning'])
        self.assertNotIn('approve', [a['name'] for a in items[conflicting.id]['actions']])
        self.assertIn('approve', [a['name'] for a in items[free.id]['actions']])
        self.assertTrue(self.dashboard.with_user(self.admin).item_action('leave', free.id, 'approve'))
        self.assertEqual(free.state, 'validate')

    def test_worker_cannot_use_admin_actions(self):
        now = fields.Datetime.now()
        draft = self.shift(self.employee, now + timedelta(days=1), now + timedelta(days=1, hours=4))
        data, cards, tabs = self.overview(self.alice)
        self.assertFalse(data['admin'])
        self.assertFalse(data['today'])
        self.assertFalse(tabs)
        self.assertNotIn('unpublished', cards)
        self.assertIn('presence', data)
        dashboard = self.dashboard.with_user(self.alice)
        for source, name in (('shift', 'publish'), ('shift', 'open'), ('timesheet', 'reconcile'), ('leave', 'approve')):
            with self.assertRaises(AccessError):
                dashboard.item_action(source, draft.id, name)
        with self.assertRaises(AccessError):
            dashboard.quick_action('create_shift')
        self.assertEqual(draft.state, 'draft')


@tagged('post_install', '-at_install')
class TestDashboardOperationsUI(HttpCase):
    def test_admin_inline_publish_and_dialogs(self):
        admin = new_test_user(self.env, login='ops_ui_admin', tz='UTC', groups=','.join([
            'binaryaid_work_management.group_work_admin', 'hr.group_hr_user',
            'hr_attendance.group_hr_attendance_manager', 'hr_holidays.group_hr_holidays_user']))
        user = new_test_user(self.env, login='ops_ui_worker', groups='binaryaid_work_management.group_work_user')
        employee = self.env['hr.employee'].create({'name': 'Dialog Worker', 'user_id': user.id})
        now = fields.Datetime.now()
        draft = self.env['binaryaid.work.shift'].with_user(admin).create({
            'name': 'Inline publish shift', 'employee_id': employee.id, 'timezone': 'UTC',
            'start': now + timedelta(days=2), 'end': now + timedelta(days=2, hours=4)})
        self.browser_js('/odoo', """
          (async () => {
            const wait = async (fn, label) => {
                for (let i = 0; i < 200; i++) {
                    const value = fn();
                    if (value) return value;
                    await new Promise(resolve => setTimeout(resolve, 100));
                }
                throw new Error('Timed out: ' + label);
            };
            const byText = (selector, text) => [...document.querySelectorAll(selector)].find(el => el.textContent.includes(text));
            await wait(() => document.querySelector('.ba_inbox'), 'attention inbox');
            const item = await wait(() => byText('.ba_inbox_item', 'Inline publish shift'), 'draft in inbox');
            item.querySelector('.ba_act_success').click();
            await wait(() => !byText('.ba_inbox_item', 'Inline publish shift'), 'draft removed after publish');
            await wait(() => byText('.o_notification', 'Publish'), 'success notification');
            byText('.ba_header button', 'Create shift').click();
            await wait(() => document.querySelector('.o_dialog .o_form_view'), 'create shift dialog');
            document.querySelector('.o_dialog .btn-close, .o_dialog .o_form_button_cancel').click();
            await wait(() => !document.querySelector('.o_dialog'), 'dialog closed');
            const day = await wait(() => document.querySelector('button.ba_plan_day:not(:disabled)'), 'planner day');
            day.click();
            await wait(() => document.querySelector('.o_dialog .o_form_view'), 'planner dialog');
            console.log('test successful');
          })().catch(error => console.error(error));
        """, login=admin.login, timeout=90)
        self.assertEqual(draft.state, 'published')
