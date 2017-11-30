# -*- encoding: utf-8 -*-

from odoo import models, fields


class res_state(models.Model):

    def name_get(self, cr, uid, ids, context=None):
        if not len(ids):
            return []
        res = []
        for state in self.browse(cr, uid, ids, context=context):
            data = []
            acc = state
            while acc:
                data.insert(0, acc.name)
                acc = acc.parent_id
            data = ' / '.join(data)
            res.append((state.id, (state.code and '[' + state.code + '] ' or '') + data))

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
                operand1,operand2 = name.split(': ',1) #name can contain spaces e.g. odoo S.A.
                ids = self.search(cr, user, [('name', operator, operand2)]+ args, limit=limit)
        else:
            ids = self.search(cr, user, args, context=context, limit=limit)
        return self.name_get(cr, user, ids, context=context)

    def _name_get_fnc(self, cr, uid, ids, prop, unknow_none, context=None):
        if not ids:
            return []
        res = []
        for state in self.browse(cr, uid, ids, context=context):
            data = []
            acc = state
            while acc:
                data.insert(0, acc.name)
                acc = acc.parent_id
            data = ' / '.join(data)
            res.append((state.id, data))
        return dict(res)

    _inherit = 'res.country.state'

    code = fields.Char('State Code', size=32,help='The state code.\n', required=True)
    complete_name = fields.Char(compute='_name_get_fnc', string='Complete Name', fnct_search=complete_name_search)
    parent_id = fields.Many2one('res.country.state','Parent State', index=True, domain=[('type','=','view')])
    child_ids = fields.One2many('res.country.state', 'parent_id', string='Child States')
    type = fields.Selection([('view','View'), ('normal','Normal')], 'Type')

    _defaults = {
            'type': 'normal',
        }
