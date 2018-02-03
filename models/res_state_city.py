# -*- encoding: utf-8 -*-
from odoo import fields, models, api
from odoo.tools.translate import _

class res_state_city(models.Model):
    _name = 'res.country.state.city'
    _description = "City of state"

    name = fields.Char(
            'City Name',
            help='The City Name.',
            required=True,
        )
    code = fields.Char(
            string='City Code',
            help='The city code.\n',
            required=True,
        )
    state_id = fields.Many2one(
            'res.country.state',
            string='State',
        )
