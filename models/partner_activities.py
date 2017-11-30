# -*- coding: utf-8 -*-
from odoo import models, fields

class PartnerActivities(models.Model):
    _name = 'partner.activities'
    _description = 'SII Economical Activities'

    code = fields.Char('Activity Code', required=True, translate=True)

    parent_id = fields.Many2one(
        'partner.activities', 'Parent Activity', select=True,
        ondelete='cascade')

    name = fields.Char('Nombre Completo', required=True, translate=True)

    vat_affected = fields.Selection(
        (('SI', 'Si'), ('NO', 'No'), ('ND', 'ND')), 'VAT Affected',
        required=True, translate=True, default='SI')

    tax_category = fields.Selection(
        (('1', '1'), ('2', '2'), ('ND', 'ND')), 'TAX Category', required=True,
        translate=True, default='1')

    internet_available = fields.Boolean('Available at Internet')

    active = fields.Boolean(
        'Active', help="Allows you to hide the activity without removing it.")

    partner_ids = fields.Many2many(
        'res.partner', id1='activities_id', id2='partner_id',
        string='Partners')

    journal_ids = fields.Many2many(
        'account.journal',
        id1='activities_id',
        id2='journal_id',
        string='Journals',
    )

    _defaults = {
        'active': 1,
        'internet_available': 1
    }
