# Operations: deployment, backup, restore and support

## Modules
`binaryaid_hrms_dashboard`, `binaryaid_work_management`, `binaryaid_work_scheduling`,
`binaryaid_roster_planning`, `binaryaid_care`, `binaryaid_care_attendance`,
`binaryaid_care_timesheet`, `binaryaid_hr_access`. Odoo 19 Community; no CRM app.

## Deploy an update (server `adchrms`, Docker)
```bash
B=~/adchrms/backups/deploy-$(date -u +%Y%m%dT%H%M%SZ); mkdir -p $B
export PGPASSWORD=$(grep ^db_password ~/adchrms/config/odoo.conf | sed 's/^db_password *= *//')
pg_dump -Fc -h 127.0.0.1 -U binaryaid -d adchrms -f $B/adchrms.dump
docker exec adchrms-odoo tar czf - -C /var/lib/odoo/filestore adchrms > $B/filestore.tar.gz
cd ~/adchrms/addons/custom && git rev-parse HEAD > $B/previous-commit.txt && git pull --ff-only
docker exec adchrms-odoo odoo -c /etc/odoo/odoo.conf -d adchrms --no-http --stop-after-init \
  -u binaryaid_hrms_dashboard,binaryaid_work_scheduling,binaryaid_roster_planning,binaryaid_care,binaryaid_care_attendance,binaryaid_care_timesheet
docker restart adchrms-odoo
```

## Restore a backup
```bash
docker stop adchrms-odoo
dropdb -h 127.0.0.1 -U binaryaid adchrms && createdb -h 127.0.0.1 -U binaryaid adchrms
pg_restore -h 127.0.0.1 -U binaryaid -d adchrms --no-owner $B/adchrms.dump
docker start adchrms-odoo
docker exec -i adchrms-odoo sh -c 'rm -rf /var/lib/odoo/filestore/adchrms && tar xzf - -C /var/lib/odoo/filestore' < $B/filestore.tar.gz
cd ~/adchrms/addons/custom && git checkout $(cat $B/previous-commit.txt)   # code matching the backup
docker restart adchrms-odoo
```
Test a restore into a separate database at least once before go-live.

## Scheduled jobs
Care timesheets (daily), document retention review (weekly), roster generation
(hourly). Check *Settings ▸ Technical ▸ Scheduled Actions* after upgrades.

## Rollout support ownership (to agree with ADC)
| Area | Owner |
| --- | --- |
| Hosting, backups, upgrades | BinaryAid |
| User accounts, roles, client portal access | ADC administrator |
| Document categories, note template, incident categories, settings | ADC operations lead |
| Bugs and change requests | BinaryAid via ADC's nominated contact |
