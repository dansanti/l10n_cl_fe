# -*- coding: utf-8 -*-
from odoo import api, models, fields, _
from odoo.exceptions import Warning
import logging
_logger = logging.getLogger(__name__)

class SiiTaxTemplate(models.Model):
    _inherit = 'account.tax.template'

    sii_code = fields.Integer(
            string='SII Code',
        )
    sii_type = fields.Selection(
            [
                    ('A','Anticipado'),
                    ('R','Retención'),
            ],
            string="Tipo de impuesto para el SII",
        )
    retencion = fields.Float(
            string="Valor retención",
            default=0.00,
        )
    no_rec = fields.Boolean(
            string="Es No Recuperable",
        )
    activo_fijo = fields.Boolean(
            string="Activo Fijo",
            default=False,
        )

class SiiTax(models.Model):
    _inherit = 'account.tax'

    sii_code = fields.Integer(
            string='SII Code',
        )
    sii_type = fields.Selection(
            [
                    ('A','Anticipado'),
                    ('R','Retención'),
            ],
            string="Tipo de impuesto para el SII",
        )
    retencion = fields.Float(
            string="Valor retención",
            default=0.00,
        )
    no_rec = fields.Boolean(
            string="Es No Recuperable",
        )
    activo_fijo = fields.Boolean(
            string="Activo Fijo",
            default=False,
        )

    @api.multi
    def compute_all(self, price_unit, currency=None, quantity=1.0, product=None, partner=None, discount=None):
        """ Returns all information required to apply taxes (in self + their children in case of a tax goup).
            We consider the sequence of the parent for group of taxes.
                Eg. considering letters as taxes and alphabetic order as sequence :
                [G, B([A, D, F]), E, C] will be computed as [A, D, F, C, E, G]
        RETURN: {
            'total_excluded': 0.0,    # Total without taxes
            'total_included': 0.0,    # Total with taxes
            'taxes': [{               # One dict for each tax in self and their children
                'id': int,
                'name': str,
                'amount': float,
                'sequence': int,
                'account_id': int,
                'refund_account_id': int,
                'analytic': boolean,
            }]
        } """
        if len(self) == 0:
            company_id = self.env.user.company_id
        else:
            company_id = self[0].company_id
        if not currency:
            currency = company_id.currency_id
        taxes = []
        # By default, for each tax, tax amount will first be computed
        # and rounded at the 'Account' decimal precision for each
        # PO/SO/invoice line and then these rounded amounts will be
        # summed, leading to the total amount for that tax. But, if the
        # company has tax_calculation_rounding_method = round_globally,
        # we still follow the same method, but we use a much larger
        # precision when we round the tax amount for each line (we use
        # the 'Account' decimal precision + 5), and that way it's like
        # rounding after the sum of the tax amounts of each line
        prec = currency.decimal_places
        base = round(price_unit * quantity, prec+2)
        base = round(base, prec)
        tot_discount = round(base * ((discount or 0.0) /100))
        base -= tot_discount
        total_excluded = base
        total_included = base

        if company_id.tax_calculation_rounding_method == 'round_globally' or not bool(self.env.context.get("round", True)):
            prec += 5

        # Sorting key is mandatory in this case. When no key is provided, sorted() will perform a
        # search. However, the search method is overridden in account.tax in order to add a domain
        # depending on the context. This domain might filter out some taxes from self, e.g. in the
        # case of group taxes.
        for tax in self.sorted(key=lambda r: r.sequence):
            if tax.amount_type == 'group':
                ret = tax.children_tax_ids.compute_all(price_unit, currency, quantity, product, partner)
                total_excluded = ret['total_excluded']
                base = ret['base']
                total_included = ret['total_included']
                tax_amount_retencion = ret['retencion']
                tax_amount = total_included - total_excluded + tax_amount_retencion
                taxes += ret['taxes']
                continue

            tax_amount = tax._compute_amount(base, price_unit, quantity, product, partner)
            if company_id.tax_calculation_rounding_method == 'round_globally' or not bool(self.env.context.get("round", True)):
                tax_amount = round(tax_amount, prec)
            else:
                tax_amount = currency.round(tax_amount)
            tax_amount_retencion = 0
            if tax.sii_type in ['R']:
                tax_amount_retencion = tax._compute_amount_ret(base, price_unit, quantity, product, partner)
                if company_id.tax_calculation_rounding_method == 'round_globally' or not bool(self.env.context.get("round", True)):
                    tax_amount_retencion = round(tax_amount_retencion, prec)
                if tax.price_include:
                    total_excluded -= (tax_amount - tax_amount_retencion )
                    total_included -= (tax_amount_retencion)
                    base -= (tax_amount - tax_amount_retencion )
                else:
                    total_included += (tax_amount - tax_amount_retencion)
            else:
                if tax.price_include:
                    total_excluded -= tax_amount
                    base -= tax_amount
                else:
                    total_included += tax_amount
            # Keep base amount used for the current tax
            tax_base = base

            if tax.include_base_amount:
                base += tax_amount

            taxes.append({
                'id': tax.id,
                'name': tax.with_context(**{'lang': partner.lang} if partner else {}).name,
                'amount': tax_amount,
                'retencion': tax_amount_retencion,
                'base': tax_base,
                'sequence': tax.sequence,
                'account_id': tax.account_id.id,
                'refund_account_id': tax.refund_account_id.id,
                'analytic': tax.analytic,
            })


        return {
            'taxes': sorted(taxes, key=lambda k: k['sequence']),
            'total_excluded': currency.round(total_excluded) if bool(self.env.context.get("round", True)) else total_excluded,
            'total_included': currency.round(total_included) if bool(self.env.context.get("round", True)) else total_included,
            'base': base,
            }

    def _compute_amount(self, base_amount, price_unit, quantity=1.0, product=None, partner=None):
        if self.amount_type == 'percent' and self.price_include:
            neto = base_amount / (1 + self.amount / 100)
            tax = base_amount - neto
            return tax
        return super(SiiTax,self)._compute_amount(base_amount, price_unit, quantity, product, partner)

    def _compute_amount_ret(self, base_amount, price_unit, quantity=1.0, product=None, partner=None):
        if self.amount_type == 'percent' and self.price_include:
            neto = base_amount / (1 + self.retencion / 100)
            tax = base_amount - neto
            return tax
        if (self.amount_type == 'percent' and not self.price_include) or (self.amount_type == 'division' and self.price_include):
            return base_amount * self.retencion / 100

