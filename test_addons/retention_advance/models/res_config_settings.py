# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ra_retention_account_id = fields.Many2one(
        related='company_id.ra_retention_account_id', readonly=False,
        domain="[('reconcile', '=', True)]")
    ra_default_retention_pct = fields.Float(
        related='company_id.ra_default_retention_pct', readonly=False)
    ra_journal_id = fields.Many2one(
        related='company_id.ra_journal_id', readonly=False,
        domain="[('type', '=', 'general')]")
