# -*- coding: utf-8 -*-
from odoo import fields, models, api

class SiiRegionalOffices(models.Model):
    _name='sii.regional.offices'

    name = fields.Char('Regional Office Name')
    city_ids = fields.Many2many(
        'res.city',
        id1='sii_regional_office_id',
        id2='city_id',
        string='Ciudades',
    )
