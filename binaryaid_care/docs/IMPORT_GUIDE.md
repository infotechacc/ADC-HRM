# Importing ADC data

Use Odoo's standard import (list view ▸ ⚙ ▸ Import records). Always click
**Test** first: Odoo validates every row and imports nothing until all rows pass.

Import in this order, using the templates in `import_templates/`:

| File | Menu | Notes |
| --- | --- | --- |
| `1_clients.csv` | Care Operations ▸ Clients | `id` is your own unique key; later files refer to it. |
| `2_service_locations.csv` | Import on *Client Service Location* | `id` is your own unique key used by shifts. `name` is the service location address. Coordinates in decimal degrees. |
| `3_employees.csv` | Employees | Department must already exist. Then use *Create User* so the worker can log in, and add them to *Work Management ▸ User*. |
| `4_future_shifts.csv` | Care Operations ▸ All Shifts (list view) | Each employee needs an active login with *Work Management ▸ User* first. `start`/`end` are **UTC** (`YYYY-MM-DD HH:MM:SS`). Sydney 08:00 AEDT = 21:00 UTC the day before. Shifts import as drafts; review them on the dashboard and publish. |

Client documents are uploaded on each client's Documents tab. Worker documents
are uploaded per worker, so every file passes type, size and content checks and
gets a version number.

Before importing live data, ADC must confirm: the five worker document names,
which worker documents are required for rostering, and the fortnight start date
(Settings ▸ Care Operations).
