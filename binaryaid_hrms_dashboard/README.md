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
no business data is read with sudo. Recent lists are bounded. Dashboard data is
loaded on entry and on Refresh, not continuously polled.

Monthly completion uses Work Date, including backdated work, and the current task
status. Full daily history remains accessible through Work Management.
Native public employee identity lookups remain unaffected. Employees without Work
Management access can still land here and see permitted summaries and Discuss.

Optional applications are not installed automatically. Future metrics should add
server-owned specifications with the same domain for their count and drilldown.
The session extension and client action registry should be revalidated on Odoo
major upgrades. Tests cover own-work isolation, denied drilldowns, company scope,
backdating, no-role/portal access, and the session's landing action.

## Operations dashboard (19.0.1.2.0)

Follows task 02 (central dashboard) and task 08 (worker home screen) of the ADC
HRMS task list. One client action renders two role-aware layouts.

**Administrators** (Work Management administrators or HR officers):
- Quick actions in the header open dialogs over the dashboard: Create shift,
  Add employee. Dialogs refresh the figures when closed.
- Metric strip: today's shifts, working now, unpublished shifts, missing
  sign-outs, leave to review, timesheet reviews and document alerts. Alert
  figures are highlighted. Selecting a metric opens its inbox tab, or its list.
- Today's shifts with attendance status (signed in / not signed in / upcoming /
  draft / completed) and filter chips. A row opens the shift in a dialog.
- 14-day planner (two calendar weeks from Monday, until ADC confirms the
  fortnight anchor) with published and draft counts. Selecting a future day
  opens a new 09:00–17:00 draft shift on that date; every value stays editable.
- Needs attention inbox with inline actions: publish drafts, approve or refuse
  leave, correct missing sign-outs, open timesheet reconciliation, open profiles
  with expiring visas or work permits. Leave that overlaps published shifts is
  flagged and cannot be approved inline until the roster is resolved (task 13).

**Workers**: current or next shift banner with sign-in status, large links
(shift calendar, work history, team messages, leave, profile), Request leave
dialog, the employee's own published 14-day roster, then personal figures.

Every inline action goes through `item_action(source, id, name)`. The server
finds the record again through the same domain that listed it, then runs the
standard Odoo method as the current user (`action_publish`, `action_approve`,
`action_refuse`, …), so normal access rights and validation apply. Validation
errors are shown as notifications and drafts stay unchanged. Lists are bounded
to 8 items per tab with a View all link. Overview cards never show care notes,
shift instructions or incident details.

Document alerts use Odoo's native visa and work permit expiry dates with the
company's work permit notice period. They will move to the five ADC worker
document categories once those categories exist (task 05).

The Scheduling and Roster Planning add-ons add their data to `get_overview`.
They no longer use template extensions. Upgrade all three modules together.
