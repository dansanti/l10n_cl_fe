# -*- coding: utf-8 -*-
from odoo import models, fields
class partner_activities(models.Model):

    _description = 'SII Economical Activities Printable Description'
    _name = 'sii.activity.description'

    name = fields.Char('Glosa', required=True, translate=True)

    vat_affected = fields.Selection(
        (('SI', 'Si'), ('NO', 'No'), ('ND', 'ND')), 'VAT Affected',
        required=True, translate=True, default='SI')

    active = fields.Boolean(
        'Active', help="Allows you to hide the activity without removing it.")

    _defaults = {
        'active': 1,
    }
