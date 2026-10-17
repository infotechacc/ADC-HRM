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

## Dashboard presentation (19.0.1.1.0)

The workspace uses a navy welcome area, role-aware metric cards, and a responsive
main/sidebar layout. Recent work keeps its existing drilldowns; monthly progress
and permitted quick actions appear alongside it. At smaller widths the panels
stack, and work tables scroll within their panel. Focus indicators, labelled
controls, refresh feedback, useful empty states and reduced-motion preferences
are supported. All displayed metrics come from the existing server definitions.

The optional Scheduling extension fills `ba_schedule_slot` with a Monday–Sunday
strip and shift cards. It uses the request timezone for dates/times and preserves
published-shift ownership checks for card navigation. No placeholder metrics,
chart trends or demo work are inserted into the dashboard.

Upgrade both `binaryaid_hrms_dashboard` and `binaryaid_work_scheduling` together
when Scheduling is installed, then refresh the web client to load the new assets.
Chrome tests cover manager desktop and employee mobile layouts, real work data,
keyboard focus and horizontal overflow. Successful runs save viewport screenshots
under Odoo's configured screenshots directory.
