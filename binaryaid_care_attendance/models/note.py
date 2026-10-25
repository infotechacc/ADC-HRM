import pytz

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from odoo.addons.binaryaid_care.models.tools import get_param

ANSWER_TYPES = [('text', 'Short text'), ('textarea', 'Long text'), ('yes_no', 'Yes / No'),
                ('choice', 'Choice'), ('number', 'Number')]


class NoteTemplate(models.Model):
    _name = 'binaryaid.care.note.template'
    _description = 'Shift Note Template'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    question_ids = fields.One2many('binaryaid.care.note.question', 'template_id', string='Questions', copy=True)

    @api.model
    def _current(self, company):
        return self.search([('company_id', 'in', [company.id, False])], order='company_id, id desc', limit=1)


class NoteQuestion(models.Model):
    _name = 'binaryaid.care.note.question'
    _description = 'Shift Note Question'
    _order = 'template_id, sequence, id'

    template_id = fields.Many2one('binaryaid.care.note.template', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    label = fields.Char(required=True)
    help_text = fields.Char()
    answer_type = fields.Selection(ANSWER_TYPES, required=True, default='textarea')
    options = fields.Text(help='One option per line, for choice questions.')
    required = fields.Boolean(default=True)

    def option_list(self):
        self.ensure_one()
        return [line.strip() for line in (self.options or '').splitlines() if line.strip()]


class ShiftNote(models.Model):
    _name = 'binaryaid.care.shift.note'
    _description = 'Shift Note'
    _inherit = ['mail.thread']
    _order = 'shift_start desc, id desc'

    shift_id = fields.Many2one('binaryaid.work.shift', required=True, readonly=True, ondelete='restrict', index=True)
    shift_start = fields.Datetime(related='shift_id.start', store=True)
    employee_id = fields.Many2one('hr.employee', required=True, readonly=True, index=True)
    user_id = fields.Many2one(related='employee_id.user_id', store=True, index=True)
    client_id = fields.Many2one('binaryaid.care.client', readonly=True, index=True)
    company_id = fields.Many2one(related='shift_id.company_id', store=True)
    note_date = fields.Date(string='Date', readonly=True)
    template_id = fields.Many2one('binaryaid.care.note.template', readonly=True)
    state = fields.Selection([('draft', 'Draft'), ('submitted', 'Submitted')], default='draft', required=True,
                             readonly=True, tracking=True)
    submitted_on = fields.Datetime(readonly=True)
    clock_out_requested_on = fields.Datetime(readonly=True, help='When Clock Out was tapped.')
    submission_token = fields.Char(readonly=True, copy=False, index=True)
    answer_ids = fields.One2many('binaryaid.care.shift.note.answer', 'note_id', string='Answers', readonly=True)
    amendment_ids = fields.One2many('binaryaid.care.shift.note.amendment', 'note_id', string='Amendments', readonly=True)

    _shift_unique = models.Constraint('UNIQUE(shift_id)', 'A shift has one note.')
    _token_unique = models.UniqueIndex('(submission_token) WHERE submission_token IS NOT NULL')

    @api.depends('shift_id', 'employee_id')
    def _compute_display_name(self):
        for note in self:
            note.display_name = _('Note: %(emp)s, %(date)s', emp=note.employee_id.name, date=note.note_date or '')

    def write(self, vals):
        if not self.env.su:
            raise AccessError(_('Shift notes change only through the note form and amendments.'))
        if self.filtered(lambda n: n.state == 'submitted') and set(vals) - {'message_main_attachment_id'}:
            raise AccessError(_('Submitted notes are preserved. Add an amendment instead.'))
        return super().write(vals)

    def unlink(self):
        raise AccessError(_('Shift notes are kept for history.'))

    def action_amend(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Amend note'), 'res_model': 'binaryaid.care.shift.note.amendment',
                'view_mode': 'form', 'target': 'new', 'context': {'default_note_id': self.id}}

    # ------------------------------------------------------------------
    # Worker service: all writes run as the system after ownership checks.
    # ------------------------------------------------------------------
    @api.model
    def _for_shift(self, shift, create=True):
        note = self.sudo().search([('shift_id', '=', shift.id)], limit=1)
        if not note and create:
            tz = pytz.timezone(shift.timezone or 'UTC')
            template = self.env['binaryaid.care.note.template'].sudo()._current(shift.company_id)
            if not template:
                raise UserError(_('No shift note template is configured. Ask your coordinator.'))
            note = self.sudo().create({
                'shift_id': shift.id, 'employee_id': shift.employee_id.id, 'client_id': shift.client_id.id,
                'note_date': pytz.UTC.localize(shift.start).astimezone(tz).date(), 'template_id': template.id})
        return note

    def _questions(self):
        return self.template_id.question_ids

    def _form_payload(self):
        self.ensure_one()
        answers = {a.question_id.id: a.value for a in self.answer_ids}
        return {
            'note_id': self.id, 'state': self.state, 'client': self.client_id.name or '',
            'date': str(self.note_date or ''),
            'questions': [{'id': q.id, 'label': q.label, 'help': q.help_text or '', 'type': q.answer_type,
                           'required': q.required, 'options': q.option_list(), 'value': answers.get(q.id, '')}
                          for q in self._questions()],
        }

    def _store_answers(self, answers):
        """Replace draft answers with the posted values (question id -> value)."""
        self.ensure_one()
        answers = {int(k): ('' if v is None else str(v)).strip()[:5000] for k, v in (answers or {}).items()}
        commands = [(5, 0, 0)]
        for question in self._questions():
            if question.id in answers:
                commands.append((0, 0, {'question_id': question.id, 'label': question.label, 'value': answers[question.id]}))
        self.sudo().write({'answer_ids': commands})

    def _validate_answers(self):
        self.ensure_one()
        values = {a.question_id: a.value for a in self.answer_ids}
        missing = [q.label for q in self._questions() if q.required and not (values.get(q) or '').strip()]
        if missing:
            raise ValidationError(_('Answer the required questions: %s', ', '.join(missing)))
        for question, value in values.items():
            if not value:
                continue
            if question.answer_type == 'yes_no' and value not in ('yes', 'no'):
                raise ValidationError(_('Answer yes or no for "%s".', question.label))
            if question.answer_type == 'choice' and value not in question.option_list():
                raise ValidationError(_('Choose one of the options for "%s".', question.label))
            if question.answer_type == 'number':
                try:
                    float(value)
                except ValueError:
                    raise ValidationError(_('Enter a number for "%s".', question.label))

    def _submit(self, token=None):
        self.ensure_one()
        self._validate_answers()
        self.sudo().write({'state': 'submitted', 'submitted_on': fields.Datetime.now(), 'submission_token': token or False})
        self.sudo().message_post(body=_('Shift note submitted.'))

    def _clock_out_time(self):
        rule = get_param(self.env, 'clock_out_time_rule')
        return (self.clock_out_requested_on if rule == 'tap' and self.clock_out_requested_on else fields.Datetime.now())


class ShiftNoteAnswer(models.Model):
    _name = 'binaryaid.care.shift.note.answer'
    _description = 'Shift Note Answer'
    _order = 'note_id, id'

    note_id = fields.Many2one('binaryaid.care.shift.note', required=True, ondelete='cascade', index=True)
    question_id = fields.Many2one('binaryaid.care.note.question', ondelete='set null')
    label = fields.Char(readonly=True, help='Question text at the time of answering.')
    value = fields.Text(readonly=True)

    def write(self, vals):
        if not self.env.su or self.note_id.filtered(lambda n: n.state == 'submitted'):
            raise AccessError(_('Submitted answers are preserved.'))
        return super().write(vals)

    def unlink(self):
        if not self.env.su or self.note_id.filtered(lambda n: n.state == 'submitted'):
            raise AccessError(_('Submitted answers are preserved.'))
        return super().unlink()


class ShiftNoteAmendment(models.Model):
    _name = 'binaryaid.care.shift.note.amendment'
    _description = 'Shift Note Amendment'
    _order = 'id'

    note_id = fields.Many2one('binaryaid.care.shift.note', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='note_id.company_id', store=True)
    author_id = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)
    reason = fields.Char(required=True)
    text = fields.Text(string='Amendment', required=True)

    @api.model_create_multi
    def create(self, vals_list):
        records = self.env['binaryaid.care.shift.note.amendment']
        for vals in vals_list:
            note = self.env['binaryaid.care.shift.note'].browse(vals.get('note_id'))
            note.check_access('read')
            author_is_writer = note.user_id == self.env.user
            if not author_is_writer and not self.env.user.has_group('binaryaid_care.group_care_reviewer'):
                raise AccessError(_('Only the note author or a care reviewer can amend a note.'))
            if note.state != 'submitted':
                raise UserError(_('Amend a note after it has been submitted.'))
            vals['author_id'] = self.env.uid
            record = super(ShiftNoteAmendment, self.sudo()).create([vals])
            note.sudo().message_post(body=_('Amendment added by %(user)s: %(reason)s', user=self.env.user.name, reason=vals['reason']))
            records |= record
        return records

    def write(self, vals):
        raise AccessError(_('Amendments are kept unchanged.'))

    def unlink(self):
        raise AccessError(_('Amendments are kept for history.'))
