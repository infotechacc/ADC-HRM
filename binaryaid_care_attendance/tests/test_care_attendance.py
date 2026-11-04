import base64
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged

LAT, LON = -33.8688, 151.2093
NEAR = (-33.86885, 151.20935)   # about 7 m away
FAR = (-33.8700, 151.2093)      # about 133 m away
PDF = b'%PDF-1.4\n%%EOF'


def setup_care(cls):
    cls.admin = new_test_user(cls.env, login='att_admin', tz='UTC', groups=','.join([
        'binaryaid_work_management.group_work_admin', 'hr.group_hr_user', 'hr_attendance.group_hr_attendance_manager']))
    cls.reviewer = new_test_user(cls.env, login='att_reviewer', groups='binaryaid_care.group_care_reviewer')
    cls.worker_user = new_test_user(cls.env, login='att_worker', tz='UTC', groups='binaryaid_work_management.group_work_user')
    cls.other_user = new_test_user(cls.env, login='att_other', groups='binaryaid_work_management.group_work_user')
    cls.worker = cls.env['hr.employee'].create({'name': 'Att Worker', 'user_id': cls.worker_user.id})
    cls.other = cls.env['hr.employee'].create({'name': 'Att Other', 'user_id': cls.other_user.id})
    cls.client = cls.env['binaryaid.care.client'].create({
        'name': 'Att Client', 'reference': 'ATT-1',
        'location_ids': [(0, 0, {'name': 'Home', 'latitude': LAT, 'longitude': LON, 'timezone': 'UTC'})]})
    cls.other_client = cls.env['binaryaid.care.client'].create({'name': 'Att Other Client', 'reference': 'ATT-2'})
    cls.location = cls.client.location_ids
    now = fields.Datetime.now().replace(microsecond=0)
    cls.shift = cls.env['binaryaid.work.shift'].with_user(cls.admin).create({
        'name': 'Morning support', 'employee_id': cls.worker.id, 'client_id': cls.client.id,
        'service_location_id': cls.location.id, 'start': now - timedelta(minutes=10), 'end': now + timedelta(hours=4),
        'review_note': 'Test roster'})
    cls.shift._roster_transition_write({'state': 'published', 'published_at': now - timedelta(days=1)})
    cls.dashboard = cls.env['binaryaid.hrms.dashboard']
    cls.questions = cls.env.ref('binaryaid_care_attendance.note_template_default').question_ids


