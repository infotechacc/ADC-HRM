from odoo import api, fields, models, _


class WorkShift(models.Model):
    _inherit = 'binaryaid.work.shift'

    care_note_status = fields.Selection([('none', 'Not started'), ('draft', 'Draft'), ('submitted', 'Submitted')],
                                        compute='_compute_care_note_status', search='_search_care_note_status',
                                        string='Shift note')
    attendance_ids = fields.One2many('hr.attendance', 'binaryaid_shift_id', string='Attendance')

    def _compute_care_note_status(self):
        # Status only, read with elevated rights: note content stays restricted to authors and reviewers.
        notes = self.env['binaryaid.care.shift.note'].sudo().search([('shift_id', 'in', self.ids)])
        by_shift = {note.shift_id.id: note.state for note in notes}
        for shift in self:
            shift.care_note_status = by_shift.get(shift.id, 'none')

    def _search_care_note_status(self, operator, value):
        values = [value] if operator in ('=', '!=') else list(value)
        submitted = self.env['binaryaid.care.shift.note'].sudo().search([('state', '=', 'submitted')]).shift_id.ids
        drafts = self.env['binaryaid.care.shift.note'].sudo().search([('state', '=', 'draft')]).shift_id.ids
        ids = {'submitted': submitted, 'draft': drafts}
        domain = []
        for state in values:
            part = [('id', 'not in', submitted + drafts)] if state == 'none' else [('id', 'in', ids[state])]
            domain = ['|'] + domain + part if domain else part
        if operator in ('!=', 'not in'):
            domain = ['!'] + domain
        return domain

    def _deletion_blockers(self):
        blockers = super()._deletion_blockers()
        if self.env['hr.attendance'].sudo().search_count([('binaryaid_shift_id', '=', self.id)]):
            blockers.append(_('a check in'))
        if self.env['binaryaid.care.shift.note'].sudo().search_count([('shift_id', '=', self.id)]):
            blockers.append(_('a shift note'))
        if self.env['binaryaid.care.attendance.exception'].sudo().search_count([('shift_id', '=', self.id)]):
            blockers.append(_('a clock exception'))
        return blockers
