from openerp import api, fields, models, _

class SO(models.Model):
    _inherit = 'sale.order'

    @api.multi
    def _prepare_invoice(self):
        order_dict = super(SO, self)._prepare_invoice()
        available_turn_ids = self.company_id.company_activities_ids
        for turn in available_turn_ids:
            order_dict['turn_issuer'] = turn.id

        return order_dict
