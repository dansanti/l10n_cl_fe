# -*- coding: utf-8 -*-
from odoo import fields, models, api

class SiiRegionalOffices(models.Model):
    _name='sii.regional.offices'

    name = fields.Char('Regional Office Name')
    state_ids = fields.Many2many(
        'res.country.state.city',
        id1='sii_regional_office_id',
        id2='state_id',
        string='Counties',
    )
