# One-fortnight pilot checklist

Before the pilot (ADC to confirm, then configure):
- [ ] Five worker document names; which worker documents are required
- [ ] Shift note template questions; whether note writing is paid (Settings)
- [ ] One client per shift (current design) or several
- [ ] Fortnight start date; clock windows; GPS accuracy limit; exception rules
- [ ] Break and paid time rules (Settings ▸ unpaid breaks stays off until agreed)
- [ ] Incident categories, severity and escalation; who are care reviewers
- [ ] Notification channel (currently in-app only), retention period, devices
- [ ] File size limit (the SRS value is unclear; currently 10 MB documents, 50 MB incident media)

End-to-end flow to verify with real users and phones:
- [ ] Admin adds a client with care plans and documents → creates and publishes a shift
- [ ] Worker sees the shift → Check In on site (GPS) → incident report → Check Out with note
- [ ] GPS failure and missed sign out exceptions → admin approves
- [ ] Leave overlapping a shift is blocked until the shift is reassigned
- [ ] Fortnight timesheet → adjust → approve → lock → CSV export
- [ ] Permissions: worker sees only own shifts/clients; notes and incidents only for reviewers
- [ ] Overnight shift and daylight saving change (first Sunday in October / April)
- [ ] Deactivated worker and archived client lose access
- [ ] Backup and restore tested
