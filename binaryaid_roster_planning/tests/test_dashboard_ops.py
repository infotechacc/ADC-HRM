from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestDashboardOperations(TransactionCase):
    """Administrator dashboard figures, today's board, calendar and dialogs."""

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
        return data, {card['key']: card['value'] for card in data['cards']}

    def test_admin_today_board_and_publication(self):
        now = fields.Datetime.now()
        _data, before = self.overview()
        running = self.shift(self.employee, now - timedelta(minutes=30), now + timedelta(hours=2))
        running.action_publish()
        self.env['hr.attendance'].create({'employee_id': self.employee.id, 'check_in': now - timedelta(minutes=25)})
        draft = self.shift(self.other, now + timedelta(days=2), now + timedelta(days=2, hours=4), name='Draft ops')
        data, cards = self.overview()
        self.assertTrue(data['admin'])
        self.assertNotIn('attention', data)
        self.assertNotIn('recent_work', data)
        self.assertEqual(cards['shifts_today'], before['shifts_today'] + 1)
        self.assertNotIn('coverage', data)
        row = next(r for r in data['day']['rows'] if r['id'] == running.id)
        self.assertEqual(row['status'], 'on_shift')
        self.assertTrue(row['time_label'] and data['day']['short'])
        # The month calendar counts the draft on its day; selecting the day lists it as a card.
        dashboard = self.dashboard.with_user(self.admin).with_context(tz='UTC')
        draft_day = str(draft.start.date())
        calendar = dashboard.calendar_month(draft_day)
        cell = next(d for week in calendar['weeks'] for d in week if d['date'] == draft_day)
        self.assertGreaterEqual(cell['draft'], 1)
        self.assertEqual(sum(len(week) for week in calendar['weeks']) % 7, 0)
        self.assertIn(draft.id, [r['id'] for r in dashboard.day_board(draft_day)['rows']])
        self.assertTrue({'create_shift', 'add_employee'}.issubset({a['key'] for a in data['quick_actions']}))
        dashboard = self.dashboard.with_user(self.admin)
        self.assertEqual(dashboard.item_action('shift', draft.id, 'open')['target'], 'new')
        with self.assertRaises(AccessError):
            dashboard.item_action('shift', draft.id, 'publish')
        self.assertEqual(dashboard.open_section('work_schedule')['view_mode'].split(',')[0], 'list')
        action = dashboard.with_context(tz='Australia/Sydney').quick_action('create_shift', '2027-01-11')
        self.assertEqual(action['target'], 'new')
        self.assertEqual(action['context']['default_start'], '2027-01-10 22:00:00')

    def test_missing_signout_figure(self):
        now = fields.Datetime.now()
        _data, before = self.overview()
        self.env['hr.attendance'].create({'employee_id': self.other.id, 'check_in': now - timedelta(hours=10)})
        _data, cards = self.overview()
        self.assertEqual(cards['missing_signout'], before['missing_signout'] + 1)
        self.assertEqual(self.dashboard.with_user(self.admin).open_section('missing_signout')['res_model'], 'hr.attendance')

    def test_worker_cannot_use_admin_actions(self):
        now = fields.Datetime.now()
        draft = self.shift(self.employee, now + timedelta(days=1), now + timedelta(days=1, hours=4))
        data, cards = self.overview(self.alice)
        self.assertFalse(data['admin'])
        self.assertFalse(data['day'])
        for method in ('calendar_month', 'day_board'):
            with self.assertRaises(AccessError):
                getattr(self.dashboard.with_user(self.alice), method)(str(now.date()))
        self.assertNotIn('unpublished', cards)
        self.assertIn('presence', data)
        dashboard = self.dashboard.with_user(self.alice)
        for source, name in (('shift', 'open'), ('leave', 'approve')):
            with self.assertRaises(AccessError):
                dashboard.item_action(source, draft.id, name)
        with self.assertRaises(AccessError):
            dashboard.quick_action('create_shift')
        self.assertEqual(draft.state, 'draft')


@tagged('post_install', '-at_install')
class TestDashboardOperationsUI(HttpCase):
    def test_admin_dashboard_dialogs(self):
        admin = new_test_user(self.env, login='ops_ui_admin', tz='UTC', groups=','.join([
            'binaryaid_work_management.group_work_admin', 'hr.group_hr_user',
            'hr_attendance.group_hr_attendance_manager', 'hr_holidays.group_hr_holidays_user']))
        user = new_test_user(self.env, login='ops_ui_worker', groups='binaryaid_work_management.group_work_user')
        employee = self.env['hr.employee'].create({'name': 'Dialog Worker', 'user_id': user.id})
        now = fields.Datetime.now()
        draft = self.env['binaryaid.work.shift'].with_user(admin).create({
            'name': 'Dialog shift', 'employee_id': employee.id, 'timezone': 'UTC',
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
            await wait(() => document.querySelector('.ba_metrics'), 'dashboard figures');
            for (const gone of ['.ba_inbox', '.ba_goto', '.ba_side', '.ba_work_table', '.ba_account_btn']) {
                if (document.querySelector(gone)) throw new Error('Removed section still shown: ' + gone);
            }
            if (byText('.ba_header button', 'Review requests')) throw new Error('Review requests still shown');
            (await wait(() => document.querySelector('.ba_month_day[aria-label^="%s"]'), 'draft day in calendar')).click();
            (await wait(() => byText('.ba_shift_tile', 'Dialog'), 'shift card for the day')).click();
            await wait(() => document.querySelector('.o_dialog .o_form_view'), 'shift dialog');
            document.querySelector('.o_dialog .btn-close').click();
            await wait(() => !document.querySelector('.o_dialog'), 'shift dialog closed');
            byText('.ba_header button', 'Create shift').click();
            await wait(() => document.querySelector('.o_dialog .o_form_view'), 'create shift dialog');
            document.querySelector('.o_dialog .btn-close, .o_dialog .o_form_button_cancel').click();
            await wait(() => !document.querySelector('.o_dialog'), 'dialog closed');
            (await wait(() => byText('.ba_dayview button', 'Assign shift'), 'assign shift button')).click();
            await wait(() => document.querySelector('.o_dialog .o_form_view'), 'assign shift dialog');
            if (document.querySelector('.o_dialog div[name="unpaid_break_minutes"]')) throw new Error('Unpaid break still shown');
            if (!document.querySelector('.o_dialog div[name="location"] input')) throw new Error('Location is not editable');
            console.log('test successful');
          })().catch(error => console.error(error));
        """ % str(draft.start.date()), login=admin.login, timeout=90)
        self.assertEqual(draft.state, 'draft')
