# -*- coding: utf-8 -*-

import base64

from odoo import models, fields, api
from odoo.tools.translate import _

from .signature_key import zero_values

class ResCompany(models.Model):

    _inherit = ["res.company", "signature.key"]
    _name = "res.company"
    
    authorized_users_ids = fields.Many2many('res.users',
       string='Authorized Users')

    @api.multi
    def action_clean1(self):
        self.ensure_one()
        # todo: debe lanzar un wizard que confirme si se limpia o no
        # self.status = 'unverified'
        self.write(zero_values)
        return True

    @api.multi
    def action_process(self):
        self.ensure_one()
        filecontent = base64.b64decode(self.key_file)
        self.load_cert_pk12(filecontent)
        return True