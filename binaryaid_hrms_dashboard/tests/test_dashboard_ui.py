from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import HttpCase, new_test_user, tagged
from odoo.tests.common import ChromeBrowser


@tagged('post_install', '-at_install')
class TestDashboardUI(HttpCase):
    """Check the real dashboard with role-specific data at desktop/mobile sizes."""

    def _check_workspace(self, manager=False, width=1366):
        group = 'group_work_admin' if manager else 'group_work_user'
        user = new_test_user(self.env, login='ui_workspace_user', name='Alex Morgan',
                             groups='binaryaid_work_management.' + group)
        employee = self.env['hr.employee'].create({'name': 'Alex Morgan', 'user_id': user.id})
        tasks = self.env['project.task'].create([
            {'name': name, 'binaryaid_employee_id': employee.id}
            for name in ['Review onboarding documents', 'Prepare the weekly operations report', 'Update employee records']])
        tasks[0].action_binaryaid_complete()
        if 'binaryaid.work.shift' in self.env:
            now = fields.Datetime.now()
            shift = self.env['binaryaid.work.shift'].create({
                'name': 'Operations & team support', 'employee_id': employee.id,
                'start': now - timedelta(minutes=30), 'end': now + timedelta(hours=7),
                'unpaid_break_minutes': 30, 'location': 'Sydney office',
                'task_ids': [(6, 0, tasks.ids)]})
            shift.action_publish()
        original = ChromeBrowser._wait_code_ok

        def check_and_capture(browser, *args, **kwargs):
            browser._websocket_request('Emulation.setDeviceMetricsOverride', params={
                'width': width, 'height': 1100 if width > 600 else 844,
                'deviceScaleFactor': 1, 'mobile': False})
            result = original(browser, *args, **kwargs)
            browser.take_screenshot(prefix='dashboard_').result(timeout=10)
            return result

        with patch.object(ChromeBrowser, '_wait_code_ok', check_and_capture):
            self.browser_js('/odoo', """
              (async () => {
                for (let i = 0; i < 200 && !document.querySelector('.ba_work_table'); i++) {
                    await new Promise(resolve => setTimeout(resolve, 100));
                }
                const dashboard = document.querySelector('.ba_dashboard');
                if (!dashboard || !dashboard.textContent.includes('Review onboarding documents')) {
                    throw new Error('Work items did not load');
                }
                if (!dashboard.querySelector('[role="progressbar"]')) {
                    throw new Error('Monthly progress is missing');
                }
                if (dashboard.scrollWidth > dashboard.clientWidth + 1) {
                    throw new Error('Dashboard overflows horizontally');
                }
                const refresh = dashboard.querySelector('.ba_refresh');
                refresh.focus();
                if (document.activeElement !== refresh) throw new Error('Refresh is not keyboard accessible');
                refresh.blur();
                console.log('test successful');
              })().catch(error => console.error(error));
            """, login=user.login, timeout=60)

    def test_manager_desktop_workspace(self):
        self._check_workspace(manager=True)

    def test_employee_mobile_workspace(self):
        self._check_workspace(width=390)
