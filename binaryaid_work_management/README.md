# BinaryAid Work Management

Odoo 19 custom extension of `project.task`, depending on `hr` and `project`.
No Odoo core files are changed. Timesheets are not required: dated narrative
work notes are not billed hours or attendance records.

## Setup

1. Install `binaryaid_work_management` from the custom add-ons path.
2. In Settings → Users, give each participating internal user the
   **Work Management / User** role. It implies the standard Project User role;
   ordinary Project functionality remains available under its native permissions.
3. Link that account to the correct employee and company in Employees.
4. Give work administrators **Work Management / Administrator**. This includes
   HR Officer access so they can select employees and open their profiles.
   The standard Administrator account receives this role on installation.

## Use

- Regular employees use **Work Management → My Work History**, which opens their
  own tasks directly, grouped by Work Date. **New** adds work for themselves;
  each task contains its notes and daily history. The selected company determines
  which linked employee is used. Employee Work and Daily Work History menus are
  restricted to Work Management administrators.
- Employees → Work Management → Employee Work opens the employee list. Click an
  employee to open their work, grouped into collapsible Work Dates (newest
  first). Administrators see employees in their allowed companies; employees see
  only their own entry, including when they have not yet been assigned any work.
- Use New inside an employee's work list to add work. Administrators may assign
  work to that employee; employees can add work only for themselves. Work Date
  defaults to today in the current user's time zone and can be changed before
  saving, including to a previous date. Saved dates remain fixed. Existing dates
  are preserved during the upgrade. Daily work has no Deadline field in these views.
- Employees see only their own employee work items. They can update descriptions,
  use **Add Daily Work Note**, and **Mark Completed**.
- Each note has a work date and a separate actual recording timestamp/author.
  Notes default to the task's Work Date and can be dated from that date through
  today. Assignment and completion history use the task's Work Date; recording
  timestamps retain when the actions actually occurred.
- Completed descriptions are locked for employees. Additional notes can still
  document corrections; administrators can reopen tasks.
- An employee profile has **Work Management** and **Daily Work History** buttons.
- Daily Work History defaults to this month, grouped by employee and day. Change
  the Work Date filter for another month. Use Completions or Work Notes to narrow
  results; pivot counts represent history entries, not hours or unique tasks.
- Archive old work items instead of deleting them. History remains available.
  Assignments are fixed to preserve ownership; create a new task if responsibility
  changes. This version does not support shared tasks, sub-tasks, or recurring work.

## Architecture and security

`binaryaid_employee_id` identifies employee work on native tasks. Ordinary tasks
have no employee link and retain their native workflows. A conditional global
record rule restricts employee work regardless of additional Project memberships
or followers; native company rules still apply. A matching rule protects the
separate SQL task-analysis model. Employee task writes are restricted server-side.

`binaryaid.work.employee` is a read-only SQL projection of existing employee
records, with independent company and ownership rules. It stores no duplicated
employee data and does not change standard employee-directory permissions.
Navigation and expandable date groups use native Odoo list views. Task lists show
status and latest work note; open a task for its full description and note history.

`binaryaid.work.log` stores append-only assignment, note, completion, and reopening
events. Normal users and administrators cannot edit/delete history or directly
create forged events. The private logging helper elevates only after task access
has been checked. The note wizard rechecks access on submission. State updates
take an ORM row lock and record events only on actual transitions.

History keeps the employee and user at recording time. Changing an employee's
linked login later changes access to current tasks, but does not transfer past
history to the replacement login. Administrators retain access within allowed
companies. Employee-account transfers need an explicit business policy.

Use dated notes for daily work evidence; editing a task description alone is not
a daily report. Notifications use Odoo's normal task assignment facilities.

## Verification

Run against a test database with the module in the add-ons path:

```sh
DEBUG=0 python odoo-bin -c odoo.conf -d TEST_DB -i binaryaid_work_management \
  --test-enable --test-tags /binaryaid_work_management \
  --stop-after-init --http-port=8079 --max-cron-threads=0
```

Use `-u` for an installed module. Tests cover assignment isolation (including
Project administrators), report/history access, company boundaries, forbidden
writes and forged events, daily notes, completion/reopening, repeated completion,
form creation, employee navigation, and native task compatibility. Test fixtures
are rolled back. Performance at production scale has not been benchmarked.

Upgrades should retest Project task methods, record-rule composition, task reports,
employee forms, and XML view compatibility against the target Odoo release.