class account_move(models.Model):
    _inherit = "account.move"

    def _get_document_data(self, cr, uid, ids, name, arg, context=None):
        """ TODO """
        res = {}
        for record in self.browse(cr, uid, ids, context=context):
            document_number = False
            if record.model and record.res_id:
                document_number = self.pool[record.model].browse(
                    cr, uid, record.res_id, context=context).document_number
            res[record.id] = document_number
        return res

    @api.depends(
        'sii_document_number',
        'name',
        'document_class_id',
        'document_class_id.doc_code_prefix',
        )
    def _get_document_number(self):
        for r in self:
            if r.sii_document_number and r.document_class_id:
                document_number = (r.document_class_id.doc_code_prefix or '') + r.sii_document_number
            else:
                document_number = r.name
            r.document_number = document_number

    document_class_id = fields.Many2one(
            'sii.document_class',
            string='Document Type',
            copy=False,
            readonly=True,
            states={'draft': [('readonly', False)]},
        )
    sii_document_number = fields.Char(
            string='Document Number',
            copy=False,
            readonly=True,
            states={'draft': [('readonly', False)]},
        )

    canceled = fields.Boolean(
            string="Canceled?",
            readonly=True,
            states={'draft': [('readonly', False)]},
        )
    iva_uso_comun = fields.Boolean(
            string="Iva Uso Común",
            readonly=True,
            states={'draft': [('readonly', False)]},
        )
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
            store=True,
            readonly=True,
            states={'draft': [('readonly', False)]},
        )
    sended = fields.Boolean(
            string="Enviado al SII",
            default=False,
            readonly=True,
            states={'draft': [('readonly', False)]},
        )
    factor_proporcionalidad = fields.Float(
            string="Factor proporcionalidad",
            default=0.00,
            readonly=True,
            states={'draft': [('readonly', False)]},
        )

    def _get_move_imps(self):
        imps = {}
        for l in self.line_ids:
            if l.tax_line_id:
                if l.tax_line_id:
                    if not l.tax_line_id.id in imps:
                        imps[l.tax_line_id.id] = {'tax_id':l.tax_line_id.id, 'credit':0 , 'debit': 0, 'code':l.tax_line_id.sii_code}
                    imps[l.tax_line_id.id]['credit'] += l.credit
                    imps[l.tax_line_id.id]['debit'] += l.debit
                    if l.tax_line_id.activo_fijo:
                        ActivoFijo[1] += l.credit
            elif l.tax_ids and l.tax_ids[0].amount == 0: #caso monto exento
                if not l.tax_ids[0].id in imps:
                    imps[l.tax_ids[0].id] = {'tax_id':l.tax_ids[0].id, 'credit':0 , 'debit': 0, 'code':l.tax_ids[0].sii_code}
                imps[l.tax_ids[0].id]['credit'] += l.credit
                imps[l.tax_ids[0].id]['debit'] += l.debit
        return imps

    def totales_por_movimiento(self):
        move_imps = self._get_move_imps()
        imps = {'iva':0,
                'exento':0,
                'otros_imps':0,
                }
        for key, i in move_imps.items():
            if i['code'] in [14]:
                imps['iva']  += (i['credit'] or i['debit'])
            elif i['code'] == 0:
                imps['exento']  += (i['credit'] or i['debit'])
            else:
                imps['otros_imps']  += (i['credit'] or i['debit'])
        imps['neto'] = self.amount - imps['otros_imps'] - imps['exento'] - imps['iva']
        return imps


