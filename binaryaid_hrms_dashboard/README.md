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
