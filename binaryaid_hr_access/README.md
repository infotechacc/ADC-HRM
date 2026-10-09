# BinaryAid Employee Directory Access

Odoo 19 normally grants internal users access to the public employee directory
independently of the Employees role. This module requires `hr.group_hr_user`
(Employees Officer; implied by Employees Administrator) to open Directory.

- Directory menu and action groups require the Employees role.
- The inherited action-load controller rejects public employee actions for users
  without that role, including bookmarked IDs, XML IDs, and action paths.
- Public employee view loading and web list/form/grouped data endpoints check the
  role server-side. Cached views do not bypass data endpoint checks after revocation.
- No context flag can disable the check. Explicit superuser operations retain
  Odoo's normal bypass.
- The Employees root menu remains available for other authorized functionality,
  including BinaryAid My Work History.

This is a **Directory page access policy**, not a blanket confidentiality policy
for all public employee identity data. Native ORM employee-name lookups remain
available to other workflows; private employee fields retain Odoo's standard
security. No broad employee model ACLs or record rules are changed.

The module depends only on `hr`; it is independent of Work Management. Tests cover
menu visibility, view/data RPC denial, direct action loads, HR access, permission
revocation, and retained basic identity lookups. Work Management regression tests
are also run during installation in the development database.

The two existing menu/action records are updated through custom XML. If this
module is uninstalled, upgrade `hr` to restore Odoo's original group configuration.
