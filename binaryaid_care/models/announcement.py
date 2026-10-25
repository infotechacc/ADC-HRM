from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


class Announcement(models.Model):
    _name = 'binaryaid.care.announcement'
    _description = 'Team Message'
    _inherit = ['mail.thread']
    _order = 'sent_on desc, id desc'
    _check_company_auto = True

    title = fields.Char(required=True, tracking=True)
    body = fields.Html(required=True, sanitize_style=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    author_id = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)
    audience = fields.Selection([('employees', 'Selected employees'), ('departments', 'Departments / teams'),
                                 ('all', 'All rostered workers')], required=True, default='employees')
    employee_ids = fields.Many2many('hr.employee', string='Employees', check_company=True)
    department_ids = fields.Many2many('hr.department', string='Departments', check_company=True)
    requires_ack = fields.Boolean(string='Requires acknowledgement')
    confirm_no_sensitive = fields.Boolean(
        string='No sensitive care information',
        help='Announcements go to several people. Confirm the message contains no client care, health or incident details.')
    state = fields.Selection([('draft', 'Draft'), ('sent', 'Sent'), ('archived', 'Archived')], default='draft',
                             required=True, tracking=True)
    sent_on = fields.Datetime(readonly=True)
    recipient_ids = fields.One2many('binaryaid.care.announcement.recipient', 'announcement_id', string='Recipients')
    recipient_count = fields.Integer(compute='_compute_stats')
    read_count = fields.Integer(compute='_compute_stats')
    ack_count = fields.Integer(compute='_compute_stats')

    @api.depends('recipient_ids.read_on', 'recipient_ids.acknowledged_on')
    def _compute_stats(self):
        for message in self:
            message.recipient_count = len(message.recipient_ids)
            message.read_count = len(message.recipient_ids.filtered('read_on'))
            message.ack_count = len(message.recipient_ids.filtered('acknowledged_on'))

    def _target_employees(self):
        self.ensure_one()
        Employee = self.env['hr.employee']
        if self.audience == 'employees':
            employees = self.employee_ids
        elif self.audience == 'departments':
            employees = Employee.search([('department_id', 'child_of', self.department_ids.ids),
                                         ('company_id', '=', self.company_id.id)])
        else:
            employees = Employee.search([('company_id', '=', self.company_id.id)])
        return employees.filtered(lambda e: e.user_id and e.user_id.active)

    def action_send(self):
        for message in self:
            if message.state != 'draft':
                raise UserError(_('Only draft messages can be sent.'))
            employees = message._target_employees()
            if not employees:
                raise UserError(_('No active employee with a login matches the selected audience.'))
            if len(employees) > 1 and not message.confirm_no_sensitive:
                raise UserError(_('Confirm that this message contains no sensitive care information before sending it to several people.'))
            message.write({'state': 'sent', 'sent_on': fields.Datetime.now(), 'recipient_ids': [
                (0, 0, {'employee_id': employee.id, 'user_id': employee.user_id.id}) for employee in employees]})
            # The notification preview is generic: the content is only visible after opening it.
            message.message_notify(partner_ids=employees.user_id.partner_id.ids, subject=_('New team message'),
                                   body=_('You have a new team message. Open your HRMS dashboard to read it.'))
        return True

    def action_archive_message(self):
        self.write({'state': 'archived'})

    def action_reset_draft(self):
        for message in self:
            if message.recipient_ids:
                raise UserError(_('A sent message keeps its recipient history. Create a new message instead.'))
        self.write({'state': 'draft'})

    def _own_recipient(self):
        recipient = self.recipient_ids.filtered(lambda r: r.user_id == self.env.user)
        if not recipient:
            raise AccessError(_('This message was not sent to you.'))
        return recipient

    def action_mark_read(self):
        self.ensure_one()
        recipient = self._own_recipient()
        if not recipient.read_on:
            recipient.sudo().read_on = fields.Datetime.now()
        return True

    def action_acknowledge(self):
        self.ensure_one()
        recipient = self._own_recipient()
        recipient.sudo().write({'read_on': recipient.read_on or fields.Datetime.now(),
                                'acknowledged_on': recipient.acknowledged_on or fields.Datetime.now()})
        return True


class AnnouncementRecipient(models.Model):
    _name = 'binaryaid.care.announcement.recipient'
    _description = 'Team Message Recipient'
    _order = 'id'

    announcement_id = fields.Many2one('binaryaid.care.announcement', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='announcement_id.company_id', store=True)
    employee_id = fields.Many2one('hr.employee', required=True, ondelete='cascade')
    user_id = fields.Many2one('res.users', required=True, index=True)
    read_on = fields.Datetime(readonly=True)
    acknowledged_on = fields.Datetime(readonly=True)

    _unique_recipient = models.Constraint('UNIQUE(announcement_id, employee_id)', 'Each employee receives a message once.')
