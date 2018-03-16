# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError
from datetime import datetime, timedelta, date
from lxml import etree
from lxml.etree import Element, SubElement
from odoo import SUPERUSER_ID
from odoo.tools.translate import _

import logging
_logger = logging.getLogger(__name__)

import xml.dom.minidom
import pytz
from six import string_types
import struct

import socket
import collections

try:
    from io import BytesIO
except:
    _logger.warning("no se ha cargado io")
import traceback as tb
import suds.metrics as metrics

try:
    from suds.client import Client
except:
    pass

try:
    import urllib3
except:
    pass

try:
    urllib3.disable_warnings()
except:
    pass

try:
    pool = urllib3.PoolManager()
except:
    pass

try:
    import textwrap
except:
    pass

try:
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    import OpenSSL
    from OpenSSL import crypto
    type_ = crypto.FILETYPE_PEM
except:
    _logger.warning('Cannot import OpenSSL library')

try:
    import dicttoxml
except ImportError:
    _logger.warning('Cannot import dicttoxml library')

try:
    import pdf417gen
except ImportError:
    _logger.warning('Cannot import pdf417gen library')

try:
    import base64
except ImportError:
    _logger.warning('Cannot import base64 library')

try:
    import hashlib
except ImportError:
    _logger.warning('Cannot import hashlib library')

try:
    import cchardet
except ImportError:
    _logger.warning('Cannot import cchardet library')

try:
    from signxml import XMLSigner, methods
except ImportError:
    _logger.warning('Cannot import signxml')

# timbre patrón. Permite parsear y formar el
# ordered-dict patrón corespondiente al documento
timbre  = """<TED version="1.0"><DD><RE>99999999-9</RE><TD>11</TD><F>1</F>\
<FE>2000-01-01</FE><RR>99999999-9</RR><RSR>\
XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX</RSR><MNT>10000</MNT><IT1>IIIIIII\
</IT1><CAF version="1.0"><DA><RE>99999999-9</RE><RS>YYYYYYYYYYYYYYY</RS>\
<TD>10</TD><RNG><D>1</D><H>1000</H></RNG><FA>2000-01-01</FA><RSAPK><M>\
DJKFFDJKJKDJFKDJFKDJFKDJKDnbUNTAi2IaDdtAndm2p5udoqFiw==</M><E>Aw==</E></RSAPK>\
<IDK>300</IDK></DA><FRMA algoritmo="SHA1withRSA">\
J1u5/1VbPF6ASXkKoMOF0Bb9EYGVzQ1AMawDNOy0xSuAMpkyQe3yoGFthdKVK4JaypQ/F8\
afeqWjiRVMvV4+s4Q==</FRMA></CAF><TSTED>2014-04-24T12:02:20</TSTED></DD>\
<FRMT algoritmo="SHA1withRSA">jiuOQHXXcuwdpj8c510EZrCCw+pfTVGTT7obWm/\
fHlAa7j08Xff95Yb2zg31sJt6lMjSKdOK+PQp25clZuECig==</FRMT></TED>"""

try:
    import xmltodict
    result = xmltodict.parse(timbre)
except ImportError:
    _logger.warning('Cannot import xmltodict library')

server_url = {
    'SIICERT':'https://maullin.sii.cl/DTEWS/',
    'SII':'https://palena.sii.cl/DTEWS/',
}

claim_url = {
    'SIICERT': 'https://ws2.sii.cl/WSREGISTRORECLAMODTECERT/registroreclamodteservice',
    'SII':'https://ws1.sii.cl/WSREGISTRORECLAMODTE/registroreclamodteservice',
}

BC = '''-----BEGIN CERTIFICATE-----\n'''
EC = '''\n-----END CERTIFICATE-----\n'''

# hardcodeamos este valor por ahora
import os, sys
USING_PYTHON2 = True if sys.version_info < (3, 0) else False
xsdpath = os.path.dirname(os.path.realpath(__file__)).replace('/models','/static/xsd/')

connection_status = {
    '0': 'Upload OK',
    '1': 'El Sender no tiene permiso para enviar',
    '2': 'Error en tamaño del archivo (muy grande o muy chico)',
    '3': 'Archivo cortado (tamaño <> al parámetro size)',
    '5': 'No está autenticado',
    '6': 'Empresa no autorizada a enviar archivos',
    '7': 'Esquema Invalido',
    '8': 'Firma del Documento',
    '9': 'Sistema Bloqueado',
    'Otro': 'Error Interno.',
}

TYPE2JOURNAL = {
    'out_invoice': 'sale',
    'in_invoice': 'purchase',
    'out_refund': 'sale',
    'in_refund': 'purchase',
}

class AccountInvoiceLine(models.Model):
    _inherit = 'account.invoice.line'

    @api.depends('price_unit', 'discount', 'invoice_line_tax_ids', 'quantity',
        'product_id', 'invoice_id.partner_id', 'invoice_id.currency_id', 'invoice_id.company_id')
    def _compute_price(self):
        for line in self:
            currency = line.invoice_id and line.invoice_id.currency_id or None
            taxes = False
            total = 0
            if line.invoice_line_tax_ids:
                taxes = line.invoice_line_tax_ids.compute_all(line.price_unit, currency, line.quantity, product=line.product_id, partner=line.invoice_id.partner_id, discount=line.discount)
            if taxes:
                line.price_subtotal = price_subtotal_signed = taxes['total_excluded']
            else:
                total = line.currency_id.round((line.quantity * line.price_unit))
                total_discount = line.currency_id.round((total * ((line.discount or 0.0) / 100.0)))
                total -= total_discount
                line.price_subtotal = price_subtotal_signed = total
            if line.invoice_id.currency_id and line.invoice_id.currency_id != line.invoice_id.company_id.currency_id:
                price_subtotal_signed = line.invoice_id.currency_id.with_context(date=line.invoice_id._get_currency_rate_date()).compute(price_subtotal_signed, line.invoice_id.company_id.currency_id)
            sign = line.invoice_id.type in ['in_refund', 'out_refund'] and -1 or 1
            line.price_subtotal_signed = price_subtotal_signed * sign
            line.price_tax_included = taxes['total_included'] if (taxes and taxes['total_included'] > total) else total

    price_tax_included = fields.Monetary(string='Amount', readonly=True, compute='_compute_price')

class AccountInvoiceTax(models.Model):
    _inherit = "account.invoice.tax"

    def _getNeto(self, currency):
        neto = 0
        for tax in self:
            base = tax.base
            price_tax_included = 0
            #amount_tax +=tax.amount
            for line in tax.invoice_id.invoice_line_ids:
                if tax.tax_id in line.invoice_line_tax_ids and tax.tax_id.price_include:
                    price_tax_included += line.price_tax_included
            if price_tax_included > 0 and  tax.tax_id.sii_type in ["R"] and tax.tax_id.amount > 0:
                base = currency.round(price_tax_included)
            elif price_tax_included > 0 and tax.tax_id.amount > 0:
                base = currency.round(price_tax_included / ( 1 + tax.tax_id.amount / 100.0))
            neto += base
        return neto

    amount_retencion = fields.Monetary(
            string="Retención",
            default=0.00,
        )
    retencion_account_id = fields.Many2one(
            'account.account',
            string='Tax Account',
            domain=[('deprecated', '=', False)],
        )


class Referencias(models.Model):
    _name = 'account.invoice.referencias'

    origen = fields.Char(
            string="Origin",
            )
    sii_referencia_TpoDocRef =  fields.Many2one(
            'sii.document_class',
            string="SII Reference Document Type",
        )
    sii_referencia_CodRef = fields.Selection(
            [
                ('1','Anula Documento de Referencia'),
                ('2','Corrige texto Documento Referencia'),
                ('3','Corrige montos')
            ],
            string="SII Reference Code",
        )
    motivo = fields.Char(
            string="Motivo",
        )
    invoice_id = fields.Many2one(
            'account.invoice',
            ondelete='cascade',
            index=True,
            copy=False,
            string="Documento",
        )
    fecha_documento = fields.Date(
            string="Fecha Documento",
            required=True,
        )

