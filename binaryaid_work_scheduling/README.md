# BinaryAid Work Scheduling

Odoo 19 add-on for ADC HRMS. Depends on `binaryaid_hrms_dashboard` and reuses
`binaryaid_work_management` roles, employee assignments and native Project tasks.
Odoo core and existing module source files are unchanged.

## Install and use

Add `ADC-HRM` to the Odoo addons path, update the Apps list and install **BinaryAid
Work Scheduling**. Existing dashboard/work modules are installed as dependencies.
Back up the target database and validate in staging before a production install.

1. Link employees to active internal users with the **Work Management / User** role.
2. Give schedulers **Work Management / Administrator**. This is the existing
   company-scoped work administrator role, not a new department manager role.
3. Open **Employees → Work Management → Weekly Work Schedule**. The calendar
   opens at the current week; use its previous/next controls for other weeks.
   Switch to List and select New to prepare a draft shift.
4. Set employee, start/finish, location, unpaid break minutes, break timing
   instructions and shift instructions. Overnight shifts use dates on both ends.
   Link existing employee tasks under Tasks and Instructions. Create new tasks
   through Employee Work first, then select them on the shift. Their existing
   completion and daily-note workflows remain available through Work Management.
5. Confirm the workplace timezone and applicable award/agreement. Configure
   notice, rest and weekly hours review thresholds for that employee's terms.
   Zero disables a threshold; notice/rest default to zero because no universal
   award-specific value is assumed. The default 38-hour weekly threshold is a
   review aid, not an overtime calculation or a determination of reasonable hours.
6. Publish from the form, or select drafts in List and use Actions → Publish Shifts.
   Overlapping published shifts for the same employee are blocked. Threshold
   exceptions require a manager review note. Publication notifies the linked user
   through Odoo chatter; email delivery follows the server's notification setup.
7. Employees see their own published/cancelled shifts in the calendar and their
   current week's published shifts on the HRMS dashboard. Dashboard Refresh
   reloads changes. The dashboard shows up to 100 shifts intersecting the user's
   local Monday–Sunday week; the calendar provides full navigation.
8. To change a published shift, record a reason, select Revise, edit the draft,
   then republish. Revisions withdraw the previous shift from the employee's
   calendar until republished. Cancellation retains a visible cancelled entry.
   Explain changes and obtain required consultation/consent before using these
   actions. Notifications alone do not meet consultation obligations.

All input/output times use standard Odoo UTC storage and user-local display. Set
users' timezones correctly. `Workplace Timezone` defines the Monday–Sunday review
week, independently of the viewer. DST changes affect actual elapsed duration;
paid hours = elapsed UTC duration minus unpaid breaks. Break instructions explain
when breaks must be taken; this version does not validate individual break timing.

## Australian requirements and design decisions

Research checked 17 October 2026 against official sources:

- [Fair Work: hours, breaks and rosters](https://www.fairwork.gov.au/employment-conditions/hours-of-work-breaks-and-rosters):
  awards and registered agreements determine many roster and break rules. Hourly
  rostering also applies to salaried employees; hourly pay is not universal.
- [Maximum weekly hours](https://www.fairwork.gov.au/tools-and-resources/fact-sheets/minimum-workplace-entitlements/maximum-weekly-hours):
  the NES generally set 38 hours for full-time workers and the lesser of 38 or
  usual weekly hours for other workers, plus reasonable additional hours.
  Averaging and reasonableness need the applicable terms and circumstances.
- [Rosters](https://www.fairwork.gov.au/employment-conditions/hours-of-work-breaks-and-rosters/rosters)
  and [FWC consultation terms](https://www.fwc.gov.au/consultation-term): changes
  to regular rosters or ordinary hours require consultation as applicable;
  award/agreement notice and consent provisions must also be checked.
- [Retail Award](https://awards.fairwork.gov.au/MA000004.html) and
  [Hospitality Award](https://awards.fairwork.gov.au/MA000009.html) illustrate
  different notice, break and rest rules. No industry award is automatically
  applied because the client's industry/classifications were not provided.
- [Record keeping](https://www.fairwork.gov.au/pay-and-wages/paying-wages/record-keeping):
  accurate time/wage records must be retained, generally for seven years.
  Rosters are planned work, not proof of actual work or payroll entitlements.

Before operational use, identify national/state system coverage, the applicable
award or enterprise agreement, employee classifications, employment types, agreed
part-time patterns, availability, location/public holidays and client policies.
Set review thresholds accordingly. Rest/notice checks are advisory gates with
recorded review, not a compliance certification or permission to waive obligations.

Not included: wage calculation, penalty/overtime rates, minimum engagements,
award interpretation, averaging cycles, automated public holidays, leave or
availability conflict checks, actual attendance reconciliation, shift acceptance,
recurrence or weekly templates. Existing attendance/time-off modules are not
modified. Review totals count each full published shift in the week of its local
start date, rather than prorating overnight shifts across week boundaries.

## Architecture and security

`binaryaid.work.shift` is a mail-thread model, protected by global company and
ownership record rules. Work users can read only their published/cancelled
shifts; existing Work administrators manage shifts in allowed companies. Private
HR records are not exposed through the employee selector to ordinary users;
stored employee display names support calendar and list views.

The ORM enforces draft-only editing, role checks, status actions, positive hours,
active employee account/role, task ownership and company matching. Published
shifts are preserved (cancel instead of delete). Chatter tracks field changes,
publication, revision and cancellation; it is operational audit history, not a
certified tamper-proof statutory archive. Company backup/retention policies still
apply. The private employee roster version serializes publication across shifts
and invalidates stale PostgreSQL snapshots. Employee task ownership remains
immutable under the existing Work Management module.

Dashboard integration extends its server model and OWL template through this
add-on. Reads and navigation use the current user's ORM permissions without sudo.
No public controller, cron, paid Enterprise Planning dependency or payroll coupling
is introduced. Uninstalling removes this add-on's data; export/retain required
records before uninstalling.

## Verification

Run on a disposable database with the project's Odoo Python environment:

```sh
DEBUG=0 python odoo/odoo-bin -d TEST_DB --addons-path=odoo/addons,ADC-HRM \
  -i binaryaid_work_scheduling --test-enable \
  --test-tags /binaryaid_work_scheduling,/binaryaid_work_management,/binaryaid_hrms_dashboard \
  --stop-after-init --http-port=8079 --max-cron-threads=0 --without-demo
```

Use `-u` for upgrades. Tests cover ownership/company isolation, employee write and
status bypass attempts, overlap handling, adjacent shifts, task reuse, revision
history, threshold review, invalid durations, dashboard integration and form views. A Chrome smoke test verifies the employee
dashboard, weekly calendar and shift detail dialog.

Validation on the supplied Odoo 19 source and an isolated PostgreSQL 16 database:
28 integration/regression tests passed across Scheduling, Work Management and
HRMS Dashboard. The expanded calendar-to-shift-detail Chrome check also passed.
Production-volume load testing was not performed. Server installation and
upgrade health checks are performed separately, with database and filestore backups.

## Dashboard refresh (19.0.1.1.0)

The schedule integrates into the redesigned dashboard's main column. A seven-day
strip highlights today and marks days touched by published shifts, including
shifts continuing after midnight. Shift cards show local start/end times,
location, tasks and full planned paid hours. Select a card to open the shift;
the server rechecks ownership, published state and active company. The calendar
button remains available for the full schedule. Preview limits are stated when
100 shifts are returned. Upgrade Scheduling and HRMS Dashboard together.
