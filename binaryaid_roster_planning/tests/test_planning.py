from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import Form, TransactionCase, tagged, new_test_user
from odoo.tests.common import freeze_time



@tagged('post_install', '-at_install')
@freeze_time('2026-10-17 03:00:00')
class TestRosterPlanning(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login='planning_manager', groups='binaryaid_work_management.group_work_admin,hr_attendance.group_hr_attendance_manager')
        cls.alice = new_test_user(cls.env, login='planning_alice', groups='binaryaid_work_management.group_work_user', tz='Australia/Sydney')
        cls.bob = new_test_user(cls.env, login='planning_bob', groups='binaryaid_work_management.group_work_user')
        cls.employee = cls.env['hr.employee'].create({'name': 'Planning Alice', 'user_id': cls.alice.id})
        cls.other = cls.env['hr.employee'].create({'name': 'Planning Bob', 'user_id': cls.bob.id})
        cls.policy = cls.env['binaryaid.roster.policy'].with_user(cls.manager).create({
            'name': 'Test reviewed policy', 'reference': 'Test reference only', 'approval_note': 'Test review evidence',
            'weekly_hours_limit': 38})
        cls.policy.action_approve()
        cls.template = cls.env['binaryaid.roster.template'].with_user(cls.manager).create({
            'name': 'Office week v1', 'anchor_date': '2027-01-04', 'timezone': 'Australia/Sydney',
            'policy_id': cls.policy.id, 'line_ids': [Command.create({
                'name': 'Office operations', 'cycle_day': day, 'start_hour': 9, 'end_hour': 17,
                'task_recipe_ids': [Command.create({'name': 'Open and prepare workspace'})]}) for day in range(5)]})
        cls.template.action_release()

    def assign(self, employee=None, **kwargs):
        vals = {'employee_id': (employee or self.employee).id, 'template_id': self.template.id,
                'date_start': '2027-01-04', 'date_end': '2027-02-28'}
        vals.update(kwargs)
        record = self.env['binaryaid.roster.assignment'].with_user(self.manager).create(vals)
        record.action_activate()
        return record

    def generate(self, assignments, start='2027-01-04', end='2027-01-17'):
        run = self.env['binaryaid.roster.run'].with_user(self.manager)._start(assignments.ids, fields.Date.to_date(start), fields.Date.to_date(end))
        for assignment in assignments:
            assignment._generate(run.date_from, run.date_to, run)
        run._finish()
        return run

    def test_bulk_assignment_and_idempotent_generation(self):
        wizard = self.env['binaryaid.roster.assign.wizard'].with_user(self.manager).create({
            'template_id': self.template.id, 'employee_ids': [Command.set((self.employee | self.other).ids)],
            'date_start': '2027-01-04', 'date_end': '2027-02-28'})
        action = wizard.action_assign()
        assignments = self.env['binaryaid.roster.assignment'].with_user(self.manager).search(action['domain'])
        self.assertEqual(len(assignments), 2)
        run = self.generate(assignments)
        self.assertEqual(run.created, 20)
        self.assertEqual(run.state, 'complete')
        shifts = assignments.shift_ids
        self.assertEqual(len(shifts), 20)
        self.assertFalse(shifts.task_ids)
        again = self.generate(assignments)
        self.assertEqual(again.created, 0)
        self.assertEqual(again.skipped, 20)
        shift = shifts[0]
        shift.action_publish()
        self.assertEqual(len(shift.task_ids), 1)
        self.assertEqual(shift.task_ids.binaryaid_employee_id, shift.employee_id)
        self.assertEqual(shift.task_ids.binaryaid_work_date, shift.roster_occurrence_date)
        shift.write({'change_reason': 'Discussed later start'})
        shift.action_revise()
        shift.write({'end': shift.end + timedelta(hours=1), 'review_note': 'Agreed change'})
        shift.action_publish()
        self.assertTrue(shift.roster_exception)
        self.assertEqual(len(shift.task_ids), 1)
        self.generate(assignments)
        self.assertEqual(len(assignments.shift_ids), 20)

    def test_immutable_versions_and_recipes(self):
        for record, vals in [(self.template, {'name': 'Rewrite'}),
                             (self.template.line_ids[0], {'start_hour': 8}),
                             (self.template.line_ids[0].task_recipe_ids, {'name': 'Rewrite'}),
                             (self.policy, {'weekly_hours_limit': 100})]:
            with self.assertRaises(ValidationError):
                record.write(vals)
        action = self.template.action_new_version()
        new = self.env['binaryaid.roster.template'].browse(action['res_id'])
        self.assertEqual(new.state, 'draft')
        self.assertEqual(len(new.line_ids), 5)
        self.assertEqual(new.previous_version_id, self.template)
        new.line_ids[0].write({'start_hour': 8})
        self.assertEqual(self.template.line_ids[0].start_hour, 9)

    def test_effective_dates_and_future_change(self):
        assignment = self.assign()
        self.generate(assignment)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.assign(date_start='2027-01-10')
        assignment._end_on(fields.Date.to_date('2027-01-10'), 'Future rotation change agreed')
        later = assignment.shift_ids.filtered(lambda s: s.roster_occurrence_date > fields.Date.to_date('2027-01-10'))
        self.assertEqual(set(later.mapped('state')), {'cancelled'})
        future = self.assign(date_start='2027-01-11')
        self.generate(future, '2027-01-11', '2027-01-17')
        self.assertEqual(len(future.shift_ids), 5)
        self.generate(assignment)
        self.assertEqual(len(assignment.shift_ids), 10)

    def test_no_regeneration_after_cancellation(self):
        assignment = self.assign()
        self.generate(assignment, end='2027-01-04')
        shift = assignment.shift_ids
        shift.write({'change_reason': 'One day exception'})
        shift.action_cancel()
        again = self.generate(assignment, end='2027-01-04')
        self.assertEqual(again.created, 0)
        self.assertEqual(again.skipped, 1)
        self.assertEqual(shift.state, 'cancelled')

    def test_automatic_publication_and_review_queue(self):
        assignment = self.assign(auto_publish=True)
        run = self.generate(assignment, end='2027-01-04')
        self.assertEqual(assignment.shift_ids.state, 'published')
        self.assertEqual(run.state, 'complete')
        policy = self.policy.copy({'name': 'Short day review', 'max_shift_hours': 6, 'approval_note': 'Test review'})
        policy.action_approve()
        template = self.template.copy({'policy_id': policy.id})
        template.action_release()
        other_assignment = self.assign(self.other, template_id=template.id, auto_publish=True)
        run = self.generate(other_assignment, end='2027-01-04')
        self.assertEqual(run.state, 'review')
        self.assertEqual(other_assignment.shift_ids.state, 'draft')
        self.assertFalse(other_assignment.shift_ids.task_ids)
        self.assertTrue(run.issue_ids.message)

    def test_overnight_rotation_and_dst(self):
        template = self.env['binaryaid.roster.template'].with_user(self.manager).create({
            'name': 'Rotating nights', 'anchor_date': '2027-01-04', 'cycle_weeks': 2,
            'line_ids': [Command.create({'name': 'Night', 'cycle_day': 7, 'start_hour': 22,
                                        'end_hour': 6, 'end_day_offset': '1', 'unpaid_break_minutes': 30})]})
        template.action_release()
        assignment = self.assign(template_id=template.id)
        self.generate(assignment, end='2027-01-18')
        self.assertEqual(len(assignment.shift_ids), 1)
        shift = assignment.shift_ids
        self.assertEqual(shift.roster_occurrence_date, fields.Date.to_date('2027-01-11'))
        self.assertEqual(shift.planned_hours, 7.5)
        other_assignment = self.assign(self.other, template_id=template.id, phase_days=7)
        self.generate(other_assignment, end='2027-01-17')
        self.assertEqual(other_assignment.shift_ids.roster_occurrence_date, fields.Date.to_date('2027-01-04'))
        draft = template.copy()
        draft.line_ids.write({'start_hour': 2.5, 'end_hour': 4, 'end_day_offset': '0', 'cycle_day': 6})
        with self.assertRaises(ValidationError):
            draft.line_ids._utc_window(fields.Date.to_date('2027-10-03'))
        with self.assertRaises(ValidationError):
            draft.line_ids._utc_window(fields.Date.to_date('2027-04-04'))

    def test_invalid_cycle_and_wrap_overlap(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.template.copy({'anchor_date': '2027-01-05'})
        draft = self.template.copy()
        draft.line_ids.unlink()
        self.env['binaryaid.roster.template.line'].create([
            {'template_id': draft.id, 'name': 'Sunday night', 'cycle_day': 6, 'start_hour': 22, 'end_hour': 6, 'end_day_offset': '1'},
            {'template_id': draft.id, 'name': 'Monday early', 'cycle_day': 0, 'start_hour': 5, 'end_hour': 9}])
        with self.assertRaises(ValidationError):
            draft.action_release()

    def test_manual_overlap_is_reported(self):
        assignment = self.assign()
        start, end = self.template.line_ids[0]._utc_window(fields.Date.to_date('2027-01-04'))
        self.env['binaryaid.work.shift'].with_user(self.manager).create({
            'name': 'Manual exception', 'employee_id': self.employee.id, 'start': start, 'end': end})
        run = self.generate(assignment, end='2027-01-04')
        self.assertEqual(run.created, 0)
        self.assertEqual(run.state, 'review')

    def test_replacement_preserves_identity_and_tasks(self):
        assignment = self.assign()
        self.generate(assignment, end='2027-01-04')
        original = assignment.shift_ids
        original.action_publish()
        task = original.task_ids
        wizard = self.env['binaryaid.roster.cover.wizard'].with_user(self.manager).create({
            'shift_id': original.id, 'employee_id': self.other.id, 'policy_id': self.policy.id,
            'reason': 'Cover discussed with both employees'})
        action = wizard.action_apply()
        replacement = self.env['binaryaid.work.shift'].search(action['domain'])
        self.assertEqual(original.state, 'cancelled')
        self.assertEqual(original.employee_id, self.employee)
        self.assertFalse(task.active)
        self.assertEqual(replacement.employee_id, self.other)
        self.assertEqual(replacement.roster_replacement_for_id, original)
        self.assertEqual(replacement.state, 'published')
        self.assertNotEqual(replacement.task_ids, task)
        self.assertTrue(replacement.task_ids.active)
        self.assertTrue(original.roster_event_ids.filtered(lambda e: e.event == 'cancelled').reason)

    def test_swap_and_atomic_failure(self):
        alice = self.assign()
        bob = self.assign(self.other)
        self.generate(alice, end='2027-01-04')
        self.generate(bob, '2027-01-05', '2027-01-05')
        originals = alice.shift_ids | bob.shift_ids
        originals.action_publish()
        wizard = self.env['binaryaid.roster.cover.wizard'].with_user(self.manager).create({
            'mode': 'swap', 'shift_id': alice.shift_ids.id, 'swap_shift_id': bob.shift_ids.id,
            'reason': 'Both employees agreed'})
        action = wizard.action_apply()
        new = self.env['binaryaid.work.shift'].search(action['domain'])
        self.assertEqual(len(new), 2)
        self.assertEqual(set(originals.mapped('state')), {'cancelled'})
        self.assertEqual(set(new.mapped('state')), {'published'})
        self.assertEqual(new.filtered(lambda s: s.roster_replacement_for_id == alice.shift_ids).employee_id, self.other)

    def test_failed_cover_keeps_original_published(self):
        assignment = self.assign()
        self.generate(assignment, end='2027-01-04')
        original = assignment.shift_ids
        original.action_publish()
        policy = self.policy.copy({'name': 'Short engagement', 'max_shift_hours': 1, 'approval_note': 'Test review'})
        policy.action_approve()
        wizard = self.env['binaryaid.roster.cover.wizard'].with_user(self.manager).create({
            'shift_id': original.id, 'employee_id': self.other.id, 'policy_id': policy.id, 'reason': 'Attempt cover'})
        with self.assertRaises(ValidationError):
            wizard.action_apply()
        self.assertEqual(original.state, 'published')
        self.assertTrue(original.task_ids.active)
        self.assertFalse(self.env['binaryaid.work.shift'].search([('roster_replacement_for_id', '=', original.id)]))

    def test_security_provenance_and_event_forgery(self):
        assignment = self.assign()
        self.generate(assignment, end='2027-01-04')
        shift = assignment.shift_ids
        self.assertFalse(self.env['binaryaid.roster.event'].with_user(self.alice).search([]))
        with self.assertRaises(AccessError):
            self.env['binaryaid.roster.template'].with_user(self.alice).search([])
        with self.assertRaises(AccessError):
            shift.with_user(self.alice).write({'roster_exception': True})
        with self.assertRaises(AccessError):
            shift.with_context(_roster_internal='forged').write({'roster_assignment_id': False})
        with self.assertRaises(AccessError):
            self.env['binaryaid.roster.event'].with_user(self.manager).create({'shift_id': shift.id})
        with self.assertRaises(AccessError):
            self.env['binaryaid.roster.run'].with_user(self.manager).create({'date_from': '2027-01-04', 'date_to': '2027-01-05'})
        with self.assertRaises(AccessError):
            shift.roster_event_ids.with_user(self.manager).write({'reason': 'Rewrite'})
        self.assertFalse(self.env['binaryaid.roster.event'].with_user(self.bob).search([]))
        shift.action_publish()
        self.assertTrue(self.env['binaryaid.roster.event'].with_user(self.alice).search([]))
        with self.assertRaises(ValidationError):
            shift.write({'employee_id': self.other.id})

    def test_actuals_snapshot_correction_and_reversal(self):
        start = fields.Datetime.now() - timedelta(days=3)
        end = start + timedelta(hours=8)
        shift = self.env['binaryaid.work.shift'].with_user(self.manager).create({
            'name': 'Historical approved plan', 'employee_id': self.employee.id, 'start': start, 'end': end})
        # Simulate a plan published before it was worked, without moving the test clock.
        shift._roster_transition_write({'state': 'published', 'published_at': start - timedelta(days=1)})
        attendance = self.env['hr.attendance'].create({'employee_id': self.employee.id, 'check_in': start, 'check_out': end})
        wizard = self.env['binaryaid.roster.actual.wizard'].with_user(self.manager).create({
            'shift_id': shift.id, 'attendance_ids': [Command.set(attendance.ids)], 'reason': 'Supervisor checked records'})
        wizard.action_approve()
        approved = shift.roster_actual_hours
        self.assertEqual(approved, attendance.worked_hours)
        self.assertTrue(shift.roster_actual_approved)
        attendance.write({'check_out': end - timedelta(hours=1)})
        self.assertEqual(shift.roster_actual_hours, approved)
        wizard.write({'reason': 'Corrected checkout verified'})
        wizard.action_approve()
        self.assertEqual(len(shift.roster_actual_ids), 2)
        self.assertEqual(shift.roster_actual_hours, attendance.worked_hours)
        wizard.write({'is_void': True, 'reason': 'Reversed for review'})
        wizard.action_approve()
        self.assertFalse(shift.roster_actual_approved)
        self.assertEqual(shift.roster_actual_hours, 0)
        self.assertEqual(len(shift.roster_actual_ids), 3)
        self.assertFalse(self.env['binaryaid.roster.actual'].with_user(self.bob).search([]))

    def test_forms_and_generation_limits(self):
        with Form(self.env['binaryaid.roster.template'].with_user(self.manager), view='binaryaid_roster_planning.view_template_form') as form:
            form.name = 'Form pattern'
            form.anchor_date = fields.Date.to_date('2027-01-04')
        self.assertEqual(form.record.state, 'draft')
        assignment = self.assign()
        with self.assertRaises(ValidationError):
            self.env['binaryaid.roster.run'].with_user(self.manager)._start(assignment.ids, fields.Date.to_date('2027-01-04'), fields.Date.to_date('2028-01-06'))
        with self.assertRaises(AccessError):
            self.env['binaryaid.roster.generate.wizard'].with_user(self.alice).create({'assignment_ids': [Command.set(assignment.ids)]})

    def test_same_pattern_different_employee_policies(self):
        policy = self.policy.copy({'name': 'Part-time agreed hours', 'weekly_hours_limit': 20,
                                   'approval_note': 'Test employee terms reviewed'})
        policy.action_approve()
        first = self.assign()
        second = self.assign(self.other, policy_id=policy.id)
        self.generate(first, end='2027-01-04')
        self.generate(second, end='2027-01-04')
        self.assertEqual(first.template_id, second.template_id)
        self.assertEqual(first.shift_ids.weekly_hours_limit, 38)
        self.assertEqual(second.shift_ids.weekly_hours_limit, 20)

    def test_cron_extends_horizon_without_duplicates(self):
        today = fields.Date.context_today(self)
        assignment = self.assign(date_start=today, date_end=today + timedelta(days=21), horizon_days=14)
        assignment.with_user(self.manager)._cron_generate()
        first_ids = assignment.shift_ids.ids
        self.assertTrue(first_ids)
        assignment.with_user(self.manager)._cron_generate()
        self.assertEqual(assignment.shift_ids.ids, first_ids)
        self.assertTrue(assignment.generated_until)

    def test_shared_tasks_and_workweek_starter(self):
        template = self.env['binaryaid.roster.template'].with_user(self.manager).create({
            'name': 'Reusable office pattern', 'anchor_date': '2027-01-04',
            'common_tasks': 'Daily safety check\nComplete handover'})
        template.action_add_workweek()
        self.assertEqual(len(template.line_ids), 5)
        template.action_release()
        assignment = self.assign(template_id=template.id)
        self.generate(assignment, end='2027-01-04')
        shift = assignment.shift_ids
        shift.action_publish()
        self.assertEqual(set(shift.task_ids.mapped('name')), {'Daily safety check', 'Complete handover'})

    def test_publication_batch_is_atomic(self):
        assignment = self.assign()
        self.generate(assignment, end='2027-01-05')
        shifts = assignment.shift_ids.sorted('start')
        # Make the second shift overlap the first, forcing failure after the first was processed.
        shifts[1].write({'start': shifts[0].start, 'end': shifts[0].end})
        wizard = self.env['binaryaid.roster.publish.wizard'].with_user(self.manager).create({
            'shift_ids': [Command.set(shifts.ids)]})
        with self.assertRaises(ValidationError):
            wizard.action_publish()
        self.assertEqual(set(shifts.mapped('state')), {'draft'})
        self.assertFalse(shifts.task_ids)

    def test_company_boundaries(self):
        company = self.env['res.company'].create({'name': 'Planning isolated company'})
        self.manager.write({'company_ids': [Command.link(company.id)]})
        template = self.env['binaryaid.roster.template'].with_user(self.manager).with_context(allowed_company_ids=[company.id]).create({
            'name': 'Other company', 'company_id': company.id, 'anchor_date': '2027-01-04'})
        self.assertFalse(self.env['binaryaid.roster.template'].with_user(self.manager).with_context(
            allowed_company_ids=[self.env.company.id]).search([('id', '=', template.id)]))
        with self.assertRaises(AccessError):
            template.with_user(self.manager).with_context(allowed_company_ids=[self.env.company.id]).read(['name'])

    def test_time_off_blocks_publication(self):
        self.employee.resource_calendar_id = self.employee.resource_calendar_id.copy({'tz': 'Australia/Sydney'})
        assignment = self.assign()
        self.generate(assignment, end='2027-01-04')
        shift = assignment.shift_ids
        leave_type = self.env['hr.leave.type'].create({'name': 'Planning approved absence',
                                                      'requires_allocation': False, 'leave_validation_type': 'no_validation'})
        self.env['hr.leave'].create({'name': 'Private absence reason', 'holiday_status_id': leave_type.id,
                                    'employee_id': self.employee.id, 'request_date_from': '2027-01-04',
                                    'request_date_to': '2027-01-04'})
        with self.assertRaises(ValidationError):
            shift.action_publish()
        self.assertFalse(shift.task_ids)

    def test_source_defaults_cannot_be_forged(self):
        with self.assertRaises(AccessError):
            self.env['binaryaid.work.shift'].with_user(self.manager).with_context(default_roster_exception=True).create({
                'name': 'Forged origin', 'employee_id': self.employee.id,
                'start': '2027-01-04 00:00:00', 'end': '2027-01-04 08:00:00'})

    def test_actual_attendance_not_double_counted(self):
        start = fields.Datetime.now() - timedelta(days=5)
        end = start + timedelta(hours=8)
        shifts = self.env['binaryaid.work.shift'].with_user(self.manager).create([
            {'name': name, 'employee_id': self.employee.id, 'start': start, 'end': end} for name in ['Original historical plan', 'Other historical plan']])
        shifts._roster_transition_write({'state': 'published', 'published_at': start - timedelta(days=1)})
        attendance = self.env['hr.attendance'].create({'employee_id': self.employee.id, 'check_in': start, 'check_out': end})
        wizard = self.env['binaryaid.roster.actual.wizard'].with_user(self.manager).create({
            'shift_id': shifts[0].id, 'attendance_ids': [Command.set(attendance.ids)], 'reason': 'Checked source'})
        wizard.action_approve()
        wizard.write({'shift_id': shifts[1].id})
        with self.assertRaises(ValidationError):
            wizard.action_approve()
        wizard.write({'shift_id': shifts[0].id, 'is_void': True, 'reason': 'Correct allocation'})
        wizard.action_approve()
        wizard.write({'shift_id': shifts[1].id, 'is_void': False})
        wizard.action_approve()
        self.assertFalse(shifts[0].roster_actual_approved)
        self.assertTrue(shifts[1].roster_actual_approved)

    def test_representative_group_generation(self):
        employees = self.env['hr.employee']
        for i in range(20):
            user = new_test_user(self.env, login='planning_scale_%s' % i, groups='binaryaid_work_management.group_work_user')
            employees |= self.env['hr.employee'].create({'name': 'Batch employee %s' % i, 'user_id': user.id})
        assignments = self.env['binaryaid.roster.assignment'].with_user(self.manager).create([
            {'employee_id': e.id, 'template_id': self.template.id, 'date_start': '2027-01-04', 'date_end': '2027-01-31'}
            for e in employees])
        assignments.action_activate()
        run = self.generate(assignments, end='2027-01-31')
        self.assertEqual(run.created, 400)
        self.assertEqual(len(assignments.shift_ids), 400)
        again = self.generate(assignments, end='2027-01-31')
        self.assertEqual(again.created, 0)
        self.assertEqual(again.skipped, 400)

    def test_full_day_leave_blocks_night_roster_despite_day_calendar(self):
        # Full-day leave must not miss night shifts merely because the native calendar is daytime.
        shift = self.env['binaryaid.work.shift'].with_user(self.manager).create({
            'name': 'Night coverage', 'employee_id': self.employee.id,
            'start': '2027-01-04 11:00:00', 'end': '2027-01-04 19:00:00', 'timezone': 'Australia/Sydney'})
        leave_type = self.env['hr.leave.type'].create({'name': 'Full-day absence', 'requires_allocation': False,
                                                      'leave_validation_type': 'no_validation'})
        self.env['hr.leave'].create({'holiday_status_id': leave_type.id, 'employee_id': self.employee.id,
                                    'request_date_from': '2027-01-04', 'request_date_to': '2027-01-04'})
        with self.assertRaises(ValidationError):
            shift.action_publish()
