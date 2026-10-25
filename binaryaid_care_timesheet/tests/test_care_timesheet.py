import base64
from datetime import datetime, timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.binaryaid_care.models.tools import fortnight_start


@tagged('post_install', '-at_install')
class TestCareTimesheet(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = new_test_user(cls.env, login='ts_admin', tz='UTC', groups=','.join([
            'binaryaid_work_management.group_work_admin', 'hr.group_hr_user']))
        cls.worker_user = new_test_user(cls.env, login='ts_worker', tz='UTC', groups='binaryaid_work_management.group_work_user')
        cls.other_user = new_test_user(cls.env, login='ts_other', groups='binaryaid_work_management.group_work_user')
        cls.worker = cls.env['hr.employee'].create({'name': 'TS Worker', 'user_id': cls.worker_user.id,
                                                    'binaryaid_employee_code': 'E-100'})
        cls.client = cls.env['binaryaid.care.client'].create({'name': 'TS Client', 'reference': 'TS-1'})
        cls.period = fortnight_start(cls.env, fields.Date.today()) - timedelta(days=14)
        day = datetime.combine(cls.period, datetime.min.time())
        cls.complete = cls._shift(day + timedelta(days=1, hours=9), 4, unpaid_break_minutes=30)
        cls.no_clock = cls._shift(day + timedelta(days=2, hours=9), 4)
        cls.with_exception = cls._shift(day + timedelta(days=3, hours=9), 4)
        Attendance = cls.env['hr.attendance']
        Attendance.create({'employee_id': cls.worker.id, 'binaryaid_shift_id': cls.complete.id,
                           'check_in': cls.complete.start, 'check_out': cls.complete.start + timedelta(hours=4)})
        Attendance.create({'employee_id': cls.worker.id, 'binaryaid_shift_id': cls.with_exception.id,
                           'check_in': cls.with_exception.start, 'check_out': cls.with_exception.end})
        for shift in (cls.complete, cls.with_exception):
            note = cls.env['binaryaid.care.shift.note']._for_shift(shift)
            note._store_answers({q.id: 'no' if q.answer_type == 'yes_no' else 'Done' for q in note._questions()})
            note._submit()
        cls.env['binaryaid.care.attendance.exception'].sudo().create({
            'employee_id': cls.worker.id, 'shift_id': cls.with_exception.id, 'kind': 'wrong_location',
            'clock_type': 'in', 'requested_time': cls.with_exception.start, 'reason': 'At the side entrance'})

    @classmethod
    def _shift(cls, start, hours, **vals):
        shift = cls.env['binaryaid.work.shift'].with_user(cls.admin).create(dict({
            'name': 'TS shift', 'employee_id': cls.worker.id, 'client_id': cls.client.id, 'timezone': 'UTC',
            'start': start, 'end': start + timedelta(hours=hours)}, **vals))
        shift._roster_transition_write({'state': 'published', 'published_at': start - timedelta(days=2)})
        return shift

    def generate(self):
        sheet = self.env['binaryaid.care.timesheet'].with_user(self.admin)._generate(self.period, self.worker)
        self.assertEqual(len(sheet), 1)
        return sheet

    def lines(self, sheet):
        return {line.shift_id: line for line in sheet.line_ids}

    def test_statuses_and_totals(self):
        sheet = self.generate()
        lines = self.lines(sheet)
        self.assertEqual(sheet.period_start, self.period)
        self.assertEqual((lines[self.complete].status, lines[self.no_clock].status, lines[self.with_exception].status),
                         ('complete', 'incomplete', 'unresolved'))
        self.assertEqual(sheet.planned_hours, 3.5 + 4 + 4)
        self.assertEqual(sheet.actual_hours, 8)
        self.assertEqual(sheet.approved_hours, 4, 'incomplete and unresolved rows are excluded')
        self.assertEqual(sheet.issue_count, 2)
        # Breaks only apply once agreed.
        self.env['ir.config_parameter'].set_param('binaryaid_care.apply_unpaid_breaks', 'True')
        sheet.with_user(self.admin).action_refresh()
        self.assertEqual(lines[self.complete].effective_hours, 3.5)

    def test_adjustment_correction_approval_and_lock(self):
        sheet = self.generate().with_user(self.admin)
        line = self.lines(sheet)[self.no_clock]
        with self.assertRaises(ValidationError):
            line._adjust(4, '')
        line._adjust(3.75, 'Confirmed with client: phone had no signal')
        self.assertEqual((line.status, line.approved_hours, line.actual_hours), ('complete', 3.75, 0))
        worker_line = self.lines(sheet)[self.complete].with_user(self.worker_user)
        worker_line._request_correction('I stayed 15 minutes longer')
        self.assertEqual(worker_line.status, 'unresolved')
        with self.assertRaises(AccessError):
            self.lines(sheet)[self.complete].with_user(self.other_user)._request_correction('not mine')
        with self.assertRaises(AccessError):
            line.with_user(self.worker_user)._adjust(8, 'self approval')
        self.lines(sheet)[self.complete].action_resolve_correction()
        sheet.action_approve()
        self.assertEqual(sheet.state, 'approved')
        self.assertEqual(sheet.approved_hours, 4 + 3.75)
        with self.assertRaises(UserError):
            line._adjust(1, 'too late')
        sheet.action_lock()
        with self.assertRaises(UserError):
            sheet.action_reset_review()
        with self.assertRaises(AccessError):
            sheet.with_user(self.admin).write({'period_start': fields.Date.today()})
        # Original attendance is untouched by adjustments.
        self.assertEqual(self.no_clock.attendance_ids, self.env['hr.attendance'])

    def test_export_and_access(self):
        sheet = self.generate().with_user(self.admin)
        with self.assertRaises(UserError):
            sheet.action_export_csv()
        sheet.action_approve()
        url = sheet.action_export_csv()['url']
        attachment = self.env['ir.attachment'].browse(int(url.split('/')[-1].split('?')[0]))
        content = base64.b64decode(attachment.datas).decode('utf-8-sig')
        self.assertIn('E-100', content)
        self.assertIn('TS-1', content)
        self.assertIn('SHIFT-%s' % self.complete.id, content)
        with self.assertRaises(AccessError):
            sheet.with_user(self.worker_user).action_export_csv()
        self.assertEqual(self.env['binaryaid.care.timesheet'].with_user(self.worker_user).search([]), sheet)
        self.assertFalse(self.env['binaryaid.care.timesheet'].with_user(self.other_user).search([]))

    def test_dashboard_queue(self):
        sheet = self.generate()
        data = self.env['binaryaid.hrms.dashboard'].with_user(self.admin).get_overview()
        tab = next(t for t in data['attention'] if t['key'] == 'timesheets')
        self.assertIn(sheet.id, [i['id'] for i in tab['items']])
        action = self.env['binaryaid.hrms.dashboard'].with_user(self.admin).item_action('timesheet', sheet.id, 'open')
        self.assertEqual(action['res_id'], sheet.id)


@tagged('post_install', '-at_install')
class TestCareEndToEnd(TransactionCase):
    """Task 17: request → assignment → attendance → note → timesheet, across all care modules."""

    def test_full_flow(self):
        admin = new_test_user(self.env, login='e2e_admin', tz='UTC', groups=','.join([
            'binaryaid_work_management.group_work_admin', 'hr.group_hr_user']))
        worker_user = new_test_user(self.env, login='e2e_worker', tz='UTC', groups='binaryaid_work_management.group_work_user')
        worker = self.env['hr.employee'].create({'name': 'E2E Worker', 'user_id': worker_user.id})
        client = self.env['binaryaid.care.client'].create({'name': 'E2E Client', 'reference': 'E2E-1', 'location_ids': [
            (0, 0, {'name': 'Home', 'latitude': -33.8688, 'longitude': 151.2093, 'timezone': 'UTC'})]})
        client.location_ids.action_verify_coordinates()
        # 1. The client's representative submits a request (portal path covered in binaryaid_care tests).
        request = self.env['binaryaid.care.client.request'].create({
            'client_id': client.id, 'support_needs': 'Morning support', 'location_id': client.location_ids.id,
            'preferred_date_from': fields.Date.today()})
        board = self.env['binaryaid.hrms.dashboard'].with_user(admin)
        board.item_action('request', request.id, 'approve')
        # 2. Admin creates an unfilled shift from the request, assigns a worker and publishes.
        context = board.item_action('request', request.id, 'create_shift')['context']
        now = fields.Datetime.now().replace(microsecond=0)
        context.update(default_start=fields.Datetime.to_string(now - timedelta(minutes=5)),
                       default_end=fields.Datetime.to_string(now + timedelta(hours=3)))
        shift = self.env['binaryaid.work.shift'].with_user(admin).with_context(**context).create({})
        self.assertTrue(shift.is_unfilled)
        shift.employee_id = worker
        shift.action_publish()
        self.assertEqual(request.state, 'scheduled')
        # 3. Worker signs in on site, reports an incident and signs out with the shift note.
        worker_board = self.env['binaryaid.hrms.dashboard'].with_user(worker_user)
        self.assertEqual(worker_board.get_overview()['clock']['action'], 'in')
        self.assertEqual(worker_board.care_clock_in(shift.id, -33.86885, 151.20935, 5)['status'], 'ok')
        incident = self.env['binaryaid.care.incident'].with_user(worker_user).create({
            'client_id': client.id, 'location': 'Kitchen', 'severity': 'low', 'description': 'Minor spill',
            'immediate_action': 'Cleaned', 'category_id': self.env.ref('binaryaid_care_attendance.incident_cat_other').id})
        self.assertTrue(incident.name.startswith('INC/'))
        form = worker_board.care_note_form(shift.id)
        answers = {q['id']: ('no' if q['type'] == 'yes_no' else 'Done') for q in form['questions']}
        self.assertEqual(worker_board.care_clock_out(shift.id, answers, -33.86885, 151.20935, 5, 'e2e')['status'], 'ok')
        attendance = self.env['hr.attendance'].search([('binaryaid_shift_id', '=', shift.id)])
        self.assertTrue(attendance.check_out and attendance.out_mode == 'binaryaid_gps')
        self.assertEqual(shift.care_note_status, 'submitted')
        # 4. The fortnightly timesheet includes the completed shift and can be approved and exported.
        sheet = self.env['binaryaid.care.timesheet'].with_user(admin)._generate(shift.start.date(), worker)
        line = sheet.line_ids.filtered(lambda l: l.shift_id == shift)
        self.assertEqual(line.status, 'complete')
        sheet.action_approve()
        sheet.action_lock()
        self.assertEqual(sheet.approved_hours, line.effective_hours)
        self.assertEqual(sheet.state, 'locked')
        self.assertIn('/web/content/', sheet.action_export_csv()['url'])
