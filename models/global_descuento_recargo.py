# -*- coding: utf-8 -*-
from odoo import fields, models, api
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)

class GlobalDescuentoRecargo(models.Model):
    _name = "account.invoice.gdr"

    type = fields.Selection(
            [
                ('D', 'Descuento'),
                ('R', 'Recargo'),
            ],
           string="Seleccione Descuento/Recargo Global",
           default='D',
           required=True,
       )
    valor = fields.Float(
            string="Descuento/Recargo Global",
            default=0.00,
            required=True,
        )
    gdr_type = fields.Selection(
            [
                    ('amount','Monto'),
                    ('percent','Porcentaje'),
            ],
            string="Tipo de descuento",
            default="percent",
            required=True,
        )
    gdr_dtail = fields.Char(
            string="Razón del descuento",
        )
    amount_untaxed_global_dr = fields.Float(
            string="Descuento/Recargo Global",
            default=0.00,
            compute='_untaxed_gdr',
        )
    aplicacion = fields.Selection(
            [
                ('flete', 'Flete'),
                ('seguro', 'Seguro'),
            ],
            string="Aplicación del Desc/Rec",
        )
    invoice_id = fields.Many2one(
            'account.invoice',
            string="Factura",
        )

    def _get_afecto(self):
        afecto = 0.00
        for line in self[0].invoice_id.invoice_line_ids:
            for tl in line.invoice_line_tax_ids:
                if tl.amount > 0:
                    afecto += line.price_subtotal
        return afecto

    @api.depends('gdr_type', 'valor', 'type')
    def _untaxed_gdr(self):
        afecto = self._get_afecto()
        des = 0
        rec = 0
        for gdr in self:
            dr = gdr.valor
            if gdr.gdr_type in ['percent']:
                if afecto == 0.00:
                    continue
                #exento = 0 #@TODO Descuento Global para exentos
                if afecto > 0:
                    dr = gdr.invoice_id.currency_id.round((afecto *  (dr / 100.0) ))
            if gdr.type == 'D':
                des += dr
            else:
                rec += dr
            gdr.amount_untaxed_global_dr = dr
        if des >= (afecto + rec):
            raise UserError('El descuento no puede ser mayor o igual a la suma de los recargos + neto')

    def get_agrupados(self):
        result = {'D':0.00, 'R':0.00}
        for gdr in self:
            result[gdr.type] += gdr.amount_untaxed_global_dr
        return result

    def get_monto_aplicar(self):
        grouped = self.get_agrupados()
        monto = 0
        for key, value in grouped.items():
            valor = value
            if key == 'D':
                valor = float(value) * (-1)
            monto += valor
        return monto
