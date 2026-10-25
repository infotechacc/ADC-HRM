# ADC HRMS – administrator guide

## Your daily dashboard
Open **HRMS Dashboard** (your home page after login).

- **Header buttons**: Create shift, Add client, Add employee, Review requests.
  They open pop-ups; the dashboard refreshes when you close them.
- **Figures bar**: today's shifts, working now, unfilled shifts, client requests,
  missing sign-outs, clock exceptions, leave to review, timesheet reviews. A figure
  turns red or amber when it needs action; click it to open the matching list.
- **Today**: every shift today with time, worker, client, location and live status
  (Signed in, Not signed in, Upcoming, Draft, Unfilled, Finished). Filter with the
  buttons above the table; click a row to open the shift.
- **Next 14 days**: a calendar of the actual shifts (time, worker, client).
  Published shifts have a solid bar, drafts a dashed bar, unfilled shifts are red.
  Hover a day and click **+** to create a shift on it.
- **Action items**: each category with work waiting (Unfilled, Requests, Clock,
  Drafts, Leave, Documents, Sign-outs, Timesheets, Notes, Incidents). Click a
  category to expand it and act on each item without leaving the page.

**Shift pop-up**: choose the client (its location and approved care requirements
appear), the time and, if known, the worker. Leave the worker empty to save an
**unfilled** shift. *Save draft* keeps it unpublished; *Publish* checks it and
notifies the worker. If publishing is blocked, the draft is kept and the reason shown.

## Clients
Care Operations ▸ Clients. Keep the participant ID, status, authorised contacts,
care requirements and service locations. Each location needs coordinates and must
be **verified** before sign in can be location checked. Archive a client to stop
new shifts; history is kept and portal logins are disabled.

**Portal access**: on *Authorised contacts*, click *Grant portal* for the
participant or an authorised representative. They can submit support needs and
see their own request status only.

## Shifts
Create from the dashboard (button or planner day). Choose the client first: the
service location and approved requests appear. *Save* keeps a draft; *Publish*
notifies the worker. Publishing is blocked for overlapping shifts, approved leave,
inactive employees or clients, and asks for a manager note when documents are
missing/expired or a location is not verified. Published changes: *Revise* or
*Cancel* with a reason, or *Replace / Swap*.

## Timesheets (every fortnight)
Timesheets are prepared automatically. Open *Timesheets* on the dashboard:
check each row's issues, *Adjust* hours with a reason when needed, then
*Approve* and *Lock*. Incomplete and unresolved rows are excluded from approved
hours. *Export CSV* produces approved hours for payroll (it does not run payroll).

## Team messages
Care Operations ▸ Team Messages. Choose employees, departments or everyone.
Keep care details out of messages; recipients only get a generic notification.
