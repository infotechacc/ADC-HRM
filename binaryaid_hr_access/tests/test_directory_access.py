from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, tagged, new_test_user


@tagged('post_install', '-at_install')
class TestDirectoryAccess(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee_user = new_test_user(cls.env, login='directory_denied', password='directory_denied', groups='base.group_user')
        cls.officer = new_test_user(cls.env, login='directory_officer', password='directory_officer', groups='hr.group_hr_user')
        cls.employee = cls.env['hr.employee'].create({'name': 'Directory Access Test', 'user_id': cls.employee_user.id})

    def test_menu_and_directory_data_requests(self):
        menu = self.env.ref('hr.menu_hr_employee')
        self.assertNotIn(menu.id, self.env['ir.ui.menu'].with_user(self.employee_user)._visible_menu_ids())
        public = self.env['hr.employee.public'].with_user(self.employee_user)
        for operation in (
            lambda: public.get_view(view_type='form'),
            lambda: public.get_views([(False, 'kanban')]),
            lambda: public.web_search_read([], {'name': {}}),
            lambda: public.browse(self.employee.id).web_read({'name': {}}),
            lambda: public.web_read_group([], ['department_id'], ['department_id']),
        ):
            with self.assertRaises(AccessError):
                operation()
        # Existing identity lookups remain usable by unrelated business workflows.
        self.assertEqual(public.browse(self.employee.id).name, self.employee.name)

    def test_hr_roles_and_permission_revocation(self):
        public = self.env['hr.employee.public'].with_user(self.officer)
        self.assertTrue(public.web_search_read([('id', '=', self.employee.id)], {'name': {}})['records'])
        self.assertTrue(public.get_views([(False, 'list')]))
        self.assertIn(self.env.ref('hr.menu_hr_employee').id,
                      self.env['ir.ui.menu'].with_user(self.officer)._visible_menu_ids())
        self.officer.write({'group_ids': [Command.set(self.env.ref('base.group_user').ids)]})
        with self.assertRaises(AccessError):
            public.browse(self.employee.id).web_read({'name': {}})

    def test_direct_action_load(self):
        action_id = self.env.ref('hr.hr_employee_public_action').id
        self.authenticate('directory_denied', 'directory_denied')
        for value in (action_id, 'hr.hr_employee_public_action'):
            response = self.url_open('/web/action/load', json={
                'jsonrpc': '2.0', 'method': 'call', 'params': {'action_id': value}, 'id': 1}).json()
            self.assertEqual(response['error']['data']['name'], 'odoo.exceptions.AccessError')
        self.authenticate('directory_officer', 'directory_officer')
        response = self.url_open('/web/action/load', json={
            'jsonrpc': '2.0', 'method': 'call', 'params': {'action_id': action_id}, 'id': 2}).json()
        self.assertEqual(response['result']['res_model'], 'hr.employee.public')
