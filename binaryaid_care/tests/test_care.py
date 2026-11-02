import base64
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged

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
        cls.client = Client.create({'name': 'Client One', 'phone': '0400 000 001', 'service_location': '14 George St, Parramatta',
                                    'latitude': -33.8688, 'longitude': 151.2093})
        cls.other_client = Client.create({'name': 'Client Two'})
        cls.location = cls.client.location_ids
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
    def test_simple_client_form(self):
        client = self.client.with_user(self.admin)
        self.assertEqual((client.service_location, client.timezone, client.radius_m),
                         ('14 George St, Parramatta', 'Australia/Sydney', 50))
        self.assertEqual(len(client.location_ids), 1)
        client.write({'service_location': '22 High St, Penrith', 'latitude': -33.75, 'radius_m': 80})
        self.assertEqual(len(client.location_ids), 1, 'the form edits the one service location')
        self.assertEqual((self.location.name, self.location.latitude, self.location.radius_m), ('22 High St, Penrith', -33.75, 80))
        with self.assertRaises(ValidationError):
            client.radius_m = 0
        client.write({'contact_name': 'Helen', 'contact_phone': '0411 000 000', 'contact_email': 'helen@example.com'})
        self.assertEqual((client.contact_name, client.contact_phone), ('Helen', '0411 000 000'))

    def test_care_plans(self):
        Plan = self.env['binaryaid.care.plan'].with_user(self.admin)
        morning, meals = Plan.create([
            {'name': 'Morning routine', 'line_ids': [(0, 0, {'name': 'Personal care'}), (0, 0, {'name': 'Medication prompt'})]},
            {'name': 'Meal preparation'}])
        self.assertEqual(morning.line_ids.mapped('name'), ['Personal care', 'Medication prompt'])
        morning.line_ids = [(0, 0, {'name': 'Breakfast'})]
        self.assertEqual(len(morning.line_ids), 3)
        with self.assertRaises(AccessError):
            self.env['binaryaid.care.plan.line'].with_user(self.alice_user).create({'plan_id': morning.id, 'name': 'x'})
        client = self.client.with_user(self.admin)
        client.plan_ids = [(6, 0, (morning | meals).ids)]
        self.assertEqual(client.service_ids.mapped('name'), ['Personal care', 'Medication prompt', 'Breakfast'])
        self.assertEqual(client.service_ids.plan_id, morning)
        client.service_ids = [(0, 0, {'name': 'Gardening'})]
        client.plan_ids = [(3, morning.id)]
        self.assertEqual(client.service_ids.mapped('name'), ['Gardening'], 'extra lines stay, plan services go')
        client.plan_ids = [(4, morning.id)]
        self.assertEqual(len(client.service_ids), 4)
        client.plan_ids = [(4, morning.id)]
        self.assertEqual(len(client.service_ids), 4, 'no duplicate services')
        # The form fills the services as soon as a plan is chosen.
        from odoo.tests import Form
        with Form(self.env['binaryaid.care.client'].with_user(self.admin)) as form:
            form.name = 'Form client'
            form.plan_ids.add(morning)
            self.assertEqual(len(form.service_ids), 3)
            with form.service_ids.new() as line:
                line.name = 'Extra walk'
        self.assertEqual(len(form.record.service_ids), 4)
        with self.assertRaises(AccessError):
            client.service_ids.with_user(self.alice_user).read(['name'])
        shift = self.shift()
        self.assertEqual(shift.client_plan_ids, self.client.plan_ids)
        action = self.env.ref('binaryaid_care.action_care_plan')
        self.assertEqual(action.view_mode, 'list,form')
        self.env['binaryaid.care.plan'].with_user(self.admin).get_views([(False, 'list'), (False, 'form')])

    def test_client_documents(self):
        Document = self.env['binaryaid.care.client.document'].with_user(self.admin)
        files = Document.create([{'client_id': self.client.id, 'name': 'plan-%s.pdf' % n, 'file': base64.b64encode(PDF)}
                                 for n in range(3)])
        self.assertEqual(len(self.client.document_ids), 3)
        preview, download = files[0].action_preview(), files[0].action_download()
        self.assertIn('download=false', preview['url'])
        self.assertEqual(preview['target'], 'new')
        self.assertIn('download=true', download['url'])
        reviewer = new_test_user(self.env, login='care_reviewer_docs', groups='binaryaid_care.group_care_reviewer')
        self.assertEqual(Document.with_user(reviewer).search([('client_id', '=', self.client.id)]), files)
        with self.assertRaises(AccessError):
            Document.with_user(self.alice_user).search([])
        files[0].unlink()
        self.assertEqual(len(self.client.document_ids), 2)

    def test_worker_sees_only_rostered_clients(self):
        Client = self.env['binaryaid.care.client'].with_user(self.alice_user)
        self.assertFalse(Client.search([]))
        self.shift().action_publish()
        self.assertEqual(Client.search([]), self.client)
        with self.assertRaises(AccessError):
            Client.browse(self.client.id).phone
        with self.assertRaises(AccessError):
            Client.browse(self.other_client.id).name
        self.assertFalse(self.env['binaryaid.care.client'].with_user(self.bob_user).search([]))
        with self.assertRaises(Exception), self.cr.savepoint():
            self.env['binaryaid.care.client'].create([{'name': 'A', 'reference': 'P-1'}, {'name': 'B', 'reference': 'P-1'}])


