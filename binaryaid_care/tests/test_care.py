import base64
from datetime import timedelta

from odoo import fields, http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged

from odoo.addons.binaryaid_work_scheduling.models.dashboard import name_parts

PDF = b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF'


@tagged('post_install', '-at_install')
class CareCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = new_test_user(cls.env, login='care_admin', tz='UTC', groups=','.join([
            'binaryaid_work_management.group_work_admin', 'hr.group_hr_user', 'hr_holidays.group_hr_holidays_user']))
        cls.alice_user = new_test_user(cls.env, login='care_alice', groups='binaryaid_work_management.group_work_user')
        cls.bob_user = new_test_user(cls.env, login='care_bob', groups='binaryaid_work_management.group_work_user')
        cls.alice = cls.env['hr.employee'].create({'name': 'Care Alice', 'user_id': cls.alice_user.id})
        cls.bob = cls.env['hr.employee'].create({'name': 'Care Bob', 'user_id': cls.bob_user.id})
        Client = cls.env['binaryaid.care.client'].with_user(cls.admin)
        cls.client = Client.create({'name': 'Client One', 'reference': 'P-001', 'care_requirements': '<p>Private needs</p>',
                                    'location_ids': [(0, 0, {'name': 'Home', 'latitude': -33.8688, 'longitude': 151.2093})]})
        cls.other_client = Client.create({'name': 'Client Two', 'reference': 'P-002'})
        cls.location = cls.client.location_ids
        cls.location.action_verify_coordinates()
        # ADC chooses which worker documents are required; the tests require the screening check.
        cls.env.ref('binaryaid_care.category_worker_screening').required = True
        # Required worker documents are satisfied for Alice so publication is not flagged.
        for document in cls.env['binaryaid.care.document'].search([('employee_id', '=', cls.alice.id)]):
            cls.env['binaryaid.care.document.version'].with_user(cls.admin)._create_version(
                document, PDF, 'cert.pdf', expiry_date=fields.Date.today() + timedelta(days=400))

    def shift(self, employee=None, client=None, days=2, **vals):
        start = fields.Datetime.now().replace(microsecond=0) + timedelta(days=days)
        values = {'name': 'Care shift', 'employee_id': (employee or self.alice).id, 'start': start,
                  'end': start + timedelta(hours=4), 'client_id': (client or self.client).id}
        if (client or self.client) == self.client:
            values['service_location_id'] = self.location.id
        values.update(vals)
        return self.env['binaryaid.work.shift'].with_user(self.admin).create(values)


class TestCareClients(CareCase):
    def test_client_documents_reference_and_archive(self):
        self.assertEqual(len(self.client.document_ids), 8)
        with self.assertRaises(Exception), self.cr.savepoint():
            self.env['binaryaid.care.client'].create({'name': 'Dup', 'reference': 'P-001'})
        contact = self.env['binaryaid.care.client.contact'].create({
            'client_id': self.client.id, 'name': 'Rep', 'email': 'rep@example.com', 'contact_type': 'representative'})
        contact.with_user(self.admin).action_grant_portal()
        self.assertTrue(contact.user_id.share and contact.user_id.active)
        self.client.with_user(self.admin).write({'active': False})
        self.assertFalse(contact.user_id.with_context(active_test=False).active)

    def test_location_coordinates_and_verification(self):
        self.assertTrue(self.location.coordinates_verified)
        self.location.with_user(self.admin).latitude = -33.87
        self.assertFalse(self.location.coordinates_verified)
        with self.assertRaises(ValidationError):
            self.location.radius_m = 0

    def test_worker_sees_only_rostered_clients(self):
        Client = self.env['binaryaid.care.client'].with_user(self.alice_user)
        self.assertFalse(Client.search([]))
        self.shift().action_publish()
        self.assertEqual(Client.search([]), self.client)
        with self.assertRaises(AccessError):
            Client.browse(self.client.id).care_requirements
        with self.assertRaises(AccessError):
            Client.browse(self.other_client.id).name
        self.assertFalse(self.env['binaryaid.care.client'].with_user(self.bob_user).search([]))


