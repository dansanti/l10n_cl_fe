# -*- encoding: utf-8 -*-

from openerp import models, fields, api


class res_partner(models.Model):

    _inherit = 'res.partner'

    state_id = fields.Many2one(
            "res.country.state",
            'Ubication',
            domain="[('country_id','=',country_id),('type','=','normal')]"
        )
    partner_activities_ids = fields.Many2many(
            'partner.activities',
            id1='partner_id',
            id2='activities_id',
            string='Activities Names'
        )

    @api.model
    def _get_default_country(self):
        return self.env.user.company_id.country_id.id or self.env.user.partner_id.country_id.id


    _defaults ={
        'country_id' : lambda self, cr, uid, c: self.pool.get('res.partner')._get_default_country(cr, uid, context=c)
    }

    dte_email = fields.Char('DTE Email')

    @api.constrains('vat')
    def _rut_unique(self):
        for r in self:
            if not r.vat or r.parent_id:
                continue
            partner = self.env['res.partner'].search(
                [
                    ('vat','=', r.vat),
                    ('id','!=', r.id),
                    ('parent_id', '!=', r.id),
                ])
            if r.vat !="CL555555555" and partner:
                raise UserError(_('El rut debe ser único'))
                return False

    def check_vat_cl(self, vat):
        body, vdig = '', ''
        if len(vat) != 9:
            return False
        else:
            body, vdig = vat[:-1], vat[-1].upper()
        try:
            vali = range(2,8) + [2,3]
            operar = '0123456789K0'[11 - (
                sum([int(digit)*factor for digit, factor in zip(
                    body[::-1],vali)]) % 11)]
            if operar == vdig:
                return True
            else:
                return False
        except IndexError:
            return False
