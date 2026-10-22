# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    ra_is_advance = fields.Boolean(
        string='Advance Payment', copy=False,
        help="Tick for customer payments that are project advances. "
             "Set automatically when the payment is used for an advance recovery.")
    ra_sale_order_id = fields.Many2one(
        'sale.order', string='Project (Sales Order)', copy=False, check_company=True,
        help="Project this advance belongs to. If empty it is set the first time the advance "
             "is recovered on an invoice that has a sales order.")

    def _ra_payment_lines(self):
        """Journal items of this payment.

        On Odoo 19 the payment-to-entry link is kept on the journal entry (`origin_payment_id`);
        `move_id` and the item-level `payment_id` can be empty. Try each link in turn.
        """
        self.ensure_one()
        Line = self.env['account.move.line']
        lines = Line.search([('move_id.origin_payment_id', '=', self.id)])
        if not lines:
            lines = Line.search([('payment_id', '=', self.id)])
        if not lines and self.move_id:
            lines = self.move_id.line_ids
        return lines

    def _ra_open_receivable_lines(self):
        """Posted receivable credit lines of this payment that still have an open balance."""
        self.ensure_one()
        return self._ra_payment_lines().filtered(
            lambda l: l.parent_state == 'posted'
            and l.account_id.account_type == 'asset_receivable'
            and l.balance < 0 and l.amount_residual < 0)
