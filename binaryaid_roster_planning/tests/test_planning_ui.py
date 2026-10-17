from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged, new_test_user


@tagged('post_install', '-at_install')
class TestRosterPlanningUI(HttpCase):
    def test_manager_generation_workflow(self):
        user = new_test_user(self.env, login='planning_ui', groups='binaryaid_work_management.group_work_admin')
        employee = self.env['hr.employee'].create({'name': 'Roster UI Employee', 'user_id': user.id})
        today = fields.Date.context_today(self)
        monday = today - timedelta(days=today.weekday())
        template = self.env['binaryaid.roster.template'].with_user(user).create({
            'name': 'Office support schedule', 'anchor_date': monday,
            'common_tasks': 'Prepare workspace\nComplete daily handover'})
        template.action_add_workweek()
        template.action_release()
        assignment = self.env['binaryaid.roster.assignment'].with_user(user).create({
            'employee_id': employee.id, 'template_id': template.id,
            'date_start': today, 'date_end': today + timedelta(days=14)})
        assignment.action_activate()
        action = self.env.ref('binaryaid_roster_planning.action_roster_assignment')
        self.browser_js('/odoo/action-%s/%s' % (action.id, assignment.id), """
          (async () => {
            const waitFor = async (selector) => {
                for (let i = 0; i < 200; i++) {
                    const element = document.querySelector(selector);
                    if (element) return element;
                    await new Promise(resolve => setTimeout(resolve, 100));
                }
                throw new Error('Missing planning element: ' + selector);
            };
            (await waitFor('button[name="action_generate"]')).click();
            const generate = await waitFor('.o_dialog button[name="action_generate"]');
            generate.click();
            const row = await waitFor('.o_data_row');
            if (!document.querySelector('.o_list_view').textContent.includes('Day shift')) {
                throw new Error('Generated shifts are missing');
            }
            row.querySelector('.o_data_cell').click();
            const publish = await waitFor('button[name="action_publish"]');
            publish.click();
            for (let i = 0; i < 200; i++) {
                if (document.querySelector('.o_form_view').textContent.includes('Prepare workspace')) {
                    console.log('test successful');
                    return;
                }
                await new Promise(resolve => setTimeout(resolve, 100));
            }
            throw new Error('Published shift tasks did not appear');
          })().catch(error => console.error(error));
        """, login=user.login, timeout=80)