class TestCareDocuments(CareCase):
    def test_upload_validation_and_versions(self):
        document = self.client.document_ids[0]
        Version = self.env['binaryaid.care.document.version'].with_user(self.admin)
        for data, name in ((PDF, 'file.exe'), (b'not a pdf', 'file.pdf'), (b'MZ\x90\x00', 'file.doc')):
            with self.assertRaises(ValidationError):
                Version._create_version(document, data, name)
        expiry = fields.Date.today() + timedelta(days=10)
        first = Version._create_version(document, PDF, 'plan.pdf', expiry_date=expiry)
        second = Version._create_version(document, PDF, 'plan-v2.pdf', expiry_date=expiry + timedelta(days=365))
        self.assertEqual((first.version, second.version, first.state), (1, 2, 'approved'))
        self.assertEqual(document.current_version_id, second)
        with self.assertRaises(AccessError):
            first.with_user(self.admin).write({'note': 'changed'})
        with self.assertRaises(AccessError):
            first.unlink()

    def test_worker_upload_needs_hr_approval(self):
        document = self.env['binaryaid.care.document'].search([('employee_id', '=', self.bob.id)], limit=1)
        version = self.env['binaryaid.care.document.version'].with_user(self.bob_user)._create_version(
            document, PDF, 'renewal.pdf', expiry_date=fields.Date.today() + timedelta(days=300))
        self.assertEqual(version.state, 'submitted')
        self.assertFalse(document.current_version_id)
        with self.assertRaises(AccessError):
            version.with_user(self.bob_user).action_approve()
        with self.assertRaises(AccessError):
            self.env['binaryaid.care.document.version'].with_user(self.bob_user)._create_version(
                self.client.document_ids[0], PDF, 'x.pdf')
        version.with_user(self.admin).action_approve()
        self.assertEqual(document.current_version_id, version)
        own = self.env['binaryaid.care.document'].with_user(self.bob_user).search([])
        self.assertTrue(own and all(d.employee_id == self.bob for d in own))

    def test_expiry_states(self):
        document = self.client.document_ids[0]
        self.assertEqual(document.expiry_state, 'missing')
        self.env['binaryaid.care.document.version'].with_user(self.admin)._create_version(
            document, PDF, 'a.pdf', expiry_date=fields.Date.today() - timedelta(days=1))
        self.assertEqual(document.expiry_state, 'expired')
        self.assertIn(document, self.env['binaryaid.care.document'].search([('expiry_state', '=', 'expired')]))


class TestCareRoster(CareCase):
    def test_publish_rules_and_warnings(self):
        shift = self.shift()
        self.assertEqual(shift.timezone, self.location.timezone)
        self.assertIn('Home', shift.location)
        shift.action_publish()
        # Bob lacks required documents: publication needs a recorded manager review.
        flagged = self.shift(employee=self.bob, days=3)
        with self.assertRaises(ValidationError):
            flagged.action_publish()
        flagged.review_note = 'Documents sighted, upload pending'
        flagged.action_publish()
        unverified = self.client.location_ids.create({'client_id': self.client.id, 'name': 'Centre'})
        draft = self.shift(days=4, service_location_id=unverified.id, review_note=False)
        self.assertTrue(any('coordinates' in w for w in draft._review_warnings()))
        self.other_client.status = 'on_hold'
        with self.assertRaises(ValidationError):
            self.shift(client=self.other_client, days=5, review_note='ok').action_publish()
        with self.assertRaises(ValidationError):
            self.shift(client=self.other_client, service_location_id=self.location.id)

    def test_concurrent_edit_protection(self):
        shift = self.shift()
        token = shift.binaryaid_revision_token
        shift.write({'name': 'First editor', 'binaryaid_revision_token': token})
        with self.assertRaises(UserError):
            shift.write({'name': 'Second editor', 'binaryaid_revision_token': token})
        self.assertEqual(shift.name, 'First editor')

    def test_request_to_shift_flow(self):
        request = self.env['binaryaid.care.client.request'].create({
            'client_id': self.client.id, 'support_needs': 'Help with shopping', 'location_id': self.location.id,
            'preferred_date_from': fields.Date.today() + timedelta(days=3), 'preferred_start_time': 10, 'preferred_end_time': 13})
        self.assertTrue(request.name.startswith('REQ/'))
        Request = request.with_user(self.admin)
        with self.assertRaises(UserError):
            Request.action_create_shift()
        with self.assertRaises(UserError):
            Request.action_decline()
        Request.action_approve()
        context = Request.action_create_shift()['context']
        shift = self.env['binaryaid.work.shift'].with_user(self.admin).with_context(**context).create({'employee_id': self.alice.id})
        self.assertEqual((shift.client_id, shift.client_request_id, shift.service_location_id), (self.client, request, self.location))
        self.assertAlmostEqual((shift.end - shift.start).total_seconds(), 3 * 3600)
        shift.action_publish()
        self.assertEqual(request.state, 'scheduled')
        with self.assertRaises(AccessError):
            request.with_user(self.alice_user).action_approve()

    def test_leave_requires_staffing_resolution(self):
        shift = self.shift(days=3)
        shift.action_publish()
        leave_type = self.env['hr.leave.type'].create({'name': 'Care leave', 'requires_allocation': False, 'leave_validation_type': 'hr'})
        day = shift.start.date()
        leave = self.env['hr.leave'].create({'holiday_status_id': leave_type.id, 'employee_id': self.alice.id,
                                             'request_date_from': day, 'request_date_to': day})
        self.assertEqual(leave.binaryaid_conflict_count, 1)
        with self.assertRaises(UserError):
            leave.with_user(self.admin).action_approve()
        shift.with_user(self.admin).write({'change_reason': 'Covering leave'})
        shift.with_user(self.admin).action_cancel()
        leave.with_user(self.admin).action_approve()
        self.assertEqual(leave.state, 'validate')


