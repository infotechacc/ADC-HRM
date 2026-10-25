from odoo import models

# Fields that stay under HR control: employment, bank/tax and document approval data.
HR_CONTROLLED_FIELDS = {'employee_bank_account_ids', 'job_title', 'category_ids', 'visa_expire',
                        'work_location_id', 'barcode', 'pin', 'km_home_work', 'work_email'}


class ResUsers(models.Model):
    _inherit = 'res.users'

    @property
    def SELF_WRITEABLE_FIELDS(self):
        return [field for field in super().SELF_WRITEABLE_FIELDS if field not in HR_CONTROLLED_FIELDS]
