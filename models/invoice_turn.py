# -*- coding: utf-8 -*-

from odoo import models, fields, api


class invoice_turn(models.Model):
    _inherit = "account.invoice"

    invoice_turn = fields.Many2one(
        'partner.activities',
        'Giro',
        readonly=True,
        store=True,
        states={'draft': [('readonly', False)]})
    activity_description = fields.Many2one(
        'sii.activity.description',
        string="Giro",
        related="partner_id.activity_description",
        readonly=True,
    )

    @api.onchange('partner_id')
    def _set_partner_activity(self):
        for inv in self:
            for act in inv.partner_id.partner_activities_ids:
                inv.invoice_turn = act # El último giro, @TODO set default
