# BinaryAid HRMS Dashboard

A dedicated OWL client action and app menu, depending on `binaryaid_work_management`.
Install/upgrade with the custom addons directory configured in Odoo.

Internal users receive this action as the standard web session `home_action_id`.
Explicit action links still take priority. Discuss stays installed and accessible.
No login controller, core file, or stored user preference is modified. Uninstalling
restores Odoo's normal home action behavior.

Work users see their own work. Work admins see work in the active company. Employee
counts require HR Officer access. Attendance, Time Off and Recruitment cards are
included only when their models are installed and readable. All counts, grouped
aggregates and drilldowns use the current user's ORM access and company scope;
no business data is read with sudo. Dashboard data is
loaded on entry and on Refresh, not continuously polled.

Native public employee identity lookups remain unaffected. Employees without Work
Management access can still land here and see permitted summaries and Discuss.

Optional applications are not installed automatically. Future metrics should add
server-owned specifications with the same domain for their count and drilldown.
The session extension and client action registry should be revalidated on Odoo
major upgrades. Tests cover own-work isolation, denied drilldowns, company scope,
no-role/portal access, and the session's landing action.

## Operations dashboard (19.0.1.5.0)

Follows task 02 (central dashboard) and task 08 (worker home screen) of the ADC
HRMS task list. One client action renders two role-aware layouts, kept simple:
there are no action item, go to, recent work item or My account sections.

**Administrators** (Work Management administrators or HR officers):
- Quick actions in the header open dialogs over the dashboard: Create shift, Add client, Add employee. Dialogs refresh the figures when closed.
- Figures: today's shifts, working now, unfilled shifts, missing sign-outs, clock exceptions, leave to review, timesheet reviews. Alert figures are highlighted. Selecting a figure opens its list.
- Today's shifts with attendance status and filter chips. A row opens the shift in a dialog.
- 14-day calendar of shifts. Selecting a future day opens a new 09:00–17:00 draft shift on that date; every value stays editable.

**Workers**: Check In and Check Out buttons (both always shown, only the one that
applies is enabled), current or next shift, large links (My shifts, Incident forms,
Team messages, Leave, My profile), Request leave, the employee's own published
14-day roster, team messages and leave.

Shift rows and own-leave cancellation go through `item_action(source, id, name)`:
the server finds the record again through a server-owned domain and runs the
standard Odoo method as the current user. Figures never show care notes, shift
instructions or incident details.

Every form in the system shows labelled **Save** and **Cancel** buttons instead of
Odoo's icon-only buttons (`static/src/form_buttons.xml`).

The Scheduling and Roster Planning add-ons add their data to `get_overview`.
Upgrade the modules together.
