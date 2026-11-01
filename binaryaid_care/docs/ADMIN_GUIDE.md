# ADC HRMS – administrator guide

## Your daily dashboard
Open **HRMS Dashboard** (your home page after login).

- **Header buttons**: Create shift, Add client, Add employee.
  They open pop-ups; the dashboard refreshes when you close them.
- **Figures bar**: today's shifts, working now, unfilled shifts,
  missing sign-outs, clock exceptions, leave to review, timesheet reviews. A figure
  turns red or amber when it needs action; click it to open the matching list.
- **Shift calendar** (left): a month view with the number of shifts on each day
  and a red badge for unfilled shifts. Use the arrows to change month and
  *Today* to come back.
- **Selected day** (right): click a date to see its shifts as cards: day and date,
  start – end time, client, location, worker and live status (Signed in, Not
  signed in, Upcoming, Draft, Unfilled). Click a card to see the details in a
  pop-up, or *Assign shift* to add a shift on that day.

**Shift pop-up**: choose the client (its service location fills *Location*, which
you can still change before publishing; its care plans appear), the time and,
if known, the worker. Leave the worker empty to save an
**unfilled** shift. *Save draft* keeps it unpublished; *Publish* checks it and
notifies the worker. If publishing is blocked, the draft is kept and the reason shown.

## Clients
Care Operations ▸ Clients. One form holds the client name, phone and email,
the alternative contact's name, phone and email, and the service location with its
latitude, longitude, timezone and clock radius. Workers can only check in and out
within the clock radius of these coordinates. Archive a client (⚙ ▸ Archive) to
stop new shifts; history is kept.

- **Care plans** (after Clock radius): choose one or more plans from
  Care Operations ▸ Plans.
- **Care Plans tab**: lists every service of the chosen plans. Removing a plan
  removes its services. Use *Add a line* to add extra services for this client only.
- **Documents tab**: *Add a line* and choose a file; upload as many as needed.
  Each file has *Preview* and *Download* buttons.

## Plans
Care Operations ▸ Plans lists all plans with their services. Click *New*, enter the
plan name, add one line per service the plan includes (*Add a line*), then *Save*.
Click a plan to open and change it.

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
