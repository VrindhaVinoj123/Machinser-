# -*- coding: utf-8 -*-
from odoo import models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def action_ra_release_retention(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Release Retention',
            'res_model': 'ra.release.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_partner_id': self.commercial_partner_id.id},
        }
