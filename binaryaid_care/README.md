# BinaryAid Care Operations (ADC HRMS)

Custom client management and care operations for Australian Diversity Care on
Odoo 19 Community. Clients are a custom model linked to rostered employees; the
CRM app and sales pipelines are not used.

| Module | Delivers (ADC task list) |
| --- | --- |
| `binaryaid_hrms_dashboard` | 02 central dashboard, 08 worker home screen |
| `binaryaid_care` | 03 clients, 04 client request portal, 05 worker documents, 06–07 client shifts and publish checks, 12 team messages and profile limits, 13 leave/roster conflicts, 16 document security |
| `binaryaid_care_attendance` | 08 clock actions, 09 location verified attendance and exceptions, 10 shift notes, 11 incidents |
| `binaryaid_care_timesheet` | 14 fortnightly timesheets, 15 reports and approved export |
| existing roster modules | 06–07 shifts, overlap/leave validation, revisions, replacement, DST |

Security: permissions are enforced on the server (ACLs, record rules and checked
service methods). Workers see only their own published shifts and the clients and
locations on them; client logins see only their own requests; shift notes and
incidents are limited to their author and the *Care Records Reviewer* group.

Configuration (Care Operations ▸ Configuration and Settings) holds every value ADC
must still confirm: document categories, required worker documents, note template,
incident categories and escalation, fortnight start, clock windows, GPS accuracy,
note-writing time rule, unpaid breaks, upload limits, retention and virus scanner.

Guides, import templates, operations runbook and pilot checklist: see `docs/`.
