# -*- coding: utf-8 -*-
from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class RaReleaseWizard(models.TransientModel):
    _name = 'ra.release.wizard'
    _description = 'Release Retention'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    partner_id = fields.Many2one('res.partner', string='Customer', required=True)
    date = fields.Date(
        string='Release Date', required=True, default=fields.Date.context_today,
        help="Accounting date and due date of the released amount.")
    line_ids = fields.One2many('ra.release.wizard.line', 'wizard_id', string='Retention')

    # --------------------------------------------------------------
    @api.model
    def _ra_line_vals(self, partner, company):
        account = company.ra_retention_account_id
        if not account or not partner:
            return []
        lines = self.env['account.move.line'].search([
            ('company_id', '=', company.id),
            ('account_id', '=', account.id),
            ('move_id.ra_kind', '=', 'retention'),
            ('move_id.state', '=', 'posted'),
            ('move_id.reversed_entry_id', '=', False),
            ('partner_id', 'child_of', partner.commercial_partner_id.id),
            ('balance', '>', 0),
            ('amount_residual', '>', 0),
        ], order='date, id')
        vals = []
        for line in lines:
            invoice = line.move_id.ra_invoice_id
            vals.append({
                'retention_line_id': line.id,
                'invoice_id': invoice.id,
                'project_id': invoice.ra_project_id.id,
                'handover_date': line.date_maturity,
                'currency_id': line.currency_id.id,
                'retained_amount': line.amount_currency,
                'remaining_amount': line.amount_residual_currency,
                'release_amount': 0.0,
            })
        return vals

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        partner_id = res.get('partner_id') or self.env.context.get('default_partner_id')
        if partner_id and 'line_ids' in fields_list:
            partner = self.env['res.partner'].browse(partner_id)
            company = self.env['res.company'].browse(res.get('company_id') or self.env.company.id)
            res['line_ids'] = [Command.create(v) for v in self._ra_line_vals(partner, company)]
        return res

    @api.onchange('partner_id', 'company_id')
    def _onchange_partner_id(self):
        commands = [Command.clear()]
        commands += [Command.create(v) for v in self._ra_line_vals(self.partner_id, self.company_id)]
        self.line_ids = commands

    # --------------------------------------------------------------
    def action_fill_full(self):
        self.ensure_one()
        for line in self.line_ids:
            line.release_amount = line.remaining_amount
        return self._reopen()

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
            'view_mode': 'form', 'target': 'new',
        }

    def _ra_create_release(self, ret_line, amount):
        """Dr Receivable / Cr Retention Receivable for `amount`, reconciled with the retention line."""
        move = ret_line.move_id
        invoice = move.ra_invoice_id
        currency = ret_line.currency_id
        if currency.is_zero(amount - ret_line.amount_residual_currency):
            balance = ret_line.amount_residual
        else:
            balance = invoice.company_currency_id.round(
                ret_line.amount_residual * amount / ret_line.amount_residual_currency)
        receivable_line = move.line_ids.filtered(lambda l: l.balance < 0)[:1]
        ref = _("Retention release - %s", invoice.name)
        entry = self.env['account.move']._ra_create_entry(
            'release', invoice, invoice, self.date, ref, currency,
            [(receivable_line.account_id, receivable_line.partner_id, amount, balance, self.date),
             (ret_line.account_id, ret_line.partner_id, -amount, -balance, self.date)], balance)
        (entry.line_ids.filtered(lambda l: l.balance < 0) | ret_line).reconcile()
        return entry

    def action_release(self):
        self.ensure_one()
        lines = self.line_ids.filtered(lambda l: l.release_amount)
        if not lines:
            raise UserError(_("Enter an amount to release on at least one line."))
        entries = self.env['account.move']
        for line in lines:
            ret_line = line.retention_line_id
            if ret_line.company_id != self.company_id:
                raise UserError(_("Retention lines must belong to the selected company."))
            if line.release_amount < 0 or line.currency_id.compare_amounts(
                    line.release_amount, ret_line.amount_residual_currency) > 0:
                raise UserError(_(
                    "You cannot release %(amount)s on %(invoice)s: only %(left)s is still held.",
                    amount=line.currency_id.format(line.release_amount), invoice=line.invoice_id.name,
                    left=line.currency_id.format(ret_line.amount_residual_currency)))
            # Lock dates are enforced by Odoo when the entry is posted; the whole release then rolls back.
            entries |= self._ra_create_release(ret_line, line.release_amount)
        return {
            'type': 'ir.actions.act_window', 'name': _("Retention Releases"), 'res_model': 'account.move',
            'view_mode': 'list,form', 'domain': [('id', 'in', entries.ids)],
        }


class RaReleaseWizardLine(models.TransientModel):
    _name = 'ra.release.wizard.line'
    _description = 'Release Retention Line'

    wizard_id = fields.Many2one('ra.release.wizard', required=True, ondelete='cascade')
    retention_line_id = fields.Many2one('account.move.line', string='Retention Item', required=True)
    invoice_id = fields.Many2one('account.move', string='Invoice')
    project_id = fields.Many2one('sale.order', string='Project')
    handover_date = fields.Date(string='Handover Date')
    currency_id = fields.Many2one('res.currency')
    retained_amount = fields.Monetary(string='Retained', currency_field='currency_id')
    remaining_amount = fields.Monetary(string='Still Held', currency_field='currency_id')
    release_amount = fields.Monetary(string='Release', currency_field='currency_id')

    @api.constrains('release_amount')
    def _check_release_amount(self):
        for line in self:
            ret_line = line.retention_line_id
            remaining = ret_line.amount_residual_currency
            if line.release_amount < 0 or ret_line.currency_id.compare_amounts(line.release_amount, remaining) > 0:
                raise ValidationError(_("The amount to release must be between 0 and the retention still held."))
            # if line.release_amount < 0 or line.currency_id.compare_amounts(
            #         line.release_amount, line.remaining_amount) > 0:
            #     raise ValidationError(_("The amount to release must be between 0 and the retention still held."))
