# -*- encoding: utf-8 -*-
from odoo import fields, models

class res_state_city(models.Model):

    def name_get(self, cr, uid, ids, context=None):
        if not len(ids):
            return []
        res = []
        for city in self.browse(cr, uid, ids, context=context):
            res.append((city.id, (city.code and '[' + city.code + '] ' or '') + city.name))

        return res


    def complete_name_search(self, cr, user, name, args=None, operator='ilike', context=None, limit=100):
        if not args:
            args = []
        args = args[:]
        ids = []
        if name:
            ids = self.search(cr, user, [('name', operator, name)]+ args, limit=limit)
            if not ids and len(name.split()) >= 2:
                #Separating code and name of account for searching
                operand1,operand2 = name.split(': ',1) #name can contain spaces e.g. OpenERP S.A.
                ids = self.search(cr, user, [('name', operator, operand2)]+ args, limit=limit)
        else:
            ids = self.search(cr, user, args, context=context, limit=limit)
        return self.name_get(cr, user, ids, context=context)

    def _name_get_fnc(self, cr, uid, ids, prop, unknow_none, context=None):
        if not ids:
            return []
        res = []
        for city in self.browse(cr, uid, ids, context=context):
            data = []
            acc = city
            while acc:
                data.insert(0, acc.name)
                if hasattr(acc,'state_id'):
                    acc = acc.state_id
                else :
                    acc = acc.parent_id
            data = ' / '.join(data)
            res.append((city.id, data))
        return dict(res)

    _name = 'res.country.state.city'
    _description = "City of state"

    name = fields.Char('City Name',help='The City Name.',required=True)
    code = fields.Char('City Code', size=32,help='The city code.\n', required=True)
    #complete_name = fields.Char(compute="_name_get_fnc", string='Complete Name', fnct_search=complete_name_search)
    country_id = fields.Many2one('res.country', 'Country', required=True)
    state_id = fields.Many2one('res.country.state','State', index=True, domain="[('country_id','=',country_id),('type','=','normal')]")
    type = fields.Selection([('view','View'), ('normal','Normal')], 'Type')

    _defaults = {
            'type': 'normal',
        }
