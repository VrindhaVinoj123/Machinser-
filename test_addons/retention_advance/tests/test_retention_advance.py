# -*- coding: utf-8 -*-
from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestRetentionAdvance(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.company_data['company']
        cls.retention_account = cls.env['account.account'].with_company(cls.company).create({
            'code': 'RET001', 'name': 'Retention Receivable',
            'account_type': 'asset_current', 'reconcile': True,
            'company_ids': [Command.set(cls.company.ids)],
        })
        cls.company.write({'ra_retention_account_id': cls.retention_account.id})
        cls.payment = cls._make_payment(200000)

    @classmethod
    def _make_payment(cls, amount, currency=None):
        payment = cls.env['account.payment'].create({
            'payment_type': 'inbound', 'partner_type': 'customer', 'partner_id': cls.partner_a.id,
            'amount': amount, 'currency_id': (currency or cls.company.currency_id).id,
            'journal_id': cls.company_data['default_journal_bank'].id,
            'date': '2026-01-01', 'ra_is_advance': True,
        })
        payment.action_post()
        return payment

    def _invoice(self, price=100000, currency=None, retention_pct=10.0, recovery_pct=20.0, post=True):
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': self.partner_a.id, 'invoice_date': '2026-01-31',
            'currency_id': (currency or self.company.currency_id).id,
            'ra_retention_pct': retention_pct, 'ra_recovery_pct': recovery_pct,
            'ra_advance_payment_id': self.payment.id, 'ra_handover_date': '2027-01-31',
            'invoice_line_ids': [Command.create({
                'product_id': self.product_a.id, 'quantity': 1, 'price_unit': price,
                'tax_ids': [Command.set(self.company_data['default_tax_sale'].ids)],
            })],
        })
        if post:
            invoice.action_post()
        return invoice

    def _retention_balance(self):
        lines = self.env['account.move.line'].search([
            ('account_id', '=', self.retention_account.id), ('parent_state', '=', 'posted')])
        return sum(lines.mapped('balance'))

    def _advance_left(self):
        return -sum(self.payment._ra_open_receivable_lines().mapped('amount_residual'))

    def _release(self, amount, date='2026-12-31'):
        wizard = self.env['ra.release.wizard'].create({'partner_id': self.partner_a.id, 'date': date})
        wizard.invalidate_recordset()
        wizard.line_ids.unlink()
        for vals in wizard._ra_line_vals(self.partner_a, self.company):
            wizard.write({'line_ids': [Command.create(vals)]})
        wizard.line_ids[:1].release_amount = amount
        wizard.action_release()

    # ------------------------------------------------------------------
    def test_example_from_the_task(self):
        invoice = self._invoice()
        self.assertEqual(invoice.amount_total, 115000)
        self.assertEqual(invoice.ra_amount_to_pay, 85000)
        self.assertEqual(invoice.amount_residual, 85000)
        self.assertEqual(self._retention_balance(), 10000)
        self.assertEqual(self._advance_left(), 180000)

    def test_over_recovery_is_blocked(self):
        with self.assertRaises(ValidationError):
            self._invoice(price=2000000, recovery_pct=20.0, post=False)

    def test_partial_release(self):
        self._invoice()
        self._release(4000)
        self.assertEqual(self._retention_balance(), 6000)

    def test_partial_credit_note(self):
        invoice = self._invoice()
        wizard = self.env['account.move.reversal'].with_context(
            active_model='account.move', active_ids=invoice.ids).create({'journal_id': invoice.journal_id.id})
        credit_note = self.env['account.move'].browse(wizard.refund_moves()['res_id'])
        credit_note.invoice_line_ids.price_unit = 50000
        credit_note.action_post()
        self.assertEqual(credit_note.ra_cn_ratio, 0.5)
        self.assertEqual(self._retention_balance(), 5000)
        self.assertEqual(self._advance_left(), 180000)  # returned advance is a separate open credit

    def test_reset_to_draft_and_repost_does_not_duplicate(self):
        invoice = self._invoice()
        invoice.button_draft()
        self.assertEqual(self._retention_balance(), 0)
        self.assertEqual(self._advance_left(), 200000)
        invoice.action_post()
        self.assertEqual(self._retention_balance(), 10000)
        self.assertEqual(self._advance_left(), 180000)
        self.assertEqual(len(invoice._ra_active_helpers(('retention',))), 1)
        self.assertEqual(len(invoice._ra_active_helpers(('recovery',))), 1)

    def test_reset_blocked_after_release(self):
        invoice = self._invoice()
        self._release(10000)
        with self.assertRaises(UserError):
            invoice.button_draft()

    def test_foreign_currency_invoice(self):
        currency = self.currency_data['currency']
        invoice = self._invoice(currency=currency)
        self.assertEqual(invoice.amount_residual, 85000)
        self.assertEqual(invoice.ra_retention_amount, 10000)
