# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    ra_retention_account_id = fields.Many2one(
        'account.account', string='Retention Receivable Account',
        domain="[('reconcile', '=', True)]",
        help="Reconcilable account where retention held back by customers is booked.")
    ra_default_retention_pct = fields.Float(
        string='Default Retention %', digits=(5, 2), default=0.0,
        help="Pre-filled on new customer invoices. The user can change it per invoice.")
    ra_journal_id = fields.Many2one(
        'account.journal', string='Retention Journal', domain="[('type', '=', 'general')]",
        help="Miscellaneous journal used for the retention / advance entries. "
             "If empty, the first miscellaneous journal of the company is used.")
