# BinaryAid Roster Planning

Reusable, versioned roster patterns and effective employee assignments for ADC
HRMS / Odoo 19. Read [the architecture decision and complete workflow](ARCHITECTURE.md)
for the alternatives, security model, Australian research and practical limits.

Install **BinaryAid Roster Planning** with `ADC-HRM` in the addons path. It adds
standard Odoo Attendance and Time Off dependencies and extends the existing
Scheduling module; existing manual shifts and dashboard remain in place. Upgrade
`binaryaid_work_scheduling` to 19.0.1.2.1 alongside installation. Back up the
database, filestore and add-on sources before installation or upgrade.

**Start here:** Employees → Work Management → Roster Planning.

1. Review Policies: configure applicable terms and record policy review evidence.
2. Schedule Templates: create a 1–12 week pattern anchored on a Monday. Add shift
   rows, break instructions, locations and per-shift task definitions. Release it.
3. Assign Employees: choose a group/department and inclusive effective dates.
4. Employee Assignments: select assignments → Actions → Generate Roster Preview.
   Review the generated shifts directly. Select drafts → Review and Publish.
5. Automatic generation extends each active assignment's horizon hourly. Automatic
   publication is optional and requires an approved policy; unresolved checks
   leave drafts for review. Generation diagnostics remain available internally.
6. Use Revise for one future shift, Replace / Swap for coverage, and End / Change
   Schedule to switch recurring patterns from a future date. These operations
   preserve original records and record reasons.
7. Roster Audit shows completed-date published/cancelled shifts grouped by employee,
   with scheduled hours, breaks and locations. Drafts and future shifts stay in the
   scheduling screens. Shift details contain only Tasks and Instructions; manager
   review notes and reasons remain there to support publication and changes.

Generation Runs and Actual Work History menus and the attendance reconciliation
button are hidden. Their underlying records and backend services are retained.

No generic Australian award is assumed. Approving a configured policy does not
make it legally compliant. Actual pay/overtime calculation is outside this module.

## Verification

Use a disposable database and the project's Odoo Python environment:

```sh
DEBUG=0 python odoo/odoo-bin -d TEST_DB --addons-path=odoo/addons,ADC-HRM \
  -i binaryaid_roster_planning -u binaryaid_work_scheduling \
  --test-enable --test-tags /binaryaid_roster_planning,/binaryaid_work_scheduling,/binaryaid_hrms_dashboard,/binaryaid_work_management \
  --stop-after-init --http-interface=127.0.0.1 --http-port=8079 \
  --max-cron-threads=0 --without-demo
```

Use `-u` for an installed planning module. Production-volume throughput, failover,
backup restoration and client-specific award acceptance remain deployment work.

Release verification on the supplied Odoo 19 source: **56 tests passed** across
Planning, Scheduling, HRMS Dashboard and Work Management. This includes the
manager's generation/publication browser workflow, employee dashboard/calendar,
mobile/desktop layouts, 20 employees producing 400 shifts with a duplicate-free
rerun, mixed employee policies, rotation offsets, DST, full-day leave for night
shifts, immutable history, swaps, atomic rollback and attendance reconciliation.
These are functional checks, not a production capacity or compliance certification.
