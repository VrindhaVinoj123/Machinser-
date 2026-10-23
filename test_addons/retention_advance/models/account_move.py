# -*- coding: utf-8 -*-
from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError

RA_KINDS = [
    ('retention', 'Retention'),
    ('return_retention', 'Retention Returned (Credit Note)'),
    ('release', 'Retention Release'),
    ('recovery', 'Advance Recovery'),
    ('return_advance', 'Advance Returned (Credit Note)'),
]


class AccountMove(models.Model):
    _inherit = 'account.move'

    # ------------------------------------------------------------------
    # Fields entered / shown on the customer invoice (invoice currency)
    # ------------------------------------------------------------------
    ra_retention_pct = fields.Float(
        string='Retention %', digits=(5, 2), compute='_compute_ra_retention_pct',
        store=True, readonly=False)
    ra_retention_amount = fields.Monetary(
        string='Retention', compute='_compute_ra_retention_amount', store=True,
        currency_field='currency_id')
    ra_handover_date = fields.Date(
        string='Expected Handover Date', copy=False,
        help="Due date of the retention. If empty, the invoice due date is used.")
    ra_advance_payment_id = fields.Many2one(
        'account.payment', string='Advance Payment', copy=False, check_company=True,
        domain="[('company_id', '=', company_id), ('payment_type', '=', 'inbound'),"
               " ('partner_type', '=', 'customer'),"
               " ('partner_id', 'child_of', commercial_partner_id),"
               " ('state', 'in', ('in_process', 'paid'))]")
    ra_recovery_type = fields.Selection(
        [('percent', '% of work done'), ('fixed', 'Fixed amount')],
        string='Recovery Method', default='percent', copy=False)
    ra_recovery_pct = fields.Float(string='Recovery %', digits=(5, 2), copy=False)
    ra_recovery_fixed = fields.Monetary(
        string='Recovery Amount (fixed)', currency_field='currency_id', copy=False)
    ra_recovery_amount = fields.Monetary(
        string='Advance Recovery', compute='_compute_ra_recovery_amount', store=True,
        currency_field='currency_id')
    ra_amount_to_pay = fields.Monetary(
        string='Amount to Pay Now', compute='_compute_ra_amount_to_pay', store=True,
        currency_field='currency_id')
    ra_project_id = fields.Many2one(
        'sale.order', string='Project', compute='_compute_ra_project_id', store=True, recursive=True)

    # ------------------------------------------------------------------
    # Fields on the helper entries (and their reversals)
    # ------------------------------------------------------------------
    ra_kind = fields.Selection(RA_KINDS, string='Retention/Advance Entry Type', copy=False, index=True)
    ra_invoice_id = fields.Many2one(
        'account.move', string='Project Invoice', copy=False, index=True,
        help="Customer invoice this retention / advance entry belongs to.")
    ra_source_move_id = fields.Many2one(
        'account.move', string='Triggered By', copy=False, index=True,
        help="Document that triggered the entry (invoice or credit note).")
    ra_amount = fields.Monetary(
        string='Amount (company currency)', currency_field='company_currency_id', copy=False,
        help="Signed amount used by the report. Reversals carry the opposite sign.")
    ra_helper_move_ids = fields.One2many('account.move', 'ra_source_move_id', string='Retention/Advance Entries')
    ra_cn_ratio = fields.Float(
        string='Credit Note Ratio', copy=False,
        help="Share of the original invoice credited by this credit note (set at posting).")
    ra_retention_released = fields.Monetary(
        string='Retention Released', compute='_compute_ra_retention_balance',
        currency_field='currency_id')
    ra_retention_held = fields.Monetary(
        string='Retention Still Held', compute='_compute_ra_retention_balance',
        currency_field='currency_id')

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------

    @api.depends('ra_retention_amount', 'state', 'ra_helper_move_ids.state',
                 'ra_helper_move_ids.line_ids.amount_residual_currency')
    def _compute_ra_retention_balance(self):
        for move in self:
            released = held = 0.0
            if move.move_type == 'out_invoice' and move.state == 'posted' and move.id:
                helpers = self._ra_filter_active(self.env['account.move'].search([
                    ('ra_invoice_id', '=', move.id), ('ra_kind', 'in', ('retention', 'release'))]))
                for helper in helpers:
                    debit_lines = helper.line_ids.filtered(lambda l: l.balance > 0)
                    if helper.ra_kind == 'retention':
                        held += sum(debit_lines.mapped('amount_residual_currency'))
                    else:
                        released += sum(debit_lines.mapped('amount_currency'))
            move.ra_retention_released = released
            move.ra_retention_held = held

    @api.depends('company_id', 'move_type')
    def _compute_ra_retention_pct(self):
        for move in self:
            if move.move_type == 'out_invoice' and move.state == 'draft':
                move.ra_retention_pct = move.company_id.ra_default_retention_pct
            else:
                move.ra_retention_pct = 0.0

    @api.depends('amount_untaxed', 'ra_retention_pct', 'move_type', 'currency_id')
    def _compute_ra_retention_amount(self):
        for move in self:
            if move.move_type == 'out_invoice' and move.ra_retention_pct and move.currency_id:
                move.ra_retention_amount = move.currency_id.round(
                    move.amount_untaxed * move.ra_retention_pct / 100.0)
            else:
                move.ra_retention_amount = 0.0

    @api.depends('amount_untaxed', 'ra_recovery_type', 'ra_recovery_pct', 'ra_recovery_fixed',
                 'move_type', 'currency_id')
    def _compute_ra_recovery_amount(self):
        for move in self:
            amount = 0.0
            if move.move_type == 'out_invoice' and move.currency_id:
                if move.ra_recovery_type == 'fixed':
                    amount = move.ra_recovery_fixed
                elif move.ra_recovery_pct:
                    amount = move.currency_id.round(move.amount_untaxed * move.ra_recovery_pct / 100.0)
            move.ra_recovery_amount = amount

    @api.depends('amount_total', 'ra_retention_amount', 'ra_recovery_amount', 'move_type')
    def _compute_ra_amount_to_pay(self):
        for move in self:
            if move.move_type == 'out_invoice':
                move.ra_amount_to_pay = move.amount_total - move.ra_retention_amount - move.ra_recovery_amount
            else:
                move.ra_amount_to_pay = move.amount_total

    @api.depends('invoice_line_ids.sale_line_ids.order_id', 'reversed_entry_id.ra_project_id')
    def _compute_ra_project_id(self):
        for move in self:
            orders = move.invoice_line_ids.sale_line_ids.order_id.sorted('id')
            move.ra_project_id = orders[:1] or move.reversed_entry_id.ra_project_id

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    @api.constrains('ra_retention_pct', 'ra_recovery_pct', 'ra_recovery_fixed')
    def _check_ra_values(self):
        for move in self:
            if not 0.0 <= move.ra_retention_pct <= 100.0:
                raise ValidationError(_("Retention % must be between 0 and 100."))
            if not 0.0 <= move.ra_recovery_pct <= 100.0:
                raise ValidationError(_("Recovery % must be between 0 and 100."))
            if move.ra_recovery_fixed < 0.0:
                raise ValidationError(_("The fixed recovery amount cannot be negative."))

    @api.constrains('ra_advance_payment_id', 'ra_recovery_amount')
    def _check_ra_advance_remaining(self):
        for move in self.filtered(lambda m: m.state == 'draft' and m.move_type == 'out_invoice'
                                            and m.ra_advance_payment_id and m.ra_recovery_amount):
            remaining = move._ra_advance_remaining()
            if move.currency_id.compare_amounts(move.ra_recovery_amount, remaining) > 0:
                raise ValidationError(_(
                    "You cannot recover %(amount)s: only %(left)s is left on advance %(payment)s.",
                    amount=move.currency_id.format(move.ra_recovery_amount),
                    left=move.currency_id.format(remaining),
                    payment=move.ra_advance_payment_id.name))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _ra_receivable_lines(self):
        self.ensure_one()
        return self.line_ids.filtered(
            lambda l: l.account_id.account_type == 'asset_receivable' and l.display_type == 'payment_term')

    def _ra_advance_remaining(self):
        """Open balance of the selected advance, expressed in the invoice currency."""
        self.ensure_one()
        total = 0.0
        for line in self.ra_advance_payment_id._ra_open_receivable_lines():
            if line.currency_id == self.currency_id:
                total += -line.amount_residual_currency
            else:
                total += self.company_currency_id._convert(
                    -line.amount_residual, self.currency_id, self.company_id,
                    self.date or fields.Date.context_today(self))
        return max(total, 0.0)

    def _ra_company_balance(self, amount):
        """Company-currency balance of `amount` (invoice currency) at the invoice's own rate."""
        self.ensure_one()
        lines = self._ra_receivable_lines()
        total_cur = sum(lines.mapped('amount_currency'))
        total_bal = sum(lines.mapped('balance'))
        if not total_cur or self.currency_id.is_zero(amount - total_cur):
            return total_bal
        return self.company_currency_id.round(total_bal * amount / total_cur)

    def _ra_get_journal(self):
        self.ensure_one()
        journal = self.company_id.ra_journal_id or self.env['account.journal'].search(
            [('company_id', '=', self.company_id.id), ('type', '=', 'general')], limit=1)
        if not journal:
            raise UserError(_("No miscellaneous journal found for company %s.", self.company_id.name))
        return journal

    @staticmethod
    def _ra_filter_active(moves):
        """Posted helper entries that were not reversed (and are not reversals themselves)."""
        return moves.filtered(
            lambda m: m.state == 'posted' and not m.reversed_entry_id
                      and not m.reversal_move_ids.filtered(lambda r: r.state == 'posted'))

    def _ra_active_helpers(self, kinds):
        self.ensure_one()
        return self._ra_filter_active(self.ra_helper_move_ids.filtered(lambda m: m.ra_kind in kinds))

    @api.model
    def _ra_create_entry(self, kind, invoice, source, date, ref, currency, specs, ra_amount):
        """Create and post a helper entry.

        specs: list of (account, partner, amount_currency, balance, date_maturity); positive = debit.
        """
        lines = []
        for account, partner, amount_cur, balance, maturity in specs:
            lines.append(Command.create({
                'name': ref,
                'account_id': account.id,
                'partner_id': partner.id,
                'currency_id': currency.id,
                'amount_currency': amount_cur,
                'debit': balance if balance > 0 else 0.0,
                'credit': -balance if balance < 0 else 0.0,
                'date_maturity': maturity,
            }))
        move = self.create({
            'move_type': 'entry',
            'journal_id': invoice._ra_get_journal().id,
            'date': date,
            'ref': ref,
            'company_id': invoice.company_id.id,
            'currency_id': currency.id,
            'ra_kind': kind,
            'ra_invoice_id': invoice.id,
            'ra_source_move_id': source.id,
            'ra_amount': ra_amount,
            'line_ids': lines,
        })
        move.action_post()
        return move

    # ------------------------------------------------------------------
    # Posting
    # ------------------------------------------------------------------
    def _ra_check_before_post(self):
        self.ensure_one()
        company = self.company_id
        currency = self.currency_id
        if self.ra_retention_amount and not company.ra_retention_account_id:
            raise UserError(_("Please set the Retention Receivable account in the accounting settings."))
        if currency.compare_amounts(self.ra_retention_amount + self.ra_recovery_amount, self.amount_untaxed) > 0:
            raise UserError(_("Retention plus advance recovery cannot exceed the work done on the invoice."))
        if not self.ra_recovery_amount:
            return
        payment = self.ra_advance_payment_id
        if not payment:
            raise UserError(_("Select the advance payment to recover from."))
        if payment.company_id != company or payment.state not in ('in_process', 'paid') \
                or payment.partner_id.commercial_partner_id != self.commercial_partner_id:
            raise UserError(_("The advance payment must be posted and belong to the same customer and company."))
        open_lines = payment._ra_open_receivable_lines()
        if not open_lines:
            raise UserError(_("Advance %s has no open balance left.", payment.name))
        # Lock the advance lines so two invoices cannot recover the same money at the same time.
        self.env.cr.execute('SELECT id FROM account_move_line WHERE id IN %s FOR UPDATE', [tuple(open_lines.ids)])
        self.env['account.move.line'].invalidate_model(['amount_residual', 'amount_residual_currency', 'reconciled'])
        remaining = self._ra_advance_remaining()
        if currency.compare_amounts(self.ra_recovery_amount, remaining) > 0:
            raise UserError(_(
                "You cannot recover %(amount)s: only %(left)s is left on advance %(payment)s.",
                amount=currency.format(self.ra_recovery_amount), left=currency.format(remaining),
                payment=payment.name))

    def _post(self, soft=True):
        to_check = self.filtered(
            lambda m: m.state == 'draft' and m.move_type == 'out_invoice'
                      and (m.ra_retention_amount or m.ra_recovery_amount))
        for move in to_check:
            move._ra_check_before_post()
        posted = super()._post(soft=soft)
        for move in posted:
            if move.move_type == 'out_invoice' and (move.ra_retention_amount or move.ra_recovery_amount):
                move._ra_create_invoice_entries()
            elif move.move_type == 'out_refund' and move.reversed_entry_id:
                move._ra_create_refund_entries()
        return posted

    def _ra_create_invoice_entries(self):
        self.ensure_one()
        Move = self.env['account.move']
        rec_lines = self._ra_receivable_lines()
        if not rec_lines:
            return
        partner = rec_lines[0].partner_id
        inv_account = rec_lines[0].account_id
        currency = self.currency_id
        due = self.invoice_date_due or self.date

        # 1. Retention: Dr Retention Receivable / Cr Receivable, reconciled with the invoice
        if self.ra_retention_amount and not self._ra_active_helpers(('retention',)):
            ret_account = self.company_id.ra_retention_account_id
            if ret_account in rec_lines.account_id:
                raise UserError(_("The Retention Receivable account must differ from the customer receivable account."))
            amount = self.ra_retention_amount
            balance = self._ra_company_balance(amount)
            entry = Move._ra_create_entry(
                'retention', self, self, self.date, _("Retention - %s", self.name), currency,
                [(ret_account, partner, amount, balance, self.ra_handover_date or due),
                 (inv_account, partner, -amount, -balance, due)], balance)
            credit = entry.line_ids.filtered(lambda l: l.balance < 0)
            (credit | rec_lines).reconcile()

        # 2. Advance recovery: Dr Receivable (matched to the advance) / Cr Receivable (matched to the invoice)
        if self.ra_recovery_amount and not self._ra_active_helpers(('recovery',)):
            payment = self.ra_advance_payment_id
            pay_lines = payment._ra_open_receivable_lines()
            amount = self.ra_recovery_amount
            balance = self._ra_company_balance(amount)
            entry = Move._ra_create_entry(
                'recovery', self, self, self.date, _("Advance recovery - %s", self.name), currency,
                [(pay_lines[0].account_id, pay_lines[0].partner_id, amount, balance, self.date),
                 (inv_account, partner, -amount, -balance, self.date)], balance)
            debit = entry.line_ids.filtered(lambda l: l.balance > 0)
            credit = entry.line_ids.filtered(lambda l: l.balance < 0)
            (debit | pay_lines).reconcile()
            (credit | rec_lines).reconcile()
            vals = {'ra_is_advance': True}
            if not payment.ra_sale_order_id and self.ra_project_id:
                vals['ra_sale_order_id'] = self.ra_project_id.id
            payment.write(vals)

    def _ra_create_refund_entries(self):
        """Give back retention and advance in proportion to the credited work."""
        self.ensure_one()
        Move = self.env['account.move']
        invoice = self.reversed_entry_id
        if invoice.move_type != 'out_invoice' or self._ra_active_helpers(('return_retention', 'return_advance')):
            return
        retention_move = invoice._ra_active_helpers(('retention',))[:1]
        recovery_move = invoice._ra_active_helpers(('recovery',))[:1]
        if not (retention_move or recovery_move) or not invoice.amount_untaxed:
            return
        previous = invoice.reversal_move_ids.filtered(
            lambda m: m != self and m.state == 'posted' and m.move_type == 'out_refund')
        ratio = max(0.0, min(self.amount_untaxed / invoice.amount_untaxed, 1.0 - sum(previous.mapped('ra_cn_ratio'))))
        if not ratio:
            return
        self.ra_cn_ratio = ratio
        currency = invoice.currency_id
        cn_lines = self._ra_receivable_lines()
        partner = cn_lines[0].partner_id
        inv_account = invoice._ra_receivable_lines()[:1].account_id

        # Retention comes back: Dr Receivable / Cr Retention Receivable
        if retention_move:
            ret_line = retention_move.line_ids.filtered(lambda l: l.balance > 0)
            amount = min(currency.round(invoice.ra_retention_amount * ratio), ret_line.amount_residual_currency)
            if amount > 0:
                if currency.is_zero(amount - ret_line.amount_residual_currency):
                    balance = ret_line.amount_residual
                else:
                    balance = self.company_currency_id.round(
                        ret_line.amount_residual * amount / ret_line.amount_residual_currency)
                entry = Move._ra_create_entry(
                    'return_retention', invoice, self, self.date, _("Retention returned - %s", self.name),
                    ret_line.currency_id,
                    [(inv_account, partner, amount, balance, self.date),
                     (ret_line.account_id, ret_line.partner_id, -amount, -balance, self.date)], -balance)
                (entry.line_ids.filtered(lambda l: l.balance < 0) | ret_line).reconcile()
                (entry.line_ids.filtered(lambda l: l.balance > 0) | cn_lines).reconcile()

        # Advance comes back: the open credit is re-created on the customer (Cr), the debit is
        # applied to the credit note (Dr).
        if recovery_move and invoice.ra_recovery_amount:
            amount = currency.round(invoice.ra_recovery_amount * ratio)
            if amount > 0:
                balance = self.company_currency_id.round(recovery_move.ra_amount * amount / invoice.ra_recovery_amount)
                adv_account = recovery_move.line_ids.filtered(lambda l: l.balance > 0).account_id[:1]
                adv_partner = recovery_move.line_ids.filtered(lambda l: l.balance > 0).partner_id[:1]
                entry = Move._ra_create_entry(
                    'return_advance', invoice, self, self.date, _("Advance returned - %s", self.name), currency,
                    [(inv_account, partner, amount, balance, self.date),
                     (adv_account, adv_partner, -amount, -balance, self.date)], -balance)
                (entry.line_ids.filtered(lambda l: l.balance > 0) | cn_lines).reconcile()

    # ------------------------------------------------------------------
    # Reset to draft
    # ------------------------------------------------------------------
    def _ra_check_can_reset(self):
        self.ensure_one()
        if self.move_type != 'out_invoice':
            return
        later = self._ra_filter_active(self.search([
            ('ra_invoice_id', '=', self.id),
            ('ra_kind', 'in', ('release', 'return_retention', 'return_advance'))]))
        if later:
            raise UserError(_(
                "Invoice %s cannot be reset to draft: retention was already released or a credit "
                "note was issued against it. Reverse those entries first.", self.name))

    def _ra_reverse_helpers(self):
        """Reverse (never delete) the retention/advance entries created by this document."""
        self.ensure_one()
        helpers = self._ra_filter_active(self.ra_helper_move_ids.filtered(lambda m: m.ra_kind != 'release'))
        for helper in helpers:
            helper.line_ids.remove_move_reconcile()
            helper._reverse_moves([{
                'date': helper.date,
                'ref': _("Reversal of %s", helper.name),
                'ra_kind': helper.ra_kind,
                'ra_invoice_id': helper.ra_invoice_id.id,
                'ra_source_move_id': helper.ra_source_move_id.id,
                'ra_amount': -helper.ra_amount,
            }], cancel=True)
        if self.move_type == 'out_refund':
            self.ra_cn_ratio = 0.0

    def button_draft(self):
        posted = self.filtered(lambda m: m.state == 'posted')
        for move in posted:
            move._ra_check_can_reset()
        res = super().button_draft()
        for move in posted:
            move._ra_reverse_helpers()
        return res