class TestCareMessagesAndProfile(CareCase):
    def test_announcements(self):
        message = self.env['binaryaid.care.announcement'].with_user(self.admin).create({
            'title': 'Roster reminder', 'body': '<p>Check your shifts</p>', 'audience': 'employees',
            'employee_ids': [(6, 0, (self.alice | self.bob).ids)], 'requires_ack': True})
        with self.assertRaises(UserError):
            message.action_send()
        message.confirm_no_sensitive = True
        message.action_send()
        self.assertEqual(message.recipient_count, 2)
        mine = self.env['binaryaid.care.announcement'].with_user(self.alice_user).browse(message.id)
        mine.action_acknowledge()
        self.assertEqual((message.read_count, message.ack_count), (1, 1))
        overview = self.env['binaryaid.hrms.dashboard'].with_user(self.bob_user).get_overview()
        self.assertEqual(overview['messages']['unread'], 1)
        self.assertIn('messages', {card['key'] for card in overview['cards']})
        draft = self.env['binaryaid.care.announcement'].with_user(self.admin).create({'title': 'Draft', 'body': '<p>x</p>'})
        self.assertFalse(self.env['binaryaid.care.announcement'].with_user(self.alice_user).search([('id', '=', draft.id)]))

    def test_profile_limits_and_deactivation(self):
        writeable = self.env['res.users'].SELF_WRITEABLE_FIELDS
        self.assertNotIn('employee_bank_account_ids', writeable)
        self.assertNotIn('job_title', writeable)
        self.assertIn('private_phone', writeable)
        self.bob.with_user(self.admin).write({'active': False})
        self.assertFalse(self.bob_user.active)

    def test_dashboard_requests_and_quick_actions(self):
        request = self.env['binaryaid.care.client.request'].create({
            'client_id': self.client.id, 'support_needs': 'Confidential detail', 'preferred_date_from': fields.Date.today()})
        dashboard = self.env['binaryaid.hrms.dashboard'].with_user(self.admin)
        data = dashboard.get_overview()
        tab = next(t for t in data['attention'] if t['key'] == 'client_requests')
        item = next(i for i in tab['items'] if i['id'] == request.id)
        self.assertNotIn('Confidential', str(item))
        self.assertIn('add_client', {a['key'] for a in data['quick_actions']})
        self.assertEqual(dashboard.quick_action('add_client')['res_model'], 'binaryaid.care.client')
        dashboard.item_action('request', request.id, 'approve')
        self.assertEqual(request.state, 'approved')
        self.assertEqual(dashboard.item_action('request', request.id, 'create_shift')['target'], 'new')
        with self.assertRaises(AccessError):
            self.env['binaryaid.hrms.dashboard'].with_user(self.alice_user).item_action('request', request.id, 'approve')


@tagged('post_install', '-at_install')
class TestCarePortal(HttpCase):
    def test_portal_request_submission_and_isolation(self):
        client = self.env['binaryaid.care.client'].create({'name': 'Portal Client', 'reference': 'P-PORTAL'})
        other = self.env['binaryaid.care.client'].create({'name': 'Hidden Client', 'reference': 'P-HIDDEN'})
        hidden = self.env['binaryaid.care.client.request'].create({
            'client_id': other.id, 'support_needs': 'Hidden', 'preferred_date_from': fields.Date.today()})
        contact = self.env['binaryaid.care.client.contact'].create({
            'client_id': client.id, 'name': 'Portal Rep', 'email': 'portal.rep@example.com'})
        contact.action_grant_portal()
        contact.user_id.password = 'portal-rep-pass'
        self.authenticate('portal.rep@example.com', 'portal-rep-pass')
        page = self.url_open('/my/support-requests/new')
        self.assertEqual(page.status_code, 200)
        response = self.url_open('/my/support-requests/new', data={
            'csrf_token': http.Request.csrf_token(self), 'client_id': other.id, 'support_needs': 'Should fail',
            'preferred_date_from': str(fields.Date.today() + timedelta(days=1))})
        self.assertIn('Choose the client', response.text)
        self.url_open('/my/support-requests/new', data={
            'csrf_token': http.Request.csrf_token(self), 'client_id': client.id, 'support_needs': 'Weekly shopping support',
            'preferred_date_from': str(fields.Date.today() + timedelta(days=2)), 'preferred_start_time': '10:00',
            'preferred_end_time': '12:30'})
        created = self.env['binaryaid.care.client.request'].search([('client_id', '=', client.id)])
        self.assertEqual(len(created), 1)
        self.assertEqual(created.preferred_end_time, 12.5)
        listing = self.url_open('/my/support-requests').text
        self.assertIn(created.name, listing)
        self.assertNotIn(hidden.name, listing)
        self.assertNotIn(hidden.name, self.url_open('/my/support-requests/%s' % hidden.id).text)
        # Employee HR files, shifts and attendance are not reachable for client logins.
        for model in ('hr.employee', 'binaryaid.work.shift', 'hr.attendance'):
            with self.assertRaises(AccessError):
                self.env[model].with_user(contact.user_id).search([])