@tagged('post_install', '-at_install')
class TestCareClock(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        setup_care(cls)

    def answers(self, complete=True):
        values = {}
        for question in self.questions:
            if question.required or complete:
                values[question.id] = 'no' if question.answer_type == 'yes_no' else 'Supported with routine'
        if not complete:
            values.pop(self.questions.filtered('required')[0].id)
        return values

    def test_clock_in_rules(self):
        board = self.dashboard.with_user(self.worker_user)
        self.assertEqual(board.get_overview()['clock']['action'], 'in')
        # Outside the clock radius: nothing is recorded and the dashboard gets the location to show in a pop-up.
        result = board.care_clock_in(self.shift.id, *FAR, 5)
        self.assertEqual(result['status'], 'out_of_range')
        self.assertEqual((result['place'], result['radius']), (self.location.name, 50))
        self.assertGreater(result['distance'], 50)
        self.assertIn('Move to', result['message'])
        self.assertFalse(self.shift.attendance_ids)
        with self.assertRaises(ValidationError):
            board.care_clock_in(self.shift.id, *NEAR, 500)  # imprecise reading
        with self.assertRaises(AccessError):
            self.dashboard.with_user(self.other_user).care_clock_in(self.shift.id, *NEAR, 5)
        self.assertEqual(board.care_clock_in(self.shift.id, *NEAR, 5)['status'], 'ok')
        self.assertEqual(board.care_clock_in(self.shift.id, *NEAR, 5)['status'], 'already')
        attendance = self.shift.attendance_ids
        self.assertEqual(len(attendance), 1)
        self.assertEqual(attendance.in_mode, 'binaryaid_gps')
        self.assertLess(attendance.binaryaid_in_distance_m, 50)
        self.assertTrue(board.care_is_signed_in())
        # Odoo's own top bar / kiosk check in has no shift location check and is refused.
        with self.assertRaises(UserError):
            self.other.with_user(self.other_user).sudo()._attendance_action_change()
        self.assertFalse(self.env['hr.attendance'].search([('employee_id', '=', self.other.id)]))
        self.assertEqual(board.get_overview()['clock']['action'], 'out')

    def test_window_and_missing_coordinates(self):
        later = self.shift.copy({'start': self.shift.start + timedelta(days=1), 'end': self.shift.end + timedelta(days=1)})
        later._roster_transition_write({'state': 'published', 'published_at': fields.Datetime.now()})
        with self.assertRaises(ValidationError):
            self.dashboard.with_user(self.worker_user).care_clock_in(later.id, *NEAR, 5)
        self.location.write({'latitude': 0, 'longitude': 0})
        with self.assertRaises(ValidationError):
            self.dashboard.with_user(self.worker_user).care_clock_in(self.shift.id, *NEAR, 5)

    def test_clock_out_note_draft_and_idempotency(self):
        board = self.dashboard.with_user(self.worker_user)
        board.care_clock_in(self.shift.id, *NEAR, 5)
        form = board.care_note_form(self.shift.id)
        self.assertEqual(len(form['questions']), len(self.questions))
        result = board.care_clock_out(self.shift.id, self.answers(complete=False), *NEAR, 5, 'tok-1')
        self.assertEqual(result['status'], 'error')
        note = self.env['binaryaid.care.shift.note'].search([('shift_id', '=', self.shift.id)])
        self.assertEqual(note.state, 'draft')
        self.assertTrue(note.answer_ids, 'draft answers are kept after a recoverable failure')
        result = board.care_clock_out(self.shift.id, self.answers(), *FAR, 5, 'tok-2')
        self.assertEqual(result['status'], 'error')
        self.assertFalse(self.shift.attendance_ids.check_out)
        self.assertEqual(board.care_clock_out(self.shift.id, self.answers(), *NEAR, 5, 'tok-3')['status'], 'ok')
        self.assertEqual(board.care_clock_out(self.shift.id, self.answers(), *NEAR, 5, 'tok-3')['status'], 'already')
        self.assertEqual(note.state, 'submitted')
        attendance = self.shift.attendance_ids
        self.assertTrue(attendance.check_out)
        self.assertEqual(attendance.check_out, max(note.clock_out_requested_on, attendance.check_in + timedelta(seconds=1)))
        self.assertEqual(self.shift.care_note_status, 'submitted')

    def test_note_protection_and_amendments(self):
        board = self.dashboard.with_user(self.worker_user)
        board.care_clock_in(self.shift.id, *NEAR, 5)
        board.care_note_form(self.shift.id)
        board.care_clock_out(self.shift.id, self.answers(), *NEAR, 5, 'tok-a')
        note = self.env['binaryaid.care.shift.note'].search([('shift_id', '=', self.shift.id)])
        with self.assertRaises(AccessError):
            note.with_user(self.worker_user).write({'state': 'draft'})
        with self.assertRaises(AccessError):
            note.sudo().answer_ids[0].write({'value': 'rewritten'})
        Amendment = self.env['binaryaid.care.shift.note.amendment']
        Amendment.with_user(self.worker_user).create({'note_id': note.id, 'reason': 'Typo', 'text': 'Correction'})
        self.assertEqual(len(note.amendment_ids), 1)
        with self.assertRaises(AccessError):
            Amendment.with_user(self.other_user).create({'note_id': note.id, 'reason': 'x', 'text': 'y'})
        # Roster administrators see note status but not the note itself.
        self.assertFalse(self.env['binaryaid.care.shift.note'].with_user(self.admin).search([('id', '=', note.id)]))
        self.assertEqual(self.env['binaryaid.work.shift'].with_user(self.admin).browse(self.shift.id).care_note_status, 'submitted')
        self.assertTrue(self.env['binaryaid.care.shift.note'].with_user(self.reviewer).search([('id', '=', note.id)]))

    def test_exception_route(self):
        board = self.dashboard.with_user(self.worker_user)
        with self.assertRaises(ValidationError):
            board.care_report_exception(self.shift.id, 'gps_failure', '', 'in')
        board.care_report_exception(self.shift.id, 'gps_failure', 'Phone GPS failed', 'in',
                                    fields.Datetime.to_string(self.shift.start))
        exception = self.env['binaryaid.care.attendance.exception'].search([('shift_id', '=', self.shift.id)])
        self.assertEqual(exception.state, 'submitted')
        with self.assertRaises(AccessError):
            exception.with_user(self.worker_user).action_approve()
        cards = {c['key']: c['value'] for c in self.dashboard.with_user(self.admin).get_overview()['cards']}
        self.assertEqual(cards['exceptions'], 1)
        exception.with_user(self.admin).action_approve()
        self.assertEqual(exception.state, 'approved')
        self.assertEqual(exception.attendance_id.check_in, self.shift.start)
        self.assertEqual(exception.attendance_id.in_mode, 'binaryaid_exception')
        out = board.care_report_exception(self.shift.id, 'missed_clock_out', 'Forgot', 'out',
                                          fields.Datetime.to_string(self.shift.end), answers=self.answers())
        self.assertEqual(out['status'], 'ok')
        second = self.env['binaryaid.care.attendance.exception'].search([('shift_id', '=', self.shift.id), ('clock_type', '=', 'out')])
        with self.assertRaises(UserError):
            second.with_user(self.admin).action_reject()
        second.with_user(self.admin).write({'review_note': 'Confirmed with client'})
        second.with_user(self.admin).action_approve()
        self.assertEqual(exception.attendance_id.check_out, self.shift.end)


    def test_missed_sign_in_on_ended_shift_is_closed(self):
        ended = self.env['binaryaid.work.shift'].with_user(self.admin).create({
            'name': 'Yesterday', 'employee_id': self.worker.id, 'client_id': self.client.id,
            'service_location_id': self.location.id, 'start': self.shift.start - timedelta(days=1),
            'end': self.shift.start - timedelta(days=1) + timedelta(hours=3)})
        ended._roster_transition_write({'state': 'published', 'published_at': ended.start - timedelta(days=1)})
        self.dashboard.with_user(self.worker_user).care_report_exception(
            ended.id, 'gps_failure', 'No GPS', 'in', fields.Datetime.to_string(ended.start))
        exception = self.env['binaryaid.care.attendance.exception'].search([('shift_id', '=', ended.id)])
        exception.with_user(self.admin).action_approve()
        self.assertEqual((exception.attendance_id.check_in, exception.attendance_id.check_out), (ended.start, ended.end))
        self.assertEqual(self.dashboard.with_user(self.worker_user).get_overview()['clock']['shift_id'], self.shift.id,
                         'the worker can still clock in to the current shift')


@tagged('post_install', '-at_install')
class TestCareIncidents(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        setup_care(cls)
        cls.category = cls.env.ref('binaryaid_care_attendance.incident_cat_injury')

    def report(self, user, client, **vals):
        values = {'client_id': client.id, 'location': 'Lounge', 'category_id': self.category.id, 'severity': 'high',
                  'description': 'Client slipped', 'immediate_action': 'First aid given', 'occurred_at': fields.Datetime.now()}
        values.update(vals)
        return self.env['binaryaid.care.incident'].with_user(user).create(values)

    def test_worker_reporting_and_restrictions(self):
        incident = self.report(self.worker_user, self.client)
        self.assertTrue(incident.name.startswith('INC/'))
        self.assertEqual(incident.shift_id, self.shift)
        self.assertTrue(incident.activity_ids, 'high severity incidents are escalated to reviewers')
        with self.assertRaises(AccessError):
            self.report(self.worker_user, self.other_client)
        with self.assertRaises(AccessError):
            incident.with_user(self.worker_user).write({'severity': 'low'})
        self.assertFalse(self.env['binaryaid.care.incident'].with_user(self.other_user).search([('id', '=', incident.id)]))
        self.assertFalse(self.env['binaryaid.care.incident'].with_user(self.admin).search([('id', '=', incident.id)]))
        reviewed = incident.with_user(self.reviewer)
        reviewed.action_review()
        self.env.cr.precommit.run()  # each review step is its own request in real use
        with self.assertRaises(UserError):
            reviewed.action_close()
        reviewed.write({'outcome': 'Family informed'})
        reviewed.action_close()
        self.assertEqual(incident.state, 'closed')
        self.env.cr.precommit.run()
        tracked = incident.sudo().message_ids.tracking_value_ids.filtered(lambda t: t.field_id.name == 'state')
        self.assertGreaterEqual(len(tracked), 2)

    def test_attachments_validated(self):
        good = self.env['ir.attachment'].with_user(self.worker_user).create({
            'name': 'photo.png', 'raw': b'\x89PNG\r\n\x1a\n' + b'0' * 32, 'res_model': 'binaryaid.care.incident'})
        incident = self.report(self.worker_user, self.client, attachment_ids=[(6, 0, good.ids)])
        self.assertEqual(incident.attachment_ids.res_id, incident.id)
        bad = self.env['ir.attachment'].with_user(self.worker_user).create({
            'name': 'run.png', 'raw': b'MZ' + b'0' * 32, 'res_model': 'binaryaid.care.incident'})
        with self.assertRaises(ValidationError):
            self.report(self.worker_user, self.client, attachment_ids=[(6, 0, bad.ids)])

    def test_reviewer_dashboard_hides_details(self):
        self.report(self.worker_user, self.client, description='Very private detail')
        overview = self.dashboard.with_user(self.reviewer).get_overview()
        self.assertNotIn('private', str(overview))
        action = self.dashboard.with_user(self.worker_user).quick_action('report_incident')
        self.assertEqual(action['res_model'], 'binaryaid.care.incident')


@tagged('post_install', '-at_install')
class TestCareClockBrowser(HttpCase):
    def test_worker_clock_in_note_and_clock_out(self):
        setup_care(self)
        self.browser_js('/odoo', """
          (async () => {
            // First tap from about 130 m away: a pop-up asks the worker to move to the shift location.
            navigator.geolocation.getCurrentPosition = (ok) => ok({coords: {latitude: -33.8700, longitude: 151.2093, accuracy: 6}});
            const wait = async (fn, label) => {
                for (let i = 0; i < 200; i++) {
                    const value = fn();
                    if (value) return value;
                    await new Promise(resolve => setTimeout(resolve, 100));
                }
                throw new Error('Timed out: ' + label);
            };
            const byText = (sel, text) => [...document.querySelectorAll(sel)].find(el => el.textContent.includes(text));
            const enabled = (text) => { const b = byText('.ba_clock_btn', text); return b && !b.disabled && b; };
            // Both buttons are always shown; only the one that applies is enabled.
            await wait(() => byText('.ba_clock_btn', 'Check In') && byText('.ba_clock_btn', 'Check Out'), 'both buttons');
            if (enabled('Check Out')) throw new Error('Check Out enabled before Check In');
            // A location that cannot be read: the message is a pop-up that closes with OK.
            const farGps = navigator.geolocation.getCurrentPosition;
            navigator.geolocation.getCurrentPosition = (ok, fail) => fail({code: 2});
            (await wait(() => enabled('Check In'), 'check in button')).click();
            const alert = await wait(() => byText('.modal', 'Check In not recorded'), 'error pop-up');
            byText('.modal button', 'OK').click();
            await wait(() => !document.querySelector('.modal'), 'error pop-up closed');
            if (document.querySelector('.ba_clock_card .alert')) throw new Error('Message left under the buttons');
            navigator.geolocation.getCurrentPosition = farGps;
            (await wait(() => enabled('Check In'), 'check in button')).click();
            const popup = await wait(() => document.querySelector('.modal .ba_location_dialog'), 'location pop-up');
            if (!popup.textContent.includes('Home') || !popup.textContent.includes('50 m')) throw new Error('Location details missing');
            byText('.modal button', 'OK').click();
            await wait(() => !document.querySelector('.modal'), 'pop-up closed');
            if (enabled('Check Out')) throw new Error('Checked in from outside the location');
            navigator.geolocation.getCurrentPosition = (ok) => ok({coords: {latitude: %s, longitude: %s, accuracy: 6}});
            (await wait(() => enabled('Check In'), 'check in button')).click();
            (await wait(() => enabled('Check Out'), 'check out button')).click();
            await wait(() => document.querySelector('.modal textarea'), 'note dialog');
            for (const area of document.querySelectorAll('.modal textarea')) {
                area.value = 'Supported with routine';
                area.dispatchEvent(new Event('input', {bubbles: true}));
            }
            for (const group of document.querySelectorAll('.modal [role="radiogroup"]')) {
                [...group.querySelectorAll('button')].find(b => b.textContent.trim() === 'No').click();
            }
            await new Promise(resolve => setTimeout(resolve, 200));
            byText('.modal button', 'Submit note and Check Out').click();
            await wait(() => !document.querySelector('.modal'), 'dialog closed after submission');
            await wait(() => !enabled('Check Out'), 'clock card updated');
            console.log('test successful');
          })().catch(error => console.error(error));
        """ % (-33.86885, 151.20935), login='att_worker', timeout=90)
        attendance = self.shift.attendance_ids
        self.assertTrue(attendance.check_out)
        self.assertEqual(self.env['binaryaid.care.shift.note'].search([('shift_id', '=', self.shift.id)]).state, 'submitted')
