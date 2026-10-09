from odoo import api, models, _
from odoo.exceptions import AccessError


class HrEmployeePublic(models.Model):
    _inherit = 'hr.employee.public'

    @api.model
    def _check_directory_access(self):
        if not self.env.su and not self.env.user.has_group('hr.group_hr_user'):
            raise AccessError(_('You need Employees Officer or Administrator access to open the Employee Directory.'))

    @api.model
    def get_view(self, view_id=None, view_type='form', **options):
        self._check_directory_access()
        return super().get_view(view_id, view_type, **options)

    @api.model
    def get_views(self, views, options=None):
        self._check_directory_access()
        return super().get_views(views, options=options)

    @api.model
    @api.readonly
    def web_search_read(self, domain, specification, offset=0, limit=None, order=None, count_limit=None):
        self._check_directory_access()
        return super().web_search_read(domain, specification, offset=offset, limit=limit,
                                       order=order, count_limit=count_limit)

    @api.readonly
    def web_read(self, specification):
        self._check_directory_access()
        return super().web_read(specification)

    @api.model
    @api.readonly
    def web_read_group(self, *args, **kwargs):
        self._check_directory_access()
        return super().web_read_group(*args, **kwargs)