class TestCareGaps(CareCase):
    def test_unfilled_shift_lifecycle(self):
        shift = self.env['binaryaid.work.shift'].with_user(self.admin).create({
            'name': 'Open shift', 'client_id': self.client.id, 'service_location_id': self.location.id,
            'start': fields.Datetime.now() + timedelta(days=1), 'end': fields.Datetime.now() + timedelta(days=1, hours=3)})
        self.assertTrue(shift.is_unfilled)
        dashboard = self.env['binaryaid.hrms.dashboard'].with_user(self.admin)
        data = dashboard.get_overview()
        tab = next(t for t in data['attention'] if t['key'] == 'unfilled')
        self.assertIn(shift.id, [i['id'] for i in tab['items']])
        self.assertNotIn(shift.id, [i['id'] for t in data['attention'] if t['key'] == 'unpublished' for i in t['items']])
        self.assertEqual(name_parts('[DEMO] Mei Lin Zhang'), ['Mei', 'Lin', 'Zhang'])
        chips = [c for day in data['coverage']['days'] for c in day['items'] if c['id'] == shift.id]
        self.assertTrue(chips and chips[0]['unfilled'] and chips[0]['client'] == self.client.name)
        self.assertEqual(dashboard.item_action('shift', shift.id, 'open')['views'][0][0],
                         self.env.ref('binaryaid_care.view_shift_quick_form').id)
        with self.assertRaises(ValidationError):
            shift.action_publish()
        self.assertEqual(shift.state, 'draft', 'the draft is kept when publication fails')
        shift.employee_id = self.alice
        shift.action_publish()
        self.assertEqual((shift.state, shift.is_unfilled), ('published', False))

    def test_worker_home_navigation_plan_and_leave(self):
        shift = self.shift(instructions='Prepare lunch and go for a walk')
        shift.action_publish()
        leave_type = self.env['hr.leave.type'].create({'name': 'Home leave', 'requires_allocation': False,
                                                      'leave_validation_type': 'hr'})
        day = fields.Date.today() + timedelta(days=20)
        leave = self.env['hr.leave'].with_user(self.alice_user).create({
            'holiday_status_id': leave_type.id, 'employee_id': self.alice.id, 'request_date_from': day, 'request_date_to': day})
        board = self.env['binaryaid.hrms.dashboard'].with_user(self.alice_user)
        data = board.get_overview()
        self.assertEqual([n['key'] for n in data['worker_nav']],
                         ['work_schedule', 'my_incidents', 'team_messages', 'my_leave', 'profile']
                         if 'binaryaid.care.incident' in self.env else ['work_schedule', 'team_messages', 'my_leave', 'profile'])
        item = next(s for s in data['schedule']['shifts'] if s['id'] == shift.id)
        self.assertEqual(item['plan'], 'Prepare lunch and go for a walk')
        self.assertTrue(item['map_url'])
        mine = next(l for l in data['my_leave'] if l['id'] == leave.id)
        if mine['can_cancel']:
            self.assertEqual(board.item_action('my_leave', leave.id, 'cancel')['res_model'], 'hr.holidays.cancel.leave')
        with self.assertRaises(AccessError):
            self.env['binaryaid.hrms.dashboard'].with_user(self.bob_user).item_action('my_leave', leave.id, 'cancel')

    def test_document_slots_for_existing_records(self):
        employee = self.env['hr.employee'].with_context(binaryaid_skip=True).sudo().create({'name': 'Legacy worker'})
        self.env['binaryaid.care.document'].search([('employee_id', '=', employee.id)]).unlink()
        from odoo.addons.binaryaid_care import _prepare_document_slots
        _prepare_document_slots(self.env)
        worker_categories = self.env['binaryaid.care.document.category'].search_count([('applies_to', '=', 'employee')])
        self.assertEqual(len(employee.binaryaid_document_ids), worker_categories)
        category = self.env['binaryaid.care.document.category'].create({'name': 'Vaccination record', 'applies_to': 'employee'})
        self.assertIn(category, employee.binaryaid_document_ids.category_id)
        missing = self.env['binaryaid.care.document'].search([('employee_id', '=', employee.id), ('expiry_state', '=', 'missing')])
        self.assertEqual(len(missing), worker_categories + 1)