class account_move_line(models.Model):
    _inherit = "account.move.line"

    document_class_id = fields.Many2one(
            'sii.document_class',
            string='Document Type',
            related='move_id.document_class_id',
            store=True,
            readonly=True,
        )
    document_number = fields.Char(
            string='Document Number',
            related='move_id.document_number',
            store=True,
            readonly=True,
        )

class account_journal_sii_document_class(models.Model):
    _name = "account.journal.sii_document_class"
    _description = "Journal SII Documents"
    _order = 'sequence'

    name = fields.Char(
            related='sii_document_class_id.name',
        )
    sii_document_class_id = fields.Many2one(
            'sii.document_class',
            string='Document Type',
            required=True,
        )
    sequence_id = fields.Many2one(
            'ir.sequence',
            string='Entry Sequence',
            required=False,
            help="""This field contains the information related to the numbering \
            of the documents entries of this document type.""",
        )
    journal_id = fields.Many2one(
            'account.journal',
            string='Journal',
            required=True,
        )
    sequence = fields.Integer(
            string='Sequence',
        )


class account_journal(models.Model):
    _inherit = "account.journal"

    sucursal_id = fields.Many2one(
            'sii.sucursal',
            string="Sucursal",
        )
    sii_code = fields.Char(
            related='sucursal_id.name',
            string="Código SII Sucursal",
            readonly=True,
        )
    journal_document_class_ids = fields.One2many(
            'account.journal.sii_document_class',
            'journal_id',
            'Documents Class',
        )
    use_documents = fields.Boolean(
            string='Use Documents?',
            default='_get_default_doc',
        )
    journal_activities_ids = fields.Many2many(
            'partner.activities',
            id1='journal_id',
            id2='activities_id',
            string='Journal Turns',
            help="""Select the turns you want to \
            invoice in this Journal""",
        )
    restore_mode = fields.Boolean(
            string="Restore Mode",
            default=False,
        )

    @api.multi
    def _get_default_doc(self):
        self.ensure_one()
        if self.type == 'sale' or self.type == 'purchase':
            self.use_documents = True

class res_currency(models.Model):
    _inherit = "res.currency"

    sii_code = fields.Char(
            string='SII Code',
            size=4,
        )
