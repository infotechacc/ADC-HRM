# ADC HRMS – administrator guide

## Your daily dashboard
Open **HRMS Dashboard** (your home page after login).

- **Header buttons**: Create shift, Add client, Add employee.
  They open pop-ups; the dashboard refreshes when you close them.
- **Figures bar**: today's shifts, working now, unfilled shifts,
  missing sign-outs, clock exceptions, leave to review, timesheet reviews. A figure
  turns red or amber when it needs action; click it to open the matching list.
- **Today**: every shift today with time, worker, client, location and live status
  (Signed in, Not signed in, Upcoming, Draft, Unfilled, Finished). Filter with the
  buttons above the table; click a row to open the shift.
- **Next 14 days**: a calendar of the actual shifts (time, worker, client).
  Published shifts have a solid bar, drafts a dashed bar, unfilled shifts are red.
  Hover a day and click **+** to create a shift on it.

**Shift pop-up**: choose the client (its service location and care plans
appear), the time and, if known, the worker. Leave the worker empty to save an
**unfilled** shift. *Save draft* keeps it unpublished; *Publish* checks it and
notifies the worker. If publishing is blocked, the draft is kept and the reason shown.

## Clients
Care Operations ▸ Clients. One form holds the client name, phone and email,
alternative contacts (name, phone, email) and the service location with its
latitude, longitude, timezone and clock radius. Workers can only check in and out
within the clock radius of these coordinates. Archive a client (⚙ ▸ Archive) to
stop new shifts; history is kept.

- **Care Plans tab**: *Add a line* lists every plan from Care Operations ▸ Plans;
  tick one or more to assign them, or click *New* to create a plan on the spot.
- **Documents tab**: *Add a line* and choose a file; upload as many as needed.
  Each file has *Preview* and *Download* buttons.

## Plans
Care Operations ▸ Plans. Enter a plan name to create it; all plans are listed.

## Shifts
Create from the dashboard (button or planner day). Choose the client first: the
service location and care plans appear. *Save* keeps a draft; *Publish*
notifies the worker. Publishing is blocked for overlapping shifts, approved leave,
inactive employees or clients, and asks for a manager note when documents are
missing/expired or a location has no coordinates. Published changes: *Revise* or
*Cancel* with a reason, or *Replace / Swap*.

## Timesheets (every fortnight)
Timesheets are prepared automatically. Open *Timesheets* on the dashboard:
check each row's issues, *Adjust* hours with a reason when needed, then
*Approve* and *Lock*. Incomplete and unresolved rows are excluded from approved
hours. *Export CSV* produces approved hours for payroll (it does not run payroll).

## Forms
Every form has labelled **Save** and **Cancel** buttons at the top while you have
unsaved changes.
