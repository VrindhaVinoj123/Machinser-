# -*- coding: utf-8 -*-
import base64
import io
from collections import defaultdict

import xlsxwriter

from odoo import _, fields, models


class RaReportWizard(models.TransientModel):
    _name = 'ra.report.wizard'
    _description = 'Retention & Advance Report'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    date_to = fields.Date(string='As at', required=True, default=fields.Date.context_today)
    partner_ids = fields.Many2many('res.partner', string='Customers', help="Leave empty for all customers.")
    line_ids = fields.One2many('ra.report.line', 'wizard_id', string='Lines')

    # --------------------------------------------------------------
    def _ra_compute_data(self):
        """Return {(partner_id, project_id): {column: amount}} in company currency."""
        self.ensure_one()
        company, date_to = self.company_id, self.date_to
        Move = self.env['account.move']
        data = defaultdict(lambda: defaultdict(float))
        partner_ids = set(self.partner_ids.commercial_partner_id.ids)

        def key(partner, project):
            return (partner.commercial_partner_id.id, project.id or 0)

        def wanted(partner):
            return not partner_ids or partner.commercial_partner_id.id in partner_ids

        # Total invoiced: untaxed work done of invoices that carry retention/advance, net of credit notes
        moves = Move.search([
            ('company_id', '=', company.id), ('state', '=', 'posted'), ('date', '<=', date_to),
            ('move_type', 'in', ('out_invoice', 'out_refund'))])
        for move in moves:
            invoice = move if move.move_type == 'out_invoice' else move.reversed_entry_id
            if not invoice or not (invoice.ra_retention_amount or invoice.ra_recovery_amount):
                continue
            if not wanted(move.partner_id):
                continue
            sign = 1 if move.move_type == 'out_invoice' else -1
            data[key(move.partner_id, move.ra_project_id)]['invoiced'] += sign * abs(move.amount_untaxed_signed)

        # Retention / advance entries (reversals are included with the opposite sign)
        helpers = Move.search([
            ('company_id', '=', company.id), ('state', '=', 'posted'), ('date', '<=', date_to),
            ('ra_kind', '!=', False)])
        for helper in helpers:
            invoice = helper.ra_invoice_id
            if not wanted(invoice.partner_id):
                continue
            row = data[key(invoice.partner_id, invoice.ra_project_id)]
            if helper.ra_kind in ('retention', 'return_retention'):
                row['held'] += helper.ra_amount
            elif helper.ra_kind == 'release':
                row['released'] += helper.ra_amount
            else:  # recovery, return_advance
                row['recovered'] += helper.ra_amount

        # Advance received
        payments = self.env['account.payment'].search([
            ('company_id', '=', company.id), ('ra_is_advance', '=', True), ('payment_type', '=', 'inbound'),
            ('state', 'in', ('in_process', 'paid')), ('date', '<=', date_to)])
        for payment in payments:
            if not wanted(payment.partner_id):
                continue
            receivable = payment._ra_payment_lines().filtered(
                lambda l: l.parent_state == 'posted' and l.account_id.account_type == 'asset_receivable')
            data[key(payment.partner_id, payment.ra_sale_order_id)]['received'] += -sum(receivable.mapped('balance'))
        return data

    def action_compute(self):
        self.ensure_one()
        data = self._ra_compute_data()
        Partner, Order = self.env['res.partner'], self.env['sale.order']
        rows = []
        for (partner_id, project_id), v in data.items():
            rows.append({
                'wizard_id': self.id,
                'partner_id': partner_id,
                'project_id': project_id or False,
                'invoiced': v['invoiced'],
                'retention_held': v['held'],
                'retention_released': v['released'],
                'retention_balance': v['held'] - v['released'],
                'advance_received': v['received'],
                'advance_recovered': v['recovered'],
                'advance_balance': v['received'] - v['recovered'],
            })
        rows.sort(key=lambda r: (Partner.browse(r['partner_id']).display_name or '',
                                 Order.browse(r['project_id']).name or '' if r['project_id'] else ''))
        self.line_ids.unlink()
        self.env['ra.report.line'].create(rows)
        return {
            'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
            'view_mode': 'form', 'target': 'current',
        }

    def action_export_xlsx(self):
        self.ensure_one()
        self.action_compute()
        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {'in_memory': True})
        ws = wb.add_worksheet('Retention and Advance')
        title = wb.add_format({'bold': True, 'font_size': 14})
        head = wb.add_format({'bold': True, 'bg_color': '#D9E1F2', 'border': 1, 'text_wrap': True, 'align': 'center'})
        money = wb.add_format({'num_format': '#,##0.00'})
        money_b = wb.add_format({'num_format': '#,##0.00', 'bold': True, 'top': 1})
        bold = wb.add_format({'bold': True, 'top': 1})
        ws.write(0, 0, _("Retention & Advance Report - %s", self.company_id.name), title)
        ws.write(1, 0, _("As at %(date)s - amounts in %(cur)s", date=self.date_to, cur=self.company_id.currency_id.name))
        headers = [_("Customer"), _("Project"), _("Total Invoiced (work done)"), _("Retention Held"),
                   _("Retention Released"), _("Retention Balance"), _("Advance Received"),
                   _("Advance Recovered"), _("Advance Balance")]
        for col, text in enumerate(headers):
            ws.write(3, col, text, head)
        fields_ = ['invoiced', 'retention_held', 'retention_released', 'retention_balance',
                   'advance_received', 'advance_recovered', 'advance_balance']
        row = 4
        for line in self.line_ids:
            ws.write(row, 0, line.partner_id.display_name)
            ws.write(row, 1, line.project_id.name or _("(no project)"))
            for col, name in enumerate(fields_, start=2):
                ws.write_number(row, col, line[name], money)
            row += 1
        if row > 4:
            ws.write(row, 0, _("Total"), bold)
            ws.write(row, 1, '', bold)
            for col, name in enumerate(fields_, start=2):
                letter = xlsxwriter.utility.xl_col_to_name(col)
                ws.write_formula(row, col, '=SUM(%s5:%s%d)' % (letter, letter, row), money_b, sum(self.line_ids.mapped(name)))
        ws.set_column(0, 1, 30)
        ws.set_column(2, 8, 18)
        ws.freeze_panes(4, 2)
        wb.close()
        attachment = self.env['ir.attachment'].create({
            'name': 'retention_advance_report_%s.xlsx' % self.date_to,
            'datas': base64.b64encode(output.getvalue()),
            'type': 'binary',
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {'type': 'ir.actions.act_url', 'url': '/web/content/%s?download=true' % attachment.id, 'target': 'self'}


class RaReportLine(models.TransientModel):
    _name = 'ra.report.line'
    _description = 'Retention & Advance Report Line'

    wizard_id = fields.Many2one('ra.report.wizard', required=True, ondelete='cascade')
    currency_id = fields.Many2one(related='wizard_id.company_id.currency_id')
    partner_id = fields.Many2one('res.partner', string='Customer')
    project_id = fields.Many2one('sale.order', string='Project')
    invoiced = fields.Monetary(string='Total Invoiced', currency_field='currency_id')
    retention_held = fields.Monetary(string='Retention Held', currency_field='currency_id')
    retention_released = fields.Monetary(string='Retention Released', currency_field='currency_id')
    retention_balance = fields.Monetary(string='Retention Balance', currency_field='currency_id')
    advance_received = fields.Monetary(string='Advance Received', currency_field='currency_id')
    advance_recovered = fields.Monetary(string='Advance Recovered', currency_field='currency_id')
    advance_balance = fields.Monetary(string='Advance Balance', currency_field='currency_id')