class TestCareDocuments(CareCase):
    def test_upload_validation_and_versions(self):
        document = self.bob.binaryaid_document_ids[0]
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
                self.alice.binaryaid_document_ids[0], PDF, 'x.pdf')
        version.with_user(self.admin).action_approve()
        self.assertEqual(document.current_version_id, version)
        own = self.env['binaryaid.care.document'].with_user(self.bob_user).search([])
        self.assertTrue(own and all(d.employee_id == self.bob for d in own))

    def test_expiry_states(self):
        document = self.bob.binaryaid_document_ids[0]
        self.assertEqual(document.expiry_state, 'missing')
        self.env['binaryaid.care.document.version'].with_user(self.admin)._create_version(
            document, PDF, 'a.pdf', expiry_date=fields.Date.today() - timedelta(days=1))
        self.assertEqual(document.expiry_state, 'expired')
        self.assertIn(document, self.env['binaryaid.care.document'].search([('expiry_state', '=', 'expired')]))


class TestCareRoster(CareCase):
    def test_publish_rules_and_warnings(self):
        shift = self.shift()
        self.assertEqual(shift.timezone, self.location.timezone)
        self.assertEqual(shift.location, '14 George St, Parramatta')
        shift.action_publish()
        # Bob lacks required documents: publication needs a recorded manager review.
        flagged = self.shift(employee=self.bob, days=3)
        with self.assertRaises(ValidationError):
            flagged.action_publish()
        flagged.review_note = 'Documents sighted, upload pending'
        flagged.action_publish()
        no_coordinates = self.client.location_ids.create({'client_id': self.client.id, 'name': 'Centre'})
        draft = self.shift(days=4, service_location_id=no_coordinates.id, review_note=False)
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

    def test_leave_requires_staffing_resolution(self):
        shift = self.shift(days=3)
        shift.action_publish()
        leave_type = self.env['hr.leave.type'].create({'name': 'Care leave', 'requires_allocation': False, 'leave_validation_type': 'hr'})
        # Leave around the shift day, so the overlap holds whatever time of day the test runs.
        day = shift.start.date()
        leave = self.env['hr.leave'].create({'holiday_status_id': leave_type.id, 'employee_id': self.alice.id,
                                             'request_date_from': day - timedelta(days=1),
                                             'request_date_to': day + timedelta(days=1)})
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
        form = self.env['hr.employee'].with_user(self.admin).get_views([(False, 'form')])['views']['form']['arch']
        self.assertNotIn('Care employment', form)
        self.assertIn('action_binaryaid_documents', form)

    def test_care_operations_menus(self):
        root = self.env.ref('binaryaid_care.menu_care_root')
        menus = self.env['ir.ui.menu'].with_user(self.admin).search([('parent_id', '=', root.id)])
        self.assertEqual(menus.mapped('name'), ['Clients', 'Plans', 'All Shifts'])
        action = self.env.ref('binaryaid_care.menu_care_shifts').action
        self.assertEqual(action.res_model, 'binaryaid.work.shift')
        self.assertEqual(action.view_mode.split(',')[0], 'list')
        self.assertIn(root.id, self.env['ir.ui.menu'].with_user(self.admin)._visible_menu_ids())
        self.assertNotIn(root.id, self.env['ir.ui.menu'].with_user(self.alice_user)._visible_menu_ids())

    def test_dashboard_quick_actions(self):
        dashboard = self.env['binaryaid.hrms.dashboard'].with_user(self.admin)
        data = dashboard.get_overview()
        keys = {a['key'] for a in data['quick_actions']}
        self.assertIn('add_client', keys)
        self.assertFalse({key for key in keys if 'request' in key}, 'no client request review on the dashboard')
        self.assertNotIn('account_url', data)
        self.assertEqual(dashboard.quick_action('add_client')['res_model'], 'binaryaid.care.client')


class TestCareGaps(CareCase):
    def test_unfilled_shift_lifecycle(self):
        shift = self.env['binaryaid.work.shift'].with_user(self.admin).create({
            'name': 'Open shift', 'client_id': self.client.id, 'service_location_id': self.location.id,
            'start': fields.Datetime.now() + timedelta(days=1), 'end': fields.Datetime.now() + timedelta(days=1, hours=3)})
        self.assertTrue(shift.is_unfilled)
        dashboard = self.env['binaryaid.hrms.dashboard'].with_user(self.admin)
        data = dashboard.get_overview()
        cards = {card['key']: card['value'] for card in data['cards']}
        self.assertEqual(cards['unfilled'], 1)
        self.assertNotIn('attention', data)
        self.assertEqual(name_parts('[DEMO] Mei Lin Zhang'), ['Mei', 'Lin', 'Zhang'])
        card = next(r for r in dashboard.day_board(str(shift.start.date()))['rows'] if r['id'] == shift.id)
        self.assertTrue(card['unfilled'] and card['client'] == self.client.name)
        self.assertEqual(card['location'], '14 George St, Parramatta')
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