class AccountInvoice(models.Model):
    _inherit = "account.invoice"

    def _default_journal_document_class_id(self, default=None):
        ids = self._get_available_journal_document_class()
        document_classes = self.env['account.journal.sii_document_class'].browse(ids)
        if default:
            for dc in document_classes:
                if dc.sii_document_class_id.id == default:
                    self.journal_document_class_id = dc.id
        elif document_classes:
            default = self.get_document_class_default(document_classes)
        return default

    def _domain_journal_document_class_id(self):
        domain = self._get_available_journal_document_class()
        return [('id', 'in', domain)]

    turn_issuer = fields.Many2one(
        'partner.activities',
        'Giro Emisor',
        readonly=True,
        store=True,
        required=False,
        states={'draft': [('readonly', False)]},
        )
    vat_discriminated = fields.Boolean(
            'Discriminate VAT?',
            compute="get_vat_discriminated",
            store=True,
            readonly=False,
            help="Discriminate VAT on Quotations and Sale Orders?",
        )
    available_journal_document_class_ids = fields.Many2many(
            'account.journal.sii_document_class',
            #    compute='_get_available_journal_document_class',
            string='Available Journal Document Classes',
        )
    journal_document_class_id = fields.Many2one(
            'account.journal.sii_document_class',
            string='Documents Type',
            default=lambda self: self._default_journal_document_class_id(),
            domain=_domain_journal_document_class_id,
            readonly=True,
            store=True,
            states={'draft': [('readonly', False)]},
        )
    sii_document_class_id = fields.Many2one(
            'sii.document_class',
            related='journal_document_class_id.sii_document_class_id',
            string='Document Type',
            copy=False,
            readonly=True,
            store=True,
        )
    sii_document_number = fields.Char(
        string='Document Number',
        copy=False,
        readonly=True,)
    responsability_id = fields.Many2one(
        'sii.responsability',
        string='Responsability',
        related='commercial_partner_id.responsability_id',
        store=True,
        )
    iva_uso_comun = fields.Boolean(
            string="Uso Común",
            readonly=True,
            states={'draft': [('readonly', False)]}
        ) # solamente para compras tratamiento del iva
    no_rec_code = fields.Selection(
            [
                    ('1','Compras destinadas a IVA a generar operaciones no gravados o exentas.'),
                    ('2','Facturas de proveedores registrados fuera de plazo.'),
                    ('3','Gastos rechazados.'),
                    ('4','Entregas gratuitas (premios, bonificaciones, etc.) recibidos.'),
                    ('9','Otros.')
            ],
            string="Código No recuperable",
            readonly=True,
            states={'draft': [('readonly', False)]},
        )# @TODO select 1 automático si es emisor 2Categoría

    document_number = fields.Char(
            compute='_get_document_number',
            string='Document Number',
            readonly=True,
        )
    next_invoice_number = fields.Integer(
            related='journal_document_class_id.sequence_id.number_next_actual',
            string='Next Document Number',
            readonly=True,
        )
    use_documents = fields.Boolean(
            related='journal_id.use_documents',
            string='Use Documents?',
            readonly=True,
        )
    referencias = fields.One2many(
            'account.invoice.referencias',
            'invoice_id',
            readonly=True,
            states={'draft': [('readonly', False)]},
    )
    forma_pago = fields.Selection(
            [
                    ('1','Contado'),
                    ('2','Crédito'),
                    ('3','Gratuito')
            ]
            ,string="Forma de pago",
            readonly=True,
            states={'draft': [('readonly', False)]},
            default='1',
        )
    contact_id = fields.Many2one(
            'res.partner',
            string="Contacto",
        )
    amount_retencion = fields.Monetary(
            string="Retención",
            default=0.00,
            compute='_compute_amount',
        )
    sii_batch_number = fields.Integer(
            copy=False,
            string='Batch Number',
            readonly=True,
            help='Batch number for processing multiple invoices together',
        )
    sii_barcode = fields.Char(
            copy=False,
            string=_('SII Barcode'),
            readonly=True,
            help='SII Barcode Name',
        )
    sii_barcode_img = fields.Binary(
            copy=False,
            string=_('SII Barcode Image'),
            help='SII Barcode Image in PDF417 format',
        )
    sii_receipt = fields.Text(
            string='SII Mensaje de recepción',
            copy=False,
        )
    sii_message = fields.Text(
        string='SII Message',
        copy=False)
    sii_xml_dte = fields.Text(
        string='SII XML DTE',
        copy=False)
    sii_xml_request = fields.Text(
        string='SII XML Request',
        copy=False)
    sii_xml_exchange = fields.Text(
        string='SII XML Exchange',
        copy=False)
    sii_xml_response = fields.Text(
        string='SII XML Response',
        copy=False)
    sii_send_ident = fields.Text(
        string='SII Send Identification',
        copy=False)
    sii_result = fields.Selection(
        [
            ('', 'n/a'),
            ('NoEnviado', 'No Enviado'),
            ('EnCola','En cola de envío'),
            ('Enviado', 'Enviado'),
            ('Aceptado', 'Aceptado'),
            ('Rechazado', 'Rechazado'),
            ('Reparo', 'Reparo'),
            ('Proceso', 'Procesado'),
            ('Reenviar', 'Reenviar'),
            ('Anulado', 'Anulado')
        ],
        string='Resultado',
        readonly=True,
        states={'draft': [('readonly', False)]},
        copy=False,
        help="SII request result",
        default = '')
    canceled = fields.Boolean(
            string="Canceled?",
        )
    estado_recep_dte = fields.Selection(
        [
            ('recibido', 'Recibido en DTE'),
            ('mercaderias','Recibido mercaderias'),
            ('validate','Validada Comercial')
        ],
        string="Estado de Recepcion del Envio",
        default='recibido',
    )
    estado_recep_glosa = fields.Char(
        string="Información Adicional del Estado de Recepción",
    )
    sii_send_file_name = fields.Char(
        string="Send File Name",
    )
    responsable_envio = fields.Many2one(
        'res.users',
    )
    ticket = fields.Boolean(string="Formato Ticket",
            default=False,
            readonly=True,
            states={'draft': [('readonly', False)]},
    )
    claim = fields.Selection(
        [
            ('ACD', 'Acepta Contenido del Documento'),
            ('RCD', 'Reclamo al  Contenido del Documento '),
            ('ERM', ' Otorga  Recibo  de  Mercaderías  o Servicios'),
            ('RFP', 'Reclamo por Falta Parcial de Mercaderías'),
            ('RFT', 'Reclamo por Falta Total de Mercaderías'),
        ],
        string="Reclamo",
    )
    claim_description = fields.Char(
        string="Detalle Reclamo",
        readonly=True,
    )
    purchase_to_done = fields.Many2many(
            'purchase.order',
            string="Ordenes de Compra a validar",
            domain=[('state', 'not in',['done', 'cancel'] )],
            readonly=True,
            states={'draft': [('readonly', False)]},
    )
    activity_description = fields.Many2one(
            'sii.activity.description',
            string="Giro",
            related="partner_id.activity_description",
            readonly=True,
    )
    amount_untaxed_global_discount = fields.Float(
            string="Global Discount Amount",
            store=True,
            default=0.00,
            compute='_compute_amount',
        )
    amount_untaxed_global_recargo = fields.Float(
            string="Global Recargo Amount",
            store=True,
            default=0.00,
            compute='_compute_amount',
        )
    global_descuentos_recargos = fields.One2many(
            'account.invoice.gdr',
            'invoice_id',
            string="Descuentos / Recargos globales",
            readonly=True,
            states={'draft': [('readonly', False)]},
        )

    @api.multi
    def compute_invoice_totals(self, company_currency, invoice_move_lines):
        '''
            @TODO Agregar Descuento Global como Concepto a parte en el caso de que sea asociado a una aplicación
        '''
        total = 0
        total_currency = 0
        amount_diff = self.amount_total
        amount_diff_currency = 0
        gdr = self.porcentaje_dr()
        if self.currency_id != company_currency:
            currency = self.currency_id.with_context(date=self.date_invoice or fields.Date.context_today(self))
            amount_diff = currency.compute(self.amount_total, company_currency)
            amount_diff_currency = self.amount_total
        for line in invoice_move_lines:
            if not line.get('tax_line_id'):
                line['price'] *= gdr
            if line.get('amount_currency', False) and not line.get('tax_line_id'):
                line['amount_currency'] *= gdr
            if self.currency_id != company_currency:
                if not (line.get('currency_id') and line.get('amount_currency')):
                    line['currency_id'] = currency.id
                    line['amount_currency'] = currency.round(line['price'])
                    line['price'] = currency.compute(line['price'], company_currency)
            else:
                line['currency_id'] = False
                line['amount_currency'] = False
                line['price'] = self.currency_id.round(line['price'])
            ##para chequeo diferencia
            amount_diff -= line['price']
            if line.get('amount_currency', False):
                amount_diff_currency -= line['amount_currency']
            if self.type in ('out_invoice', 'in_refund'):
                total += line['price']
                total_currency += line['amount_currency'] or line['price']
                line['price'] = - line['price']
            else:
                total -= line['price']
                total_currency -= line['amount_currency'] or line['price']
        if amount_diff != 0:
            if self.type in ('out_invoice', 'in_refund'):
                invoice_move_lines[0]['price'] -= amount_diff
            else:
                invoice_move_lines[0]['price'] += amount_diff
            total += amount_diff
        if amount_diff_currency !=0:
            invoice_move_lines[0]['amount_currency'] += amount_diff_currency
            total_currency += amount_diff_currency
        return total, total_currency, invoice_move_lines

    #Se retomará en la próxima actualización para poder dar soporte a factura de compras
    #@api.multi
    #def finalize_invoice_move_lines(self, move_lines):
    #    if self.global_descuentos_recargos:
    #        move_lines = self._gd_move_lines(move_lines)
    #    taxes = self.tax_line_move_line_get()
    #    retencion = 0
    #    for t in taxes:
    #        if t['name'].find('RET - ', 0, 6) > -1:
    #            retencion += t['price']
    #    retencion = round(retencion)
    #    dif = 0
    #    total = self.amount_total
    #    for line in move_lines:
    #        if line[2]['name'] == '/' or line[2]['name'] == self.name:
    #            if line[2]['credit'] > 0:
    #                dif = total - line[2]['credit']
    #            else:
    #                dif = total - line[2]['debit']
    #    if dif != 0:
    #        move_lines = self._repairDiff( move_lines, dif)
    #    return move_lines

    @api.depends('invoice_line_ids.price_subtotal', 'tax_line_ids.amount', 'tax_line_ids.amount_rounding',
                 'currency_id', 'company_id', 'date_invoice', 'type', 'global_descuentos_recargos')
    def _compute_amount(self):
        for inv in self:
            neto = 0
            if inv.global_descuentos_recargos:
                neto = inv.global_descuentos_recargos.get_monto_aplicar()
                agrupados = inv.global_descuentos_recargos.get_agrupados()
                inv.amount_untaxed_global_discount = agrupados['D']
                inv.amount_untaxed_global_recargo = agrupados['R']
            amount_tax = 0
            amount_retencion = 0
            included = False
            for tax in inv.tax_line_ids:
                if tax.tax_id.price_include:
                    included = True
                amount_tax += tax.amount
                amount_retencion  += tax.amount_retencion
            inv.amount_retencion = amount_retencion
            if included:
                neto += inv.tax_line_ids._getNeto(inv.currency_id)
                amount_retencion  += amount_retencion
            else:
                neto += sum(line.price_subtotal for line in inv.invoice_line_ids)
            inv.amount_untaxed = neto
            inv.amount_tax = amount_tax
            inv.amount_total = inv.amount_untaxed + inv.amount_tax - amount_retencion
            amount_total_company_signed = inv.amount_total
            amount_untaxed_signed = inv.amount_untaxed
            if inv.currency_id and inv.currency_id != inv.company_id.currency_id:
                currency_id = inv.currency_id.with_context(date=inv.date_invoice)
                amount_total_company_signed = currency_id.compute(inv.amount_total, inv.company_id.currency_id)
                amount_untaxed_signed = inv.currency_id.compute(inv.amount_untaxed, inv.company_id.currency_id)
            sign = inv.type in ['in_refund', 'out_refund'] and -1 or 1
            inv.amount_total_company_signed = amount_total_company_signed * sign
            inv.amount_total_signed = inv.amount_total * sign
            inv.amount_untaxed_signed = amount_untaxed_signed * sign

    def _prepare_tax_line_vals(self, line, tax):
        vals = super(AccountInvoice, self)._prepare_tax_line_vals(line, tax)
        vals['amount_retencion'] = tax['retencion']
        vals['retencion_account_id'] = self.type in ('out_invoice', 'in_invoice') and (tax['refund_account_id'] or line.account_id.id) or (tax['account_id'] or line.account_id.id)
        return vals

    @api.model
    def tax_line_move_line_get(self):
        res = []
        # keep track of taxes already processed
        done_taxes = []
        # loop the invoice.tax.line in reversal sequence
        for tax_line in sorted(self.tax_line_ids, key=lambda x: -x.sequence):
            amount = tax_line.amount + tax_line.amount_retencion
            if amount:
                tax = tax_line.tax_id
                if tax.amount_type == "group":
                    for child_tax in tax.children_tax_ids:
                        done_taxes.append(child_tax.id)
                done_taxes.append(tax.id)
                if tax_line.amount  > 0:
                    res.append({
                        'invoice_tax_line_id': tax_line.id,
                        'tax_line_id': tax_line.tax_id.id,
                        'type': 'tax',
                        'name': tax_line.name,
                        'price_unit': tax_line.amount,
                        'quantity': 1,
                        'price': tax_line.amount,
                        'account_id': tax_line.account_id.id,
                        'account_analytic_id': tax_line.account_analytic_id.id,
                        'invoice_id': self.id,
                        'tax_ids': [(6, 0, done_taxes)] if tax_line.tax_id.include_base_amount else []
                    })
                if tax_line.amount_retencion > 0:
                    res.append({
                        'invoice_tax_line_id': tax_line.id,
                        'tax_line_id': tax_line.tax_id.id,
                        'type': 'tax',
                        'name': 'RET - ' + tax_line.name,
                        'price_unit': -tax_line.amount_retencion,
                        'quantity': 1,
                        'price': -tax_line.amount_retencion,
                        'account_id': tax_line.retencion_account_id.id,
                        'account_analytic_id': tax_line.account_analytic_id.id,
                        'invoice_id': self.id,
                        'tax_ids': [(6, 0, done_taxes)] if tax_line.tax_id.include_base_amount else []
                    })
        return res

    def porcentaje_dr(self):
        if not self.global_descuentos_recargos:
            return 1
        taxes = super(AccountInvoice,self).get_taxes_values()
        afecto = 0.00
        exento = 0.00
        porcentaje = 0.00
        total = 0.00
        for id, t in taxes.items():
            tax = self.env['account.tax'].browse(t['tax_id'])
            total += t['base']
            if tax.amount > 0:
                afecto += t['base']
            else:
                exento += t['base']
        agrupados = self.global_descuentos_recargos.get_agrupados()
        monto = agrupados['R'] - agrupados['D']
        if monto == 0:
            return 1
        porcentaje = (100.0 * monto) / afecto
        return  1 + (porcentaje /100.0)

    def _get_grouped_taxes(self, line, taxes,tax_grouped={}):
        for tax in taxes:
            val = self._prepare_tax_line_vals(line, tax)
            # If the taxes generate moves on the same financial account as the invoice line,
            # propagate the analytic account from the invoice line to the tax line.
            # This is necessary in situations were (part of) the taxes cannot be reclaimed,
            # to ensure the tax move is allocated to the proper analytic account.
            if not val.get('account_analytic_id') and line.account_analytic_id and val['account_id'] == line.account_id.id:
                val['account_analytic_id'] = line.account_analytic_id.id
            key = self.env['account.tax'].browse(tax['id']).get_grouping_key(val)
            if key not in tax_grouped:
                tax_grouped[key] = val
            else:
                tax_grouped[key]['amount'] += val['amount']
                tax_grouped[key]['amount_retencion'] += val['amount_retencion']
                tax_grouped[key]['base'] += val['base']
        return tax_grouped

    @api.multi
    def get_taxes_values(self):
        tax_grouped = {}
        totales = {}
        for line in self.invoice_line_ids:
            if line.invoice_line_tax_ids and line.invoice_line_tax_ids[0].price_include:# se asume todos losproductos vienen con precio incluido o no ( no hay mixes)
                for t in line.invoice_line_tax_ids:
                    if not t in totales:
                        totales[t] = 0
                    totales[t] += (self.currency_id.round(line.price_unit *line.quantity) * line.discount)
            taxes = line.invoice_line_tax_ids.compute_all(line.price_unit, self.currency_id, line.quantity, line.product_id, self.partner_id, discount=line.discount)['taxes']
            tax_grouped = self._get_grouped_taxes(line, taxes, tax_grouped)
        if totales:
            for line in self.invoice_line_ids:
                for t in line.invoice_line_tax_ids:
                    taxes = t.compute_all(totales[t], self.currency_id, 1)['taxes']
                    tax_grouped = self._get_grouped_taxes(line, taxes, tax_grouped)
        if not self.global_descuentos_recargos:
            return tax_grouped
        gdr = self.porcentaje_dr()
        taxes = {}
        for t, group in tax_grouped.items():
            if t not in taxes:
                taxes[t] = group
            tax = self.env['account.tax'].browse(group['tax_id'])
            if tax.amount > 0:
                taxes[t]['amount'] *= gdr
                taxes[t]['base'] *=  gdr
        return taxes

    @api.onchange('global_descuentos_recargos' )
    def _onchange_descuentos(self):
        self._onchange_invoice_line_ids()

    @api.model
    def _prepare_refund(self, invoice, date_invoice=None, date=None, description=None, journal_id=None, tipo_nota=61, mode='1'):
        values = super(AccountInvoice, self)._prepare_refund(invoice, date_invoice, date, description, journal_id)
        document_type = self.env['account.journal.sii_document_class'].search(
                [
                    ('sii_document_class_id.sii_code','=', tipo_nota),
                    ('journal_id','=', invoice.journal_id.id),
                ],
                limit=1,
            )
        if invoice.type == 'out_invoice':
            type = 'out_refund'
        elif invoice.type == 'out_refund':
            type = 'out_invoice'
        elif invoice.type == 'in_invoice':
            type = 'in_refund'
        elif invoice.type == 'in_refund':
            type = 'in_invoice'
        values.update({
                'type': type,
                'journal_document_class_id': document_type.id,
                'turn_issuer': invoice.turn_issuer.id,
                'referencias':[[0,0, {
                        'origen': int(invoice.sii_document_number or invoice.reference),
                        'sii_referencia_TpoDocRef': invoice.sii_document_class_id.id,
                        'sii_referencia_CodRef': mode,
                        'motivo': description,
                        'fecha_documento': invoice.date_invoice
                    }]],
            })
        return values

    @api.multi
    @api.returns('self')
    def refund(self, date_invoice=None, date=None, description=None, journal_id=None, tipo_nota=61, mode='1'):
        new_invoices = self.browse()
        for invoice in self:
            # create the new invoice
            values = self._prepare_refund(invoice, date_invoice=date_invoice, date=date,
                                    description=description, journal_id=journal_id,
                                    tipo_nota=tipo_nota, mode=mode)
            refund_invoice = self.create(values)
            invoice_type = {'out_invoice': ('customer invoices credit note'),
                            'out_refund': ('customer invoices debit note'),
                            'in_invoice': ('vendor bill credit note'),
                            'in_refund': ('vendor bill debit note')}
            message = _("This %s has been created from: <a href=# data-oe-model=account.invoice data-oe-id=%d>%s</a>") % (invoice_type[invoice.type], invoice.id, invoice.number)
            refund_invoice.message_post(body=message)
            new_invoices += refund_invoice
        return new_invoices

    def get_document_class_default(self, document_classes):
        document_class_id = None
        #if self.turn_issuer.vat_affected not in ['SI', 'ND']:
        #    exempt_ids = [
        #        self.env.ref('l10n_cl_fe.dc_y_f_dtn').id,
        #        self.env.ref('l10n_cl_fe.dc_y_f_dte').id]
        #    for document_class in document_classes:
        #        if document_class.sii_document_class_id.id in exempt_ids:
        #            document_class_id = document_class.id
        #            break
        #        else:
        #            document_class_id = document_classes.ids[0]
        #else:
        document_class_id = document_classes.ids[0]
        return document_class_id

    @api.onchange('journal_id', 'company_id')
    def _set_available_issuer_turns(self):
        for rec in self:
            if rec.company_id:
                available_turn_ids = rec.company_id.company_activities_ids
                for turn in available_turn_ids:
                    rec.turn_issuer= turn.id

    @api.multi
    def name_get(self):
        TYPES = {
            'out_invoice': _('Invoice'),
            'in_invoice': _('Supplier Invoice'),
            'out_refund': _('Refund'),
            'in_refund': _('Supplier Refund'),
        }
        result = []
        for inv in self:
            result.append(
                (inv.id, "%s %s" % (inv.document_number or TYPES[inv.type], inv.name or '')))
        return result

    @api.model
    def name_search(self, name, args=None, operator='ilike', limit=100):
        args = args or []
        recs = self.browse()
        if name:
            recs = self.search(
                [('document_number', '=', name)] + args, limit=limit)
        if not recs:
            recs = self.search([('name', operator, name)] + args, limit=limit)
        return recs.name_get()

    def _buscarTaxEquivalente(self,tax):
        tax_n = self.env['account.tax'].search(
            [
                ('sii_code', '=', tax.sii_code),
                ('sii_type', '=', tax.sii_type),
                ('retencion', '=', tax.retencion),
                ('type_tax_use', '=', tax.type_tax_use),
                ('no_rec', '=', tax.no_rec),
                ('company_id', '=', self.company_id.id),
                ('price_include', '=', tax.price_include),
                ('amount', '=', tax.amount),
                ('amount_type', '=', tax.amount_type),
            ]
        )
        return tax_n

    def _crearTaxEquivalente(self):
        tax_n = self.env['account.tax'].create({
            'sii_code': tax.sii_code,
            'sii_type': tax.sii_type,
            'retencion': tax.retencion,
            'type_tax_use':tax.type_tax_use,
            'no_rec': tax.no_rec,
            'name': tax.name,
            'description': tax.description,
            'tax_group_id': tax.tax_group_id.id,
            'company_id': self.company_id.id,
            'price_include':tax.price_include,
            'amount': tax.amount,
            'amount_type': tax.amount_type,
            'account_id':tax.account_id.id,
            'refund_account_id': tax.refund_account_id.id,
        })
        return tax

    @api.onchange('partner_id')
    def update_journal(self):
        self.journal_id = self._default_journal()
        self.set_default_journal()
        return self.update_domain_journal()

    @api.onchange('company_id')
    def _refreshRecords(self):
        self.journal_id = self._default_journal()
        journal = self.journal_id
        for line in self.invoice_line_ids:
            tax_ids = []
            if self._context.get('type') in ('out_invoice', 'in_refund'):
                line.account_id = journal.default_credit_account_id.id
            else:
                line.account_id = journal.default_debit_account_id.id
            if self._context.get('type') in ('out_invoice', 'out_refund'):
                for tax in line.product_id.taxes_id:
                    if tax.company_id.id == self.company_id.id:
                        tax_ids.append(tax.id)
                    else:
                        tax_n = self._buscarTaxEquivalente(tax)
                        if not tax_n:
                            tax_n = self._crearTaxEquivalente(tax)
                        tax_ids.append(tax_n.id)
                line.product_id.taxes_id = False
                line.product_id.taxes_id = tax_ids
            else:
                for tax in line.product_id.supplier_taxes_id:
                    if tax.company_id.id == self.company_id.id:
                        tax_ids.append(tax.id)
                    else:
                        tax_n = self._buscarTaxEquivalente(tax)
                        if not tax_n:
                            tax_n = self._crearTaxEquivalente(tax)
                        tax_ids.append(tax_n.id)
                line.invoice_line_tax_ids = False
                line.product_id.supplier_taxes_id.append = tax_ids
            line.invoice_line_tax_ids = False
            line.invoice_line_tax_ids = tax_ids

    def _get_available_journal_document_class(self):
        context = dict(self._context or {})
        journal_id = self.journal_id
        if not journal_id and 'default_journal_id' in context:
            journal_id = self.env['account.journal'].browse(context['default_journal_id'])
        if not journal_id:
            journal_id = self.env['account.journal'].search([('type','=','sale')],limit=1)
        invoice_type = self.type or context.get('default_type', False)
        if not invoice_type:
            invoice_type = 'in_invoice' if journal_id.type == 'purchase' else 'out_invoice'
        document_class_ids = []
        nd = False
        for ref in self.referencias:
            if not nd:
                nd = ref.sii_referencia_CodRef
        if invoice_type in ['out_invoice', 'in_invoice', 'out_refund', 'in_refund']:
            if journal_id:
                domain = [
                    ('journal_id', '=', journal_id.id),
                 ]
            else:
                operation_type = self.get_operation_type(invoice_type)
                domain = [
                    ('journal_id.type', '=', operation_type),
                 ]
            if invoice_type  in [ 'in_refund', 'out_refund']:
                domain += [('sii_document_class_id.document_type','in',['credit_note'] )]
            else:
                options = ['invoice', 'invoice_in']
                if nd:
                    options.append('debit_note')
                domain += [('sii_document_class_id.document_type','in', options )]
            document_classes = self.env[
                'account.journal.sii_document_class'].search(domain)
            document_class_ids = document_classes.ids
        return document_class_ids

    @api.onchange('journal_id', 'partner_id')
    def update_domain_journal(self):
        document_classes = self._get_available_journal_document_class()
        result = {'domain':{
            'journal_document_class_id' : [('id', 'in', document_classes)],
        }}
        return result

    @api.depends('journal_id')
    @api.onchange('journal_id', 'partner_id')
    def set_default_journal(self, default=None):
        if not self.journal_document_class_id or self.journal_document_class_id.journal_id != self.journal_id:
            query = []
            if not default and not self.journal_document_class_id:
                query.append(
                    ('sii_document_class_id','=', self.journal_document_class_id.sii_document_class_id.id),
                )
            if self.journal_document_class_id.journal_id != self.journal_id or not default:
                query.append(
                    ('journal_id', '=', self.journal_id.id)
                )
            if query:
                default = self.env['account.journal.sii_document_class'].search(
                    query,
                    order='sequence asc',
                    limit=1,
                ).id
            self.journal_document_class_id = self._default_journal_document_class_id(default)

    @api.onchange('sii_document_class_id', 'partner_id')
    def _check_vat(self):
        if self.partner_id and not self._es_boleta() and not self.partner_id.commercial_partner_id.document_number:
            raise UserError(_("""The customer/supplier does not have a VAT \
defined. The type of invoicing document you selected requires you tu settle \
a VAT."""))

    @api.depends(
        'sii_document_class_id',
        'sii_document_class_id.document_letter_id',
        'sii_document_class_id.document_letter_id.vat_discriminated',
        'company_id',
        'company_id.invoice_vat_discrimination_default',)
    def get_vat_discriminated(self):
        for inv in self:
            vat_discriminated = False
            # agregarle una condicion: si el giro es afecto a iva, debe seleccionar factura, de lo contrario boleta (to-do)
            if inv.sii_document_class_id.document_letter_id.vat_discriminated or inv.company_id.invoice_vat_discrimination_default == 'discriminate_default':
                vat_discriminated = True
            inv.vat_discriminated = vat_discriminated

    @api.depends('sii_document_number', 'number')
    def _get_document_number(self):
        for inv in self:
            if inv.sii_document_number and inv.sii_document_class_id:
                document_number = (
                    inv.sii_document_class_id.doc_code_prefix or '') + inv.sii_document_number
            else:
                document_number = inv.number
            inv.document_number = document_number

    @api.one
    @api.constrains('reference', 'partner_id', 'company_id', 'type','journal_document_class_id')
    def _check_reference_in_invoice(self):
        if self.type in ['in_invoice', 'in_refund'] and self.reference:
            domain = [('type', '=', self.type),
                      ('reference', '=', self.reference),
                      ('partner_id', '=', self.partner_id.id),
                      ('journal_document_class_id.sii_document_class_id', '=',
                       self.journal_document_class_id.sii_document_class_id.id),
                      ('company_id', '=', self.company_id.id),
                      ('id', '!=', self.id)]
            invoice_ids = self.search(domain)
            if invoice_ids:
                raise UserError(u'El numero de factura debe ser unico por Proveedor.\n'\
                                u'Ya existe otro documento con el numero: %s para el proveedor: %s' %
                                (self.reference, self.partner_id.display_name))

    @api.multi
    def action_move_create(self):
        for obj_inv in self:
            invtype = obj_inv.type
            if obj_inv.journal_document_class_id and not obj_inv.sii_document_number:
                if invtype in ('out_invoice', 'out_refund'):
                    if not obj_inv.journal_document_class_id.sequence_id:
                        raise UserError(_(
                            'Please define sequence on the journal related documents to this invoice.'))
                    sii_document_number = obj_inv.journal_document_class_id.sequence_id.next_by_id()
                    prefix = obj_inv.journal_document_class_id.sii_document_class_id.doc_code_prefix or ''
                    move_name = (prefix + str(sii_document_number)).replace(' ','')
                    obj_inv.write({'move_name': move_name})
                elif invtype in ('in_invoice', 'in_refund'):
                    sii_document_number = obj_inv.reference
        super(AccountInvoice, self).action_move_create()
        for obj_inv in self:
            invtype = obj_inv.type
            if obj_inv.journal_document_class_id and not obj_inv.sii_document_number:
                obj_inv.write({'sii_document_number': sii_document_number})
            document_class_id = obj_inv.sii_document_class_id.id
            guardar = {'document_class_id': document_class_id,
                'sii_document_number': obj_inv.sii_document_number,
                'no_rec_code':obj_inv.no_rec_code,
                'iva_uso_comun':obj_inv.iva_uso_comun,}
            obj_inv.move_id.write(guardar)
        return True

    def get_operation_type(self, invoice_type):
        if invoice_type in ['in_invoice', 'in_refund']:
            operation_type = 'purchase'
        elif invoice_type in ['out_invoice', 'out_refund']:
            operation_type = 'sale'
        else:
            operation_type = False
        return operation_type

    def get_valid_document_letters(
            self,
            partner_id,
            operation_type='sale',
            company=False,
            vat_affected='SI',
            invoice_type='out_invoice',
            nd=False,):

        document_letter_obj = self.env['sii.document_letter']
        user = self.env.user
        partner = self.partner_id

        if not partner_id or not company or not operation_type:
            return []

        partner = partner.commercial_partner_id
        if operation_type == 'sale':
            issuer_responsability_id = company.partner_id.responsability_id.id
            receptor_responsability_id = partner.responsability_id.id
            domain = [
                ('issuer_ids', '=', issuer_responsability_id),
                ('receptor_ids', '=', receptor_responsability_id),
                ]
            if invoice_type == 'out_invoice' and not nd:
                if vat_affected == 'SI':
                    domain.append(('name', '!=', 'C'))
                else:
                    domain.append(('name', '=', 'C'))
        elif operation_type == 'purchase':
            issuer_responsability_id = partner.responsability_id.id
            domain = [('issuer_ids', '=', issuer_responsability_id)]
        else:
            raise UserError(_('Operation Type Error'),
                             _('Operation Type Must be "Sale" or "Purchase"'))

        # TODO: fijar esto en el wizard, o llamar un wizard desde aca
        # if not company.partner_id.responsability_id.id:
        #     raise except_orm(_('You have not settled a tax payer type for your\
        #      company.'),
        #      _('Please, set your company tax payer type (in company or \
        #      partner before to continue.'))
        document_letter_ids = document_letter_obj.search(
             domain)
        return document_letter_ids

    @api.multi
    def _check_duplicate_supplier_reference(self):
        for invoice in self:
            if invoice.type in ('in_invoice', 'in_refund') and invoice.reference:
                if self.search(
                    [
                        ('reference','=', invoice.reference),
                        ('journal_document_class_id','=',invoice.journal_document_class_id.id),
                        ('partner_id','=', invoice.partner_id.id),
                        ('type', '=', invoice.type),
                        ('id', '!=', invoice.id),
                     ]):
                    raise UserError('El documento %s, Folio %s de la Empresa %s ya se en cuentra registrado' % ( invoice.journal_document_class_id.sii_document_class_id.name, invoice.reference, invoice.partner_id.name))

    @api.multi
    def invoice_validate(self):
        for inv in self:
            inv.sii_result = 'NoEnviado'
            inv.responsable_envio = self.env.user.id
            if inv.type in ['out_invoice', 'out_refund']:
                if inv.journal_id.restore_mode:
                    inv.sii_result = 'Proceso'
                else:
                    inv._timbrar()
                    if inv._es_boleta() and not inv._nc_boleta():
                        inv.sii_result = 'Proceso'
                        continue
                    tiempo_pasivo = (datetime.now() + timedelta(hours=int(self.env['ir.config_parameter'].sudo().get_param('account.auto_send_dte', default=12))))
                    self.env['sii.cola_envio'].create({
                                                'doc_ids':[inv.id],
                                                'model':'account.invoice',
                                                'user_id':self.env.user.id,
                                                'tipo_trabajo': 'pasivo',
                                                'date_time': tiempo_pasivo,
                                                'send_email': False if inv.company_id.dte_service_provider=='SIICERT' or self.env['ir.config_parameter'].sudo().get_param('account.auto_send_email', default=True) else True,
                                                })
            if inv.purchase_to_done:
                for ptd in inv.purchase_to_done:
                    ptd.write({'state': 'done'})
        return super(AccountInvoice, self).invoice_validate()

    @api.model
    def create(self, vals):
        inv = super(AccountInvoice, self).create(vals)
        inv.update_domain_journal()
        inv.set_default_journal()
        return inv

    @api.model
    def _default_journal(self):
        if self._context.get('default_journal_id', False):
            return self.env['account.journal'].browse(self._context.get('default_journal_id'))
        company_id = self._context.get('company_id', self.company_id or self.env.user.company_id)
        if self._context.get('honorarios', False):
            inv_type = self._context.get('type', 'out_invoice')
            inv_types = inv_type if isinstance(inv_type, list) else [inv_type]
            domain = [
                ('journal_document_class_ids.sii_document_class_id.document_letter_id.name','=','M'),
                ('type', 'in', [TYPE2JOURNAL[ty] for ty in inv_types if ty in TYPE2JOURNAL])
                ('company_id', '=', company_id.id),
            ]
            journal_id = self.env['account.journal'].search(domain, limit=1)
            return journal_id
        inv_type = self._context.get('type', 'out_invoice')
        inv_types = inv_type if isinstance(inv_type, list) else [inv_type]
        domain = [
            ('type', 'in', [TYPE2JOURNAL[ty] for ty in inv_types if ty in TYPE2JOURNAL]),
            ('company_id', '=', company_id.id),
        ]
        return self.env['account.journal'].search(domain, limit=1, order="sequence asc")

    def split_cert(self, cert):
        certf, j = '', 0
        for i in range(0, 29):
            certf += cert[76 * i:76 * (i + 1)] + '\n'
        return certf

    def create_template_envio(self, RutEmisor, RutReceptor, FchResol, NroResol,
                              TmstFirmaEnv, EnvioDTE,signature_d,SubTotDTE):
        xml = '''<SetDTE ID="SetDoc">
<Caratula version="1.0">
<RutEmisor>{0}</RutEmisor>
<RutEnvia>{1}</RutEnvia>
<RutReceptor>{2}</RutReceptor>
<FchResol>{3}</FchResol>
<NroResol>{4}</NroResol>
<TmstFirmaEnv>{5}</TmstFirmaEnv>
{6}</Caratula>{7}
</SetDTE>
'''.format(RutEmisor, signature_d['subject_serial_number'], RutReceptor,
           FchResol, NroResol, TmstFirmaEnv, SubTotDTE, EnvioDTE)
        return xml

    def time_stamp(self, formato='%Y-%m-%dT%H:%M:%S'):
        tz = pytz.timezone('America/Santiago')
        return datetime.now(tz).strftime(formato)

    def _get_xsd_types(self):
        return {
          'doc': 'DTE_v10.xsd',
          'env': 'EnvioDTE_v10.xsd',
          'env_boleta': 'EnvioBOLETA_v11.xsd',
          'recep' : 'Recibos_v10.xsd',
          'env_recep' : 'EnvioRecibos_v10.xsd',
          'env_resp': 'RespuestaEnvioDTE_v10.xsd',
          'sig': 'xmldsignature_v10.xsd'
        }

    def _get_xsd_file(self, validacion, path=False):
        validacion_type = self._get_xsd_types()
        return (path or xsdpath) + validacion_type[validacion]

    def xml_validator(self, some_xml_string, validacion='doc'):
        if validacion == 'bol':
            return True
        xsd_file = self._get_xsd_file(validacion)
        try:
            xmlschema_doc = etree.parse(xsd_file)
            xmlschema = etree.XMLSchema(xmlschema_doc)
            xml_doc = etree.fromstring(some_xml_string)
            result = xmlschema.validate(xml_doc)
            if not result:
                xmlschema.assert_(xml_doc)
            return result
        except AssertionError as e:
            _logger.warning(etree.tostring(xml_doc))
            raise UserError(_('XML Malformed Error:  %s') % e.args)

    def get_seed(self, company_id):
        try:
            import ssl
            ssl._create_default_https_context = ssl._create_unverified_context
        except:
            pass
        url = server_url[company_id.dte_service_provider] + 'CrSeed.jws?WSDL'
        _server = Client(url)
        resp = _server.service.getSeed().replace('<?xml version="1.0" encoding="UTF-8"?>','')
        root = etree.fromstring(resp)
        semilla = root[0][0].text
        return semilla

    def create_template_seed(self, seed):
        xml = u'''<getToken>
<item>
<Semilla>{}</Semilla>
</item>
</getToken>
'''.format(seed)
        return xml

    def create_template_doc(self, doc):
        xml = '''<DTE xmlns="http://www.sii.cl/SiiDte" version="1.0">
{}
</DTE>'''.format(doc)
        return xml

    def create_template_env(self, doc):
        xml = '''<?xml version="1.0" encoding="ISO-8859-1"?>
<EnvioDTE xmlns="http://www.sii.cl/SiiDte" \
xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" \
xsi:schemaLocation="http://www.sii.cl/SiiDte EnvioDTE_v10.xsd" \
version="1.0">
{}
</EnvioDTE>'''.format(doc)
        return xml

    def create_template_env_boleta(self, doc):
        xml = '''<?xml version="1.0" encoding="ISO-8859-1"?>
<EnvioBOLETA xmlns="http://www.sii.cl/SiiDte" \
xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" \
xsi:schemaLocation="http://www.sii.cl/SiiDte EnvioBOLETA_v11.xsd" \
version="1.0">
{}
</EnvioBOLETA>'''.format(doc)
        return xml

    def create_template_doc1(self, doc, sign):
        xml = doc.replace('</DTE>', sign.decode() + '</DTE>')
        return xml

    def create_template_env1(self, doc, sign):
        xml = doc.replace('</EnvioDTE>', sign.decode() + '</EnvioDTE>')
        return xml

    def append_sign_recep(self, doc, sign):
        xml = doc.replace('</Recibo>', sign.decode() + '</Recibo>')
        return xml

    def append_sign_env_recep(self, doc, sign):
        xml = doc.replace('</EnvioRecibos>', sign.decode() + '</EnvioRecibos>')
        return xml

    def append_sign_env_resp(self, doc, sign):
        xml = doc.replace('</RespuestaDTE>', sign.decode() + '</RespuestaDTE>')
        return xml

    def append_sign_env_bol(self, doc, sign):
        xml = doc.replace('</EnvioBOLETA>', sign.decode() + '</EnvioBOLETA>')
        return xml

    def sign_seed(self, message, privkey, cert):
        doc = etree.fromstring(message)
        signed_node = XMLSigner(method=methods.enveloped, digest_algorithm='sha1').sign(
            doc, key=privkey.encode('ascii'), cert=cert)
        msg = etree.tostring(
            signed_node, pretty_print=True).decode().replace('ds:', '')
        return msg

    def get_token(self, seed_file, company_id):
        url = server_url[company_id.dte_service_provider] + 'GetTokenFromSeed.jws?WSDL'
        _server = Client(url)
        tree = etree.fromstring(seed_file)
        ss = etree.tostring(tree, pretty_print=True, encoding='iso-8859-1').decode()
        resp = _server.service.getToken(ss).replace('<?xml version="1.0" encoding="UTF-8"?>','')
        respuesta = etree.fromstring(resp)
        token = respuesta[0][0].text
        return token

    def ensure_str(self,x, encoding="utf-8", none_ok=False):
        if none_ok is True and x is None:
            return x
        if not isinstance(x, str):
            x = x.decode(encoding)
        return x

    def long_to_bytes(self, n, blocksize=0):
        s = b''
        if USING_PYTHON2:
            n = long(n)  # noqa
        pack = struct.pack
        while n > 0:
            s = pack(b'>I', n & 0xffffffff) + s
            n = n >> 32
        # strip off leading zeros
        for i in range(len(s)):
            if s[i] != b'\000'[0]:
                break
        else:
            # only happens when n == 0
            s = b'\000'
            i = 0
        s = s[i:]
        # add back some pad bytes.  this could be done more efficiently w.r.t. the
        # de-padding being done above, but sigh...
        if blocksize > 0 and len(s) % blocksize:
            s = (blocksize - len(s) % blocksize) * b'\000' + s
        return s

    def _append_sig(self, type, msg, message):
        if type in ['doc', 'bol']:
            fulldoc = self.create_template_doc1(message, msg)
        if type=='env':
            fulldoc = self.create_template_env1(message,msg)
        if type=='recep':
            fulldoc = self.append_sign_recep(message,msg)
        if type=='env_recep':
            fulldoc = self.append_sign_env_recep(message,msg)
        if type=='env_resp':
            fulldoc = self.append_sign_env_resp(message,msg)
        if type=='env_boleta':
            fulldoc = self.append_sign_env_bol(message,msg)
        return fulldoc

    def sign_full_xml(self, message, privkey, cert, uri, type='doc'):
        doc = etree.fromstring(message)
        string = etree.tostring(doc[0])
        mess = etree.tostring(etree.fromstring(string), method="c14n")
        digest = base64.b64encode(self.digest(mess))
        reference_uri='#'+uri
        signed_info = Element("SignedInfo")
        c14n_method = SubElement(signed_info, "CanonicalizationMethod", Algorithm='http://www.w3.org/TR/2001/REC-xml-c14n-20010315')
        sign_method = SubElement(signed_info, "SignatureMethod", Algorithm='http://www.w3.org/2000/09/xmldsig#rsa-sha1')
        reference = SubElement(signed_info, "Reference", URI=reference_uri)
        transforms = SubElement(reference, "Transforms")
        SubElement(transforms, "Transform", Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315")
        digest_method = SubElement(reference, "DigestMethod", Algorithm="http://www.w3.org/2000/09/xmldsig#sha1")
        digest_value = SubElement(reference, "DigestValue")
        digest_value.text = digest
        signed_info_c14n = etree.tostring(signed_info,method="c14n",exclusive=False,with_comments=False,inclusive_ns_prefixes=None)
        if type in ['doc','recep']:
            att = 'xmlns="http://www.w3.org/2000/09/xmldsig#"'
        else:
            att = 'xmlns="http://www.w3.org/2000/09/xmldsig#" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
        #@TODO Find better way to add xmlns:xsi attrib
        signed_info_c14n = signed_info_c14n.decode().replace("<SignedInfo>", "<SignedInfo %s>" % att )
        sig_root = Element("Signature",attrib={'xmlns':'http://www.w3.org/2000/09/xmldsig#'})
        sig_root.append(etree.fromstring(signed_info_c14n))
        signature_value = SubElement(sig_root, "SignatureValue")
        key = crypto.load_privatekey(type_,privkey.encode('ascii'))
        signature = crypto.sign(key,signed_info_c14n,'sha1')
        signature_value.text =textwrap.fill(base64.b64encode(signature).decode(),64)
        key_info = SubElement(sig_root, "KeyInfo")
        key_value = SubElement(key_info, "KeyValue")
        rsa_key_value = SubElement(key_value, "RSAKeyValue")
        modulus = SubElement(rsa_key_value, "Modulus")
        key = load_pem_private_key(privkey.encode('ascii'), password=None, backend=default_backend())
        modulus.text =  textwrap.fill(base64.b64encode(self.long_to_bytes(key.public_key().public_numbers().n)).decode(),64)
        exponent = SubElement(rsa_key_value, "Exponent")
        exponent.text = self.ensure_str(base64.b64encode(self.long_to_bytes(key.public_key().public_numbers().e)))
        x509_data = SubElement(key_info, "X509Data")
        x509_certificate = SubElement(x509_data, "X509Certificate")
        x509_certificate.text = '\n'+textwrap.fill(cert,64)
        msg = etree.tostring(sig_root)
        msg = msg if self.xml_validator(msg, 'sig') else ''
        fulldoc = self._append_sig(type, msg, message)
        return fulldoc if self.xml_validator(fulldoc, type) else ''

    def get_digital_signature_pem(self, comp_id):
        obj = user = self[0].responsable_envio if self else False
        if not obj:
            obj = user = self.env.user
        if not obj.cert:
            obj = comp_id
            if not obj or not obj.cert:
                obj = self.env['res.users'].search([("authorized_users_ids","=", user.id)])
            if not obj.cert or not user.id in obj.authorized_users_ids.ids:
                return False
        signature_data = {
            'subject_name': obj.name,
            'subject_serial_number': obj.subject_serial_number,
            'priv_key': obj.priv_key,
            'cert': obj.cert,
            'rut_envia': obj.subject_serial_number
            }
        return signature_data

    def get_digital_signature(self, comp_id):
        obj = user = False
        if 'responsable_envio' in self and self._ids:
            obj = user = self[0].responsable_envio
        if not obj:
            obj = user = self.env.user
        if not obj.cert:
            obj = comp_id
            if not obj or not obj.cert:
                obj = self.env['res.users'].search([("authorized_users_ids","=", user.id)])
            if not obj.cert or not user.id in obj.authorized_users_ids.ids:
                return False
        signature_data = {
            'subject_name': obj.name,
            'subject_serial_number': obj.subject_serial_number,
            'priv_key': obj.priv_key,
            'cert': obj.cert}
        return signature_data

    def get_resolution_data(self, comp_id):
        resolution_data = {
            'dte_resolution_date': comp_id.dte_resolution_date,
            'dte_resolution_number': comp_id.dte_resolution_number}
        return resolution_data

    def init_params(self, signature_d, company_id, file_name, envio_dte):
        params = collections.OrderedDict()
        params['rutSender'] = signature_d['subject_serial_number'][:8]
        params['dvSender'] = signature_d['subject_serial_number'][-1]
        params['rutCompany'] = company_id.vat[2:-1]
        params['dvCompany'] = company_id.vat[-1]
        params['archivo'] = (file_name,envio_dte, "text/xml")
        return params

    def procesar_recepcion(self, retorno, respuesta_dict):
        if respuesta_dict['RECEPCIONDTE']['STATUS'] != '0':
            _logger.info(connection_status[respuesta_dict['RECEPCIONDTE']['STATUS']])
        else:
            retorno.update({'sii_result': 'Enviado','sii_send_ident':respuesta_dict['RECEPCIONDTE']['TRACKID']})
        return retorno

    @api.multi
    def send_xml_file(self, envio_dte=None, file_name="envio", company_id=False, sii_result='NoEnviado', doc_ids='', post='/cgi_dte/UPL/DTEUpload'):
        if not company_id.dte_service_provider:
            raise UserError(_("Not Service provider selected!"))
        try:
            signature_d = self.get_digital_signature_pem(
                company_id)
            seed = self.get_seed(company_id)
            template_string = self.create_template_seed(seed)
            seed_firmado = self.sign_seed(
                template_string, signature_d['priv_key'],
                signature_d['cert'])
            token = self.get_token(seed_firmado,company_id)
        except:
            _logger.warning('error')
            return

        url = 'https://palena.sii.cl'
        if company_id.dte_service_provider == 'SIICERT':
            url = 'https://maullin.sii.cl'
        headers = {
            'Accept': 'image/gif, image/x-xbitmap, image/jpeg, image/pjpeg, application/vnd.ms-powerpoint, application/ms-excel, application/msword, */*',
            'Accept-Language': 'es-cl',
            'Accept-Encoding': 'gzip, deflate',
            'User-Agent': 'Mozilla/4.0 (compatible; PROG 1.0; Windows NT 5.0; YComp 5.0.2.4)',
            'Referer': '{}'.format(company_id.website),
            'Connection': 'Keep-Alive',
            'Cache-Control': 'no-cache',
            'Cookie': 'TOKEN={}'.format(token),
        }
        params = self.init_params(
            signature_d,
            company_id,
            file_name,
            '<?xml version="1.0" encoding="ISO-8859-1"?>\n'+envio_dte,
        )
        multi  = urllib3.filepost.encode_multipart_formdata(params)
        headers.update({'Content-Length': '{}'.format(len(multi[0]))})
        response = pool.request_encode_body('POST', url+post, params, headers)
        retorno = {'sii_xml_response': response.data, 'sii_result': 'NoEnviado','sii_send_ident':''}
        if response.status != 200:
            return retorno
        respuesta_dict = xmltodict.parse(response.data)
        retorno = self.procesar_recepcion(retorno, respuesta_dict)
        return retorno

    def crear_intercambio(self):
        rut = self.format_vat(self.partner_id.commercial_partner_id.vat )
        xml, file_name, comp = self._crear_envio(RUTRecep=rut)
        self.sii_xml_exchange = xml

    ''' Código para realizar migración de la versión 9.0.5.2.0, a la 9.0.5.3.0, se eliminará en 9.0.6.0.0'''
    def _read_xml(self, mode="text"):
        if self.sii_xml_request:
            xml = self.sii_xml_request.decode('ISO-8859-1').replace('<?xml version="1.0" encoding="ISO-8859-1"?>','')
        if mode == "etree":
            return etree.fromstring(xml)
        if mode == "parse":
            return xmltodict.parse(xml)
        return xml

    def _create_attachment(self,):
        if not self.sii_xml_exchange:
            try:
                self.crear_intercambio()
            except:
                #Código compatibilidad
                if self.sii_xml_request and not self.sii_xml_dte:
                    xml = self._read_xml("etree")
                    envio = xml.find("{http://www.sii.cl/SiiDte}SetDTE")
                    if envio:
                        self.sii_xml_dte = etree.tostring(envio.findall("{http://www.sii.cl/SiiDte}DTE")[0])
                self.crear_intercambio()
        url_path = '/download/xml/invoice/%s' % (self.id)
        filename = ('%s.xml' % self.document_number).replace(' ','_')
        att = self.env['ir.attachment'].search([('name','=', filename), ('res_id','=', self.id), ('res_model','=','account.invoice')], limit=1)
        if att:
            return att
        data = base64.b64encode(self.sii_xml_exchange.encode('ISO-8859-1'))
        values = dict(
                        name=filename,
                        datas_fname=filename,
                        url=url_path,
                        res_model='account.invoice',
                        res_id=self.id,
                        type='binary',
                        datas=data,
                    )
        att = self.env['ir.attachment'].create(values)
        return att

    @api.multi
    def action_invoice_sent(self):
        """ Open a window to compose an email, with the edi invoice template
            message loaded by default
        """
        self.ensure_one()
        template = self.env.ref('account.email_template_edi_invoice', False)
        compose_form = self.env.ref('mail.email_compose_message_wizard_form', False)
        att = self._create_attachment()
        atts = []
        if template.attachment_ids:
            for a in template.attachment_ids:
                atts.append(a.id)
        atts.append((6, 0, [att.id]))
        template.attachment_ids = atts
        ctx = dict(
            default_model='account.invoice',
            default_res_id=self.id,
            default_use_template=bool(template),
            default_template_id=template.id,
            default_composition_mode='comment',
            mark_invoice_as_sent=True,
        )
        return {
            'name': _('Compose Email'),
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'mail.compose.message',
            'views': [(compose_form.id, 'form')],
            'view_id': compose_form.id,
            'target': 'new',
            'context': ctx,
        }

    @api.multi
    def get_xml_file(self):
        url_path = '/download/xml/invoice/%s' % (self.id)
        return {
            'type' : 'ir.actions.act_url',
            'url': url_path,
            'target': 'self',
        }

    @api.multi
    def get_xml_exchange_file(self):
        url_path = '/download/xml/invoice_exchange/%s' % (self.id)
        return {
            'type' : 'ir.actions.act_url',
            'url': url_path,
            'target': 'self',
        }

    def get_folio(self):
        # saca el folio directamente de la secuencia
        return int(self.sii_document_number)

    def format_vat(self, value, con_cero=False):
        ''' Se Elimina el 0 para prevenir problemas con el sii, ya que las muestras no las toma si va con
        el 0 , y tambien internamente se generan problemas, se mantiene el 0 delante, para cosultas, o sino retorna "error de datos"'''
        if not value or value=='' or value == 0:
            value ="CL666666666"
            #@TODO opción de crear código de cliente en vez de rut genérico
        rut = value[:10] + '-' + value[10:]
        if not con_cero:
            rut = rut.replace('CL0','')
        rut = rut.replace('CL','')
        return rut

    def pdf417bc(self, ted):
        bc = pdf417gen.encode(
            ted,
            security_level=5,
            columns=13,
        )
        image = pdf417gen.render_image(
            bc,
            padding=15,
            scale=1,
        )
        return image

    def digest(self, data):
        sha1 = hashlib.new('sha1', data)
        return sha1.digest()

    def signmessage(self, texto, key):
        key = crypto.load_privatekey(type_, key)
        signature = crypto.sign(key, texto, 'sha1')
        text = base64.b64encode(signature).decode()
        return textwrap.fill( text, 64)

    @api.multi
    def get_related_invoices_data(self):
        """
        List related invoice information to fill CbtesAsoc.
        """
        self.ensure_one()
        rel_invoices = self.search([
            ('number', '=', self.origin),
            ('state', 'not in',
                ['draft', 'proforma', 'proforma2', 'cancel'])])
        return rel_invoices

    def _acortar_str(self, texto, size=1):
        c = 0
        cadena = ""
        while c < size and c < len(texto):
            cadena += texto[c]
            c += 1
        return cadena

    @api.multi
    def do_dte_send_invoice(self, n_atencion=None):
        ids = []
        for inv in self.with_context(lang='es_CL'):
            if inv.sii_result in ['','NoEnviado','Rechazado'] and not inv._es_boleta() and not inv._nc_boleta():
                if inv.sii_result in ['Rechazado']:
                    inv._timbrar()
                inv.sii_result = 'EnCola'
                ids.append(inv.id)
        if not isinstance(n_atencion, string_types):
            n_atencion = ''
        if ids:
            self.env['sii.cola_envio'].create({
                                    'doc_ids': ids,
                                    'model':'account.invoice',
                                    'user_id':self.env.user.id,
                                    'tipo_trabajo': 'envio',
                                    'n_atencion': n_atencion,
                                    'send_email': False if self[0].company_id.dte_service_provider=='SIICERT' or self.env['ir.config_parameter'].sudo().get_param('account.auto_send_email', default=True) else True,
                                    })
    def _es_boleta(self):
        if self.sii_document_class_id.sii_code in [35, 38, 39, 41, 70, 71]:
            return True
        return False

    def _nc_boleta(self):
        if not self.referencias or self.type != "out_refund":
            return False
        for r in self.referencias:
            if r.sii_referencia_TpoDocRef.sii_code in [35, 38, 39, 41, 70, 71]:
                return True
        return False

    def _giros_emisor(self):
        giros_emisor = []
        for turn in self.journal_id.journal_activities_ids:
            giros_emisor.extend([{'Acteco': turn.code}])
        return giros_emisor

    def _id_doc(self, taxInclude=False, MntExe=0):
        IdDoc= collections.OrderedDict()
        IdDoc['TipoDTE'] = self.sii_document_class_id.sii_code
        IdDoc['Folio'] = self.get_folio()
        IdDoc['FchEmis'] = self.date_invoice
        if self._es_boleta():
            IdDoc['IndServicio'] = 3 #@TODO agregar las otras opciones a la fichade producto servicio
        if self.ticket:
            IdDoc['TpoImpresion'] = "T"
        #if self.tipo_servicio:
        #    Encabezado['IdDoc']['IndServicio'] = 1,2,3,4
        # todo: forma de pago y fecha de vencimiento - opcional
        if taxInclude and MntExe == 0 and not self._es_boleta():
            IdDoc['MntBruto'] = 1
        if not self._es_boleta():
            IdDoc['FmaPago'] = self.forma_pago or 1
        if not taxInclude and self._es_boleta():
            IdDoc['IndMntNeto'] = 2
        #if self._es_boleta():
            #Servicios periódicos
        #    IdDoc['PeriodoDesde'] =
        #    IdDoc['PeriodoHasta'] =
        if not self._es_boleta():
            IdDoc['FchVenc'] = self.date_due or datetime.strftime(datetime.now(), '%Y-%m-%d')
        return IdDoc

    def _emisor(self):
        Emisor= collections.OrderedDict()
        Emisor['RUTEmisor'] = self.format_vat(self.company_id.vat)
        if self._es_boleta():
            Emisor['RznSocEmisor'] = self._acortar_str(self.company_id.partner_id.name, 100)
            Emisor['GiroEmisor'] = self._acortar_str(self.company_id.activity_description.name, 80)
        else:
            Emisor['RznSoc'] = self._acortar_str(self.company_id.partner_id.name, 100)
            Emisor['GiroEmis'] = self._acortar_str(self.company_id.activity_description.name, 80)
            if self.company_id.phone:
                Emisor['Telefono'] = self._acortar_str(self.company_id.phone, 20)
            Emisor['CorreoEmisor'] = self.company_id.dte_email
            Emisor['item'] = self._giros_emisor()
        if self.journal_id.sucursal_id:
            Emisor['Sucursal'] = self._acortar_str(self.journal_id.sucursal_id.name, 20)
            Emisor['CdgSIISucur'] = self._acortar_str(self.journal_id.sucursal_id.sii_code, 9)
        Emisor['DirOrigen'] = self._acortar_str(self.company_id.street + ' ' +(self.company_id.street2 or ''), 70)
        Emisor['CmnaOrigen'] = self.company_id.city_id.name or ''
        Emisor['CiudadOrigen'] = self.company_id.city or ''
        return Emisor

    def _receptor(self):
        Receptor = collections.OrderedDict()
        if not self.commercial_partner_id.vat and not self._es_boleta():
            raise UserError("Debe Ingresar RUT Receptor")
        #if self._es_boleta():
        #    Receptor['CdgIntRecep']
        Receptor['RUTRecep'] = self.format_vat(self.commercial_partner_id.vat)
        Receptor['RznSocRecep'] = self._acortar_str(self.commercial_partner_id.name, 100)
        if not self._es_boleta():
            if not self.commercial_partner_id.activity_description:
                raise UserError(_('Seleccione giro del partner'))
            Receptor['GiroRecep'] = self._acortar_str(self.commercial_partner_id.activity_description.name, 40)
        if self.partner_id.phone or self.commercial_partner_id.phone:
            Receptor['Contacto'] = self._acortar_str(self.partner_id.phone or self.commercial_partner_id.phone or self.partner_id.email, 80)
        if (self.commercial_partner_id.email or self.commercial_partner_id.dte_email or self.partner_id.email or self.partner_id.dte_email) and not self._es_boleta():
            Receptor['CorreoRecep'] = self.commercial_partner_id.dte_email or self.partner_id.dte_email or self.commercial_partner_id.email or self.partner_id.email
        street_recep = (self.partner_id.street or self.commercial_partner_id.street or False)
        if not street_recep:
            raise UserError('Debe Ingresar dirección del cliente')
        street2_recep = (self.partner_id.street2 or self.commercial_partner_id.street2 or False)
        Receptor['DirRecep'] = self._acortar_str(street_recep + (' ' + street2_recep if street2_recep else ''), 70)
        Receptor['CmnaRecep'] = self.partner_id.city_id.name or self.commercial_partner_id.city_id.name
        if not Receptor['CmnaRecep']:
            raise UserError('Debe Ingresar Comuna del cliente')
        Receptor['CiudadRecep'] = self.partner_id.city or self.commercial_partner_id.city
        return Receptor

    def _totales_otra_moneda(self, currency_id, MntExe, MntNeto, IVA, TasaIVA, ImptoReten, MntTotal=0):
        Totales = collections.OrderedDict()
        Totales['TpoMoneda'] = self._acortar_str(currency_id.abreviatura, 15)
        Totales['TpoCambio'] = currency_id.rate
        if MntNeto:
            if currency_id:
                MntNeto = currency_id.compute(MntNeto, self.company_id.currency_id)
            Totales['MntNetoOtrMnda'] = MntNeto
        if MntExe:
            if currency_id:
                MntExe = currency_id.compute(MntExe, self.company_id.currency_id)
            Totales['MntExeOtrMnda'] = MntExe
        if TasaIVA:
            if currency_id:
                IVA = currency_id.compute(IVA, self.company_id.currency_id)
            Totales['IVAOtrMnda'] = IVA
        if ImptoReten:
                Totales['ImptRetOtrMnda'] = collections.OrderedDict()
                Totales['ImptRetOtrMnda']['TipoImpOtrMnda'] = ImptoReten['TpoImp']
                Totales['ImptRetOtrMnda']['TasaImpOtrMnda'] = ImptoReten['TasaImp']
                if currency_id:
                    ImptoReten['MontoImp'] = currency_id.compute(ImptoReten['MontoImp'], self.company_id.currency_id)
                Totales['ImptRetOtrMnda']['ValorImpOtrMnda'] = ImptoReten['MontoImp']
        if currency_id:
            MntTotal = currency_id.compute(MntTotal, self.company_id.currency_id)
        Totales['MntTotOtrMnda'] = MntTotal
        #Totales['MontoNF']
        #Totales['TotalPeriodo']
        #Totales['SaldoAnterior']
        #Totales['VlrPagar']
        return Totales

    def _totales_normal(self, currency_id, MntExe, MntNeto, IVA, TasaIVA, ImptoReten, MntTotal=0):
        Totales = collections.OrderedDict()
        if MntNeto:
            Totales['MntNeto'] = MntNeto
        if MntExe:
            Totales['MntExe'] = MntExe
        if TasaIVA:
            Totales['TasaIVA'] = TasaIVA
            Totales['IVA'] = IVA
        if ImptoReten:
            Totales['ImptoReten'] = ImptoReten
        Totales['MntTotal'] = MntTotal
        #Totales['MontoNF']
        #Totales['TotalPeriodo']
        #Totales['SaldoAnterior']
        #Totales['VlrPagar']
        return Totales

    def _totales(self, MntExe=0, no_product=False, taxInclude=False):
        MntNeto = False
        IVA = False
        ImptoReten = False
        TasaIVA = False
        MntIVA = 0
        if self.sii_document_class_id.sii_code == 34 or (self.referencias and self.referencias[0].sii_referencia_TpoDocRef.sii_code == '34'):
            MntExe = self.currency_id.round(self.amount_total)
            if  no_product:
                MntExe = 0
        elif self.amount_untaxed and self.amount_untaxed != 0:
            if not self._es_boleta() or not taxInclude:
                IVA = False
                for t in self.tax_line_ids:
                    if t.tax_id.sii_code in [14, 15]:
                        IVA = t
                if IVA and IVA.base > 0 :
                    MntNeto = self.currency_id.round(IVA.base)
        if MntExe > 0:
            MntExe = self.currency_id.round( MntExe)
        if not self._es_boleta() or not taxInclude:
            if IVA:
                if not self._es_boleta():
                    TasaIVA = round(IVA.tax_id.amount, 2)
                MntIVA = self.currency_id.round(IVA.amount)
            if no_product:
                MntNeto = 0
                if not self._es_boleta():
                    TasaIVA = 0
                MntIVA = 0
        if IVA and IVA.tax_id.sii_code in [15]:
            ImptoReten = collections.OrderedDict()
            ImptoReten['TpoImp'] = IVA.tax_id.sii_code
            ImptoReten['TasaImp'] = round(IVA.tax_id.amount,2)
            ImptoReten['MontoImp'] = self.currency_id.round(IVA.amount)

        MntTotal = self.currency_id.round(self.amount_total)
        if no_product:
            MntTotal = 0
        return MntExe, MntNeto, MntIVA, TasaIVA, ImptoReten, MntTotal

    def _encabezado(self, MntExe=0, no_product=False, taxInclude=False):
        Encabezado = collections.OrderedDict()
        Encabezado['IdDoc'] = self._id_doc(taxInclude, MntExe)
        Encabezado['Emisor'] = self._emisor()
        Encabezado['Receptor'] = self._receptor()
        currency_id = False
        if self.currency_id and self.company_id and self.currency_id != self.company_id.currency_id:
            currency_id = self.currency_id.with_context(date=self.date_invoice)
        MntExe, MntNeto, IVA, TasaIVA, ImptoReten, MntTotal = self._totales(MntExe, no_product, taxInclude)
        Encabezado['Totales'] = self._totales_normal( currency_id, MntExe, MntNeto, IVA, TasaIVA, ImptoReten, MntTotal)
        if currency_id:
            Encabezado['OtraMoneda'] = self._totales_otra_moneda( currency_id, MntExe, MntNeto, IVA, TasaIVA, ImptoReten, MntTotal)
        return Encabezado

    @api.multi
    def get_barcode(self, no_product=False):
        ted = False
        folio = self.get_folio()
        result['TED']['DD']['RE'] = self.format_vat(self.company_id.vat)
        result['TED']['DD']['TD'] = self.sii_document_class_id.sii_code
        result['TED']['DD']['F']  = folio
        result['TED']['DD']['FE'] = self.date_invoice
        if not self.commercial_partner_id.vat:
            raise UserError(_("Fill Partner VAT"))
        result['TED']['DD']['RR'] = self.format_vat(self.commercial_partner_id.vat)
        result['TED']['DD']['RSR'] = self._acortar_str(self.commercial_partner_id.name,40)
        result['TED']['DD']['MNT'] = self.currency_id.round(self.amount_total)
        if no_product:
            result['TED']['DD']['MNT'] = 0
        for line in self.invoice_line_ids:
            result['TED']['DD']['IT1'] = self._acortar_str(line.product_id.name,40)
            if line.product_id.default_code:
                result['TED']['DD']['IT1'] = self._acortar_str(line.product_id.name.replace('['+line.product_id.default_code+'] ',''),40)
            break

        resultcaf = self.journal_document_class_id.sequence_id.get_caf_file(self.get_folio() )
        result['TED']['DD']['CAF'] = resultcaf['AUTORIZACION']['CAF']
        dte = result['TED']['DD']
        timestamp = self.time_stamp()
        if date( int(timestamp[:4]), int(timestamp[5:7]), int(timestamp[8:10])) < date(int(self.date[:4]), int(self.date[5:7]), int(self.date[8:10])):
            raise UserError("La fecha de timbraje no puede ser menor a la fecha de emisión del documento")
        dte['TSTED'] = timestamp
        dicttoxml.set_debug(False)
        ddxml = '<DD>'+dicttoxml.dicttoxml(
            dte, root=False, attr_type=False).decode().replace(
            '<key name="@version">1.0</key>','',1).replace(
            '><key name="@version">1.0</key>',' version="1.0">',1).replace(
            '><key name="@algoritmo">SHA1withRSA</key>',
            ' algoritmo="SHA1withRSA">').replace(
            '<key name="#text">','').replace(
            '</key>','').replace('<CAF>','<CAF version="1.0">')+'</DD>'
        keypriv = resultcaf['AUTORIZACION']['RSASK'].replace('\t','')
        root = etree.XML( ddxml )
        ddxml = etree.tostring(root)
        frmt = self.signmessage(ddxml, keypriv)
        ted = (
            '''<TED version="1.0">{}<FRMT algoritmo="SHA1withRSA">{}\
</FRMT></TED>''').format(ddxml.decode(), frmt)
        self.sii_barcode = ted
        image = False
        if ted:
            barcodefile = BytesIO()
            image = self.pdf417bc(ted)
            image.save(barcodefile,'PNG')
            data = barcodefile.getvalue()
            self.sii_barcode_img = base64.b64encode(data)
        ted  += '<TmstFirma>{}</TmstFirma>'.format(timestamp)
        return ted

    def _invoice_lines(self):
        line_number = 1
        invoice_lines = []
        no_product = False
        MntExe = 0
        currency_id = False
        if self.currency_id and self.company_id and self.currency_id != self.company_id.currency_id:
            currency_id = self.currency_id.with_context(date=self.date_invoice)
        for line in self.invoice_line_ids:
            if line.product_id.default_code == 'NO_PRODUCT':
                no_product = True
            lines = collections.OrderedDict()
            lines['NroLinDet'] = line_number
            if line.product_id.default_code and not no_product:
                lines['CdgItem'] = collections.OrderedDict()
                lines['CdgItem']['TpoCodigo'] = 'INT1'
                lines['CdgItem']['VlrCodigo'] = line.product_id.default_code
            taxInclude = False
            for t in line.invoice_line_tax_ids:
                taxInclude = t.price_include
                if t.amount == 0 or t.sii_code in [0]:#@TODO mejor manera de identificar exento de afecto
                    lines['IndExe'] = 1
                    price_exe = line.price_tax_included
                    MntExe += self.currency_id.round(price_exe)
            #if line.product_id.type == 'events':
            #   lines['ItemEspectaculo'] =
#            if self._es_boleta():
#                lines['RUTMandante']
            lines['NmbItem'] = self._acortar_str(line.product_id.name,80) #
            lines['DscItem'] = self._acortar_str(line.name, 1000) #descripción más extenza
            if line.product_id.default_code:
                lines['NmbItem'] = self._acortar_str(line.product_id.name.replace('['+line.product_id.default_code+'] ',''),80)
            #lines['InfoTicket']
            qty = round(line.quantity, 4)
            if not no_product:
                lines['QtyItem'] = qty
            if qty == 0 and not no_product:
                lines['QtyItem'] = 1
            elif qty < 0:
                raise UserError("NO puede ser menor que 0")
            if not no_product:
                lines['UnmdItem'] = line.uom_id.name[:4]
                lines['PrcItem'] = round(line.price_unit, 6)
                if currency_id:
                    lines['OtrMnda'] = collections.OrderedDict()
                    lines['OtrMnda']['PrcOtrMon'] = round(currency_id.compute( line.price_unit, self.company_id.currency_id, round=False), 6)
                    lines['OtrMnda']['Moneda'] = self._acortar_str(self.company_id.currency_id.name, 3)
                    lines['OtrMnda']['FctConv'] = round(currency_id.rate, 4)
            if line.discount > 0:
                if currency_id:
                    lines['OtrMnda']['DctoOtrMnda'] = line.discount
                lines['DescuentoPct'] = line.discount
                DescMonto = (((line.discount / 100) * lines['PrcItem'])* qty)
                lines['DescuentoMonto'] = self.currency_id.round( DescMonto )
                if currency_id:
                   lines['OtrMnda']['DctoOtrMnda'] = currency_id.compute(DescMonto, self.company_id.currency_id)
            if not no_product and not taxInclude:
                if currency_id:
                    lines['OtrMnda']['MontoItemOtrMnda'] = currency_id.compute( line.price_subtotal, self.company_id.currency_id)
                lines['MontoItem'] = self.currency_id.round(line.price_subtotal)
            elif not no_product :
                if currency_id:
                    lines['OtrMnda']['MontoItemOtrMnda'] = currency_id.compute( line.price_tax_included, self.company_id.currency_id)
                lines['MontoItem'] = self.currency_id.round(line.price_tax_included)
            if no_product:
                lines['MontoItem'] = 0
            line_number += 1
            invoice_lines.extend([{'Detalle': lines}])
            if 'IndExe' in lines:
                taxInclude = False
        return {
                'invoice_lines': invoice_lines,
                'MntExe':MntExe,
                'no_product':no_product,
                'tax_include': taxInclude,
                }

    def _gdr(self):
        result = []
        lin_dr = 1
        for dr in self.global_descuentos_recargos:
            dr_line = collections.OrderedDict()
            dr_line['NroLinDR'] = lin_dr
            dr_line['TpoMov'] = dr.type
            if dr.gdr_dtail:
                dr_line['GlosaDR'] = dr.gdr_dtail
            disc_type = "%"
            if dr.gdr_type == "amount":
                disc_type = "$"
            dr_line['TpoValor'] = disc_type
            dr_line['ValorDR'] = self.currency_id.round(dr.valor)
            if self.currency_id and self.company_id and self.currency_id != self.company_id.currency_id:
                currency_id = self.currency_id.with_context(date=self.date_invoice)
                dr_line['ValorDROtrMnda'] = currency_id.compute(dr.valor, self.company_id.currency_id)
            if self.sii_document_class_id.sii_code in [34] and (self.referencias and self.referencias[0].sii_referencia_TpoDocRef.sii_code == '34'):#solamente si es exento
                dr_line['IndExeDR'] = 1
            dr_lines = [{'DscRcgGlobal':dr_line}]
            result.append( dr_lines )
            lin_dr += 1
        return result

    def _dte(self, n_atencion=None):
        dte = collections.OrderedDict()
        invoice_lines = self._invoice_lines()
        dte['Encabezado'] = self._encabezado(invoice_lines['MntExe'], invoice_lines['no_product'], invoice_lines['tax_include'])
        lin_ref = 1
        ref_lines = []
        if self.company_id.dte_service_provider == 'SIICERT' and isinstance(n_atencion, string_types) and n_atencion != '' and not self._es_boleta():
            ref_line = {}
            ref_line = collections.OrderedDict()
            ref_line['NroLinRef'] = lin_ref
            ref_line['TpoDocRef'] = "SET"
            ref_line['FolioRef'] = self.get_folio()
            ref_line['FchRef'] = datetime.strftime(datetime.now(), '%Y-%m-%d')
            ref_line['RazonRef'] = "CASO "+n_atencion+"-" + str(self.sii_batch_number)
            lin_ref = 2
            ref_lines.extend([{'Referencia':ref_line}])
        if self.referencias :
            for ref in self.referencias:
                ref_line = {}
                ref_line = collections.OrderedDict()
                ref_line['NroLinRef'] = lin_ref
                if not self._es_boleta():
                    if  ref.sii_referencia_TpoDocRef:
                        ref_line['TpoDocRef'] = self._acortar_str(ref.sii_referencia_TpoDocRef.doc_code_prefix, 3) if ref.sii_referencia_TpoDocRef.use_prefix else ref.sii_referencia_TpoDocRef.sii_code
                        ref_line['FolioRef'] = ref.origen
                    ref_line['FchRef'] = ref.fecha_documento or datetime.strftime(datetime.now(), '%Y-%m-%d')
                if ref.sii_referencia_CodRef not in ['','none', False]:
                    ref_line['CodRef'] = ref.sii_referencia_CodRef
                ref_line['RazonRef'] = ref.motivo
                if self._es_boleta():
                    ref_line['CodVndor'] = self.seler_id.id
                    ref_lines['CodCaja'] = self.journal_id.point_of_sale_id.name
                ref_lines.extend([{'Referencia':ref_line}])
                lin_ref += 1
        dte['item'] = invoice_lines['invoice_lines']
        if self.global_descuentos_recargos:
            dte['drlines'] = self._gdr()
        dte['reflines'] = ref_lines
        dte['TEDd'] = self.get_barcode(invoice_lines['no_product'])
        return dte

    def _dte_to_xml(self, dte, tpo_dte="Documento"):
        ted = dte[tpo_dte + ' ID']['TEDd']
        dte[(tpo_dte + ' ID')]['TEDd'] = ''
        xml = dicttoxml.dicttoxml(
            dte, root=False, attr_type=False).decode() \
            .replace('<item >','').replace('<item>','').replace('</item>','')\
            .replace('<reflines>','').replace('</reflines>','')\
            .replace('<TEDd>','').replace('</TEDd>','')\
            .replace('</'+ tpo_dte + '_ID>','\n'+ted+'\n</'+ tpo_dte + '_ID>')\
            .replace('<drlines>','').replace('</drlines>','')
        return xml

    def _tpo_dte(self):
        tpo_dte = "Documento"
        if self.sii_document_class_id.sii_code == 43:
            tpo_dte = 'Liquidacion'
        return tpo_dte

    def _timbrar(self, n_atencion=None):
        try:
            signature_d = self.get_digital_signature(self.company_id)
        except:
            raise UserError(_('''There is no Signer Person with an \
        authorized signature for you in the system. Please make sure that \
        'user_signature_key' module has been installed and enable a digital \
        signature, for you or make the signer to authorize you to use his \
        signature.'''))
        certp = signature_d['cert'].replace(
            BC, '').replace(EC, '').replace('\n', '')
        folio = self.get_folio()
        tpo_dte = self._tpo_dte()
        doc_id_number = "F{}T{}".format(folio, self.sii_document_class_id.sii_code)
        doc_id = '<' + tpo_dte + ' ID="{}">'.format(doc_id_number)
        dte = collections.OrderedDict()
        dte[(tpo_dte + ' ID')] = self._dte(n_atencion)
        xml = self._dte_to_xml(dte, tpo_dte)
        root = etree.XML( xml )
        xml_pret = etree.tostring(
                root,
                pretty_print=True
            ).decode().replace(
                    '<' + tpo_dte + '_ID>',
                    doc_id
                ).replace('</' + tpo_dte + '_ID>', '</' + tpo_dte + '>')
        envelope_efact = self.create_template_doc(xml_pret)
        type = 'doc'
        if self._es_boleta():
            type = 'bol'
        einvoice = self.sign_full_xml(
                envelope_efact,
                signature_d['priv_key'],
                self.split_cert(certp),
                doc_id_number,
                type,
            )
        self.sii_xml_dte = einvoice


    def _crear_envio(self, n_atencion=None, RUTRecep="60803000-K"):
        dicttoxml.set_debug(False)
        DTEs = {}
        clases = {}
        company_id = False
        es_boleta = False
        batch = 0
        for inv in self.with_context(lang='es_CL'):
            if not inv.sii_batch_number or inv.sii_batch_number == 0:
                batch += 1
                inv.sii_batch_number = batch #si viene una guía/nota regferenciando una factura, que por numeración viene a continuación de la guia/nota, será recahazada laguía porque debe estar declarada la factura primero
            es_boleta = inv._es_boleta()
            try:
                signature_d = self.get_digital_signature(inv.company_id)
            except:
                raise UserError(_('''There is no Signer Person with an \
            authorized signature for you in the system. Please make sure that \
            'user_signature_key' module has been installed and enable a digital \
            signature, for you or make the signer to authorize you to use his \
            signature.'''))
            certp = signature_d['cert'].replace(
                BC, '').replace(EC, '').replace('\n', '')
            if inv.company_id.dte_service_provider == 'SIICERT': #Retimbrar con número de atención y envío
                inv._timbrar(n_atencion)
            #@TODO Mejarorar esto en lo posible
            if not inv.sii_document_class_id.sii_code in clases:
                clases[inv.sii_document_class_id.sii_code] = []
            clases[inv.sii_document_class_id.sii_code].extend([{
                                                'id':inv.id,
                                                'envio': inv.sii_xml_dte,
                                                'sii_batch_number': inv.sii_batch_number,
                                                'sii_document_number':inv.sii_document_number
                                            }])
            DTEs.update(clases)
            if not company_id:
                company_id = inv.company_id
            elif company_id.id != inv.company_id.id:
                raise UserError("Está combinando compañías, no está permitido hacer eso en un envío")
            company_id = inv.company_id
            #@TODO hacer autoreconciliación

        file_name = ""
        dtes={}
        SubTotDTE = ''
        resol_data = self.get_resolution_data(company_id)
        signature_d = self.get_digital_signature(company_id)
        RUTEmisor = self.format_vat(company_id.vat)
        for id_class_doc, classes in clases.items():
            NroDte = 0
            for documento in classes:
                if documento['sii_batch_number'] in dtes.keys():
                    raise UserError("No se puede repetir el mismo número de orden")
                dtes.update({str(documento['sii_batch_number']): documento['envio']})
                NroDte += 1
                file_name += 'F' + str(int(documento['sii_document_number'])) + 'T' + str(id_class_doc)
            SubTotDTE += '<SubTotDTE>\n<TpoDTE>' + str(id_class_doc) + '</TpoDTE>\n<NroDTE>'+str(NroDte)+'</NroDTE>\n</SubTotDTE>\n'
        file_name += ".xml"
        documentos =""
        for key in sorted(dtes.keys(), key=lambda r: int(r[0])):
            documentos += '\n'+dtes[key]
        # firma del sobre
        dtes = self.create_template_envio(
                RUTEmisor,
                RUTRecep,
                resol_data['dte_resolution_date'],
                resol_data['dte_resolution_number'],
                self.time_stamp(),
                documentos,
                signature_d,
                SubTotDTE,
            )
        env = 'env'
        if es_boleta:
            envio_dte  = self.create_template_env_boleta(dtes)
            env = 'env_boleta'
        else:
            envio_dte  = self.create_template_env(dtes)
        envio_dte = self.sign_full_xml(
                envio_dte.replace('<?xml version="1.0" encoding="ISO-8859-1"?>\n', ''),
                signature_d['priv_key'],
                certp,
                'SetDoc',
                env,
            )
        return envio_dte, file_name, company_id

    @api.multi
    def do_dte_send(self, n_atencion=None):
        envio_dte, file_name, company_id = self._crear_envio(n_atencion, RUTRecep="60803000-K")
        result = self.send_xml_file(envio_dte, file_name, company_id)
        for inv in self:
            inv.write({'sii_xml_response':result['sii_xml_response'],
                'sii_send_ident':result['sii_send_ident'],
                'sii_result': result['sii_result'],
                'sii_xml_request':envio_dte,
                'sii_send_file_name' : file_name,
                })

    def _get_send_status(self, track_id, signature_d,token):
        url = server_url[self.company_id.dte_service_provider] + 'QueryEstUp.jws?WSDL'
        _server = Client(url)
        rut = self.format_vat(self.company_id.vat, con_cero=True)
        respuesta = _server.service.getEstUp(
            rut[:8],
            str(rut[-1]),
            track_id,
            token)
        self.sii_receipt = respuesta
        resp = xmltodict.parse(respuesta)
        status = False
        if resp['SII:RESPUESTA']['SII:RESP_HDR']['ESTADO'] == "-11":
            if resp['SII:RESPUESTA']['SII:RESP_HDR']['ERR_CODE'] == "2":
                status =  {'warning':{'title':_('Estado -11'), 'message': _("Estado -11: Espere a que sea aceptado por el SII, intente en 5s más")}}
            else:
                status =  {'warning':{'title':_('Estado -11'), 'message': _("Estado -11: error 1Algo a salido mal, revisar carátula")}}
        if resp['SII:RESPUESTA']['SII:RESP_HDR']['ESTADO'] == "EPR":
            self.sii_result = "Proceso"
            if resp['SII:RESPUESTA']['SII:RESP_BODY']['RECHAZADOS'] == "1":
                self.sii_result = "Rechazado"
        elif resp['SII:RESPUESTA']['SII:RESP_HDR']['ESTADO'] in ["RCT", 'RFR']:
            self.sii_result = "Rechazado"
            _logger.warning(resp)
            status = {'warning':{'title':_('Error RCT'), 'message': _(resp['SII:RESPUESTA']['SII:RESP_HDR']['GLOSA'])}}
        return status

    def _get_dte_status(self, signature_d, token):
        url = server_url[self.company_id.dte_service_provider] + 'QueryEstDte.jws?WSDL'
        _server = Client(url)
        receptor = self.format_vat(self.commercial_partner_id.vat)
        date_invoice = datetime.strptime(self.date_invoice, "%Y-%m-%d").strftime("%d-%m-%Y")
        rut = signature_d['subject_serial_number']
        respuesta = _server.service.getEstDte(
            rut[:8],
            str(rut[-1]),
            self.company_id.vat[2:-1],
            self.company_id.vat[-1],
            receptor[:8],
            receptor[-1],
            str(self.sii_document_class_id.sii_code),
            str(self.sii_document_number),
            date_invoice,
            str(int(self.amount_total)),
            token,
        )
        self.sii_message = respuesta
        resp = xmltodict.parse(respuesta)
        if resp['SII:RESPUESTA']['SII:RESP_HDR']['ESTADO'] == '2':
            status = {'warning':{'title':_("Error code: 2"), 'message': _(resp['SII:RESPUESTA']['SII:RESP_HDR']['GLOSA'])}}
            return status
        if resp['SII:RESPUESTA']['SII:RESP_HDR']['ESTADO'] == "EPR":
            self.sii_result = "Proceso"
            if resp['SII:RESPUESTA']['SII:RESP_BODY']['RECHAZADOS'] == "1":
                self.sii_result = "Rechazado"
            if resp['SII:RESPUESTA']['SII:RESP_BODY']['REPARO'] == "1":
                self.sii_result = "Reparo"
        elif resp['SII:RESPUESTA']['SII:RESP_HDR']['ESTADO'] == "FAU":
            self.sii_result = "Rechazado"

    @api.multi
    def ask_for_dte_status(self):
        try:
            signature_d = self.get_digital_signature_pem(
                self.company_id)
            seed = self.get_seed(self.company_id)
            template_string = self.create_template_seed(seed)
            seed_firmado = self.sign_seed(
                template_string,
                signature_d['priv_key'],
                signature_d['cert'])
            token = self.get_token(seed_firmado,self.company_id)
        except AssertionError as e:
            raise UserError(str(e))
        if not self.sii_send_ident:
            raise UserError('No se ha enviado aún el documento, aún está en cola de envío interna en odoo')
        if self.sii_result == 'Enviado':
            status = self._get_send_status(self.sii_send_ident, signature_d, token)
            if self.sii_result != 'Proceso':
                return status
        return self._get_dte_status(signature_d, token)

    def set_dte_claim(self, rut_emisor=False, company_id=False, sii_document_number=False, sii_document_class_id=False, claim=False):
        rut_emisor = rut_emisor or self.format_vat(self.company_id.partner_id.vat)
        company_id = company_id or self.company_id
        sii_document_number =  sii_document_number or self.sii_document_number or self.reference
        sii_document_class_id = sii_document_class_id or self.sii_document_class_id
        claim = claim or self.claim
        try:
            signature_d = self.get_digital_signature_pem(
                company_id,
            )
            seed = self.get_seed( company_id )
            template_string = self.create_template_seed( seed )
            seed_firmado = self.sign_seed(
                template_string,
                signature_d['priv_key'],
                signature_d['cert'],
            )
            token = self.get_token(
                seed_firmado,
                company_id,
            )
        except AssertionError as e:
            raise UserError(str(e))
        url = claim_url[company_id.dte_service_provider] + '?wsdl'
        _server = Client(
            url,
            headers= {
                'Cookie': 'TOKEN=' + token,
                },
        )
        respuesta = _server.service.ingresarAceptacionReclamoDoc(
            rut_emisor[:-2],
            rut_emisor[-1],
            str(sii_document_class_id.sii_code),
            str(sii_document_number),
            claim,
        )
        if self.id:
            self.claim_description = respuesta

    @api.multi
    def get_dte_claim(self, ):
        try:
            signature_d = self.get_digital_signature_pem(
                self.company_id)
            seed = self.get_seed(self.company_id)
            template_string = self.create_template_seed(seed)
            seed_firmado = self.sign_seed(
                template_string,
                signature_d['priv_key'],
                signature_d['cert'])
            token = self.get_token(seed_firmado,self.company_id)
        except AssertionError as e:
            raise UserError(str(e))
        url = claim_url[self.company_id.dte_service_provider] + '?wsdl'
        _server = Client(
            url,
            headers= {
                'Cookie': 'TOKEN=' + token,
                },
        )
        respuesta = _server.service.listarEventosHistDoc(
            self.company_id.vat[2:-1],
            self.company_id.vat[-1],
            str(self.sii_document_class_id.sii_code),
            str(self.sii_document_number),
        )
        self.claim_description = respuesta
        #resp = xmltodict.parse(respuesta)
        #if resp['SII:RESPUESTA']['SII:RESP_HDR']['ESTADO'] == '2':
        #    status = {'warning':{'title':_("Error code: 2"), 'message': _(resp['SII:RESPUESTA']['SII:RESP_HDR']['GLOSA'])}}
        #    return status
        #if resp['SII:RESPUESTA']['SII:RESP_HDR']['ESTADO'] == "EPR":
        #    self.sii_result = "Proceso"
        #    if resp['SII:RESPUESTA']['SII:RESP_BODY']['RECHAZADOS'] == "1":
        #        self.sii_result = "Rechazado"
        #    if resp['SII:RESPUESTA']['SII:RESP_BODY']['REPARO'] == "1":
        #        self.sii_result = "Reparo"
        #elif resp['SII:RESPUESTA']['SII:RESP_HDR']['ESTADO'] == "RCT":
        #    self.sii_result = "Rechazado"

    @api.multi
    def wizard_upload(self):
        return {
                'type': 'ir.actions.act_window',
                'res_model': 'sii.dte.upload_xml.wizard',
                'src_model': 'account.invoice',
                'view_mode': 'form',
                'view_type': 'form',
                'views': [(False, 'form')],
                'target': 'new',
                'tag': 'action_upload_xml_wizard'
                }

    @api.multi
    def wizard_validar(self):
        return {
                'type': 'ir.actions.act_window',
                'res_model': 'sii.dte.validar.wizard',
                'src_model': 'account.invoice',
                'view_mode': 'form',
                'view_type': 'form',
                'views': [(False, 'form')],
                'target': 'new',
                'tag': 'action_validar_wizard'
                }

    @api.multi
    def invoice_print(self):
        self.ensure_one()
        self.sent = True
        if self.ticket:
            return self.env.ref('l10n_cl_fe.action_print_ticket').report_action(self)
        return self.env.ref('account.account_invoices').report_action(self)

    @api.multi
    def print_cedible(self):
        """ Print Cedible
        """
        return self.env.ref('l10n_cl_fe.action_print_cedible').report_action(self)

    @api.multi
    def getTotalDiscount(self):
        total_discount = 0
        for l in self.invoice_line_ids:
            total_discount +=  (((l.discount or 0.00) /100) * l.price_unit * l.quantity)
        return self.currency_id.round(total_discount)
