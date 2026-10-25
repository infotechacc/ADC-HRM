# Importing ADC data

Use Odoo's standard import (list view ▸ ⚙ ▸ Import records). Always click
**Test** first: Odoo validates every row and imports nothing until all rows pass.

Import in this order, using the templates in `import_templates/`:

| File | Menu | Notes |
| --- | --- | --- |
| `1_clients.csv` | Care Operations ▸ Clients | `id` is your own unique key; later files refer to it. `reference` (participant ID) must be unique. |
| `2_service_locations.csv` | Import on *Client Service Location* | `id` is your own unique key used by shifts. Coordinates in decimal degrees. Imported coordinates are **not verified**: an administrator checks each on the map and clicks *Mark coordinates verified*. |
| `3_employees.csv` | Employees | Department must already exist. Then use *Create User* so the worker can log in, and add them to *Work Management ▸ User*. |
| `4_future_shifts.csv` | Care Operations ▸ Shifts (list view) | Each employee needs an active login with *Work Management ▸ User* first. `start`/`end` are **UTC** (`YYYY-MM-DD HH:MM:SS`). Sydney 08:00 AEDT = 21:00 UTC the day before. Shifts import as drafts; review them on the dashboard and publish. |

Documents are uploaded per client and worker (Documents tab ▸ Upload), so every
file passes type, size and content checks and gets a version number.

Before importing live data, ADC must confirm: the eight client and five worker
document names (Configuration ▸ Document Categories), which worker documents are
required for rostering, and the fortnight start date (Settings ▸ Care Operations).
