# -*- coding: utf-8 -*-
from odoo import models, fields, api, SUPERUSER_ID
from odoo.tools.translate import _
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)

try:
    import xmltodict
except ImportError:
    pass

try:
    import base64
except ImportError:
    pass



class caf(models.Model):

    @api.depends('caf_file')
    def _compute_data(self):
        for caf in self:
            if caf:
                caf.load_caf()

    _name = 'dte.caf'

    name = fields.Char('File Name',
       readonly=True,
       compute='_get_filename')

    filename = fields.Char('File Name')

    caf_file = fields.Binary(
        string='CAF XML File',
        filters='*.xml',
        required=True,
        help='Upload the CAF XML File in this holder')

    _sql_constraints=[(
        'filename_unique','unique(filename)','Error! Filename Already Exist!')]

    issued_date = fields.Date('Issued Date',
        compute='_compute_data',
        store=True,)

    sii_document_class = fields.Integer('SII Document Class',
        compute='_compute_data',
        store=True, )

    start_nm = fields.Integer(
        string='Start Number',
        help='CAF Starts from this number',
        compute='_compute_data',
        store=True, )

    final_nm = fields.Integer(
        string='End Number',
        help='CAF Ends to this number',
        compute='_compute_data',
        store=True, )

    status = fields.Selection([
        ('draft', 'Draft'),
        ('in_use', 'In Use'),
        ('spent', 'Spent'),
        ('cancelled', 'Cancelled')], string='Status',
        default='draft',
        help='''Draft: means it has not been used yet. You must put in in used
in order to make it available for use. Spent: means that the number interval
has been exhausted. Cancelled means it has been deprecated by hand.''', )

    rut_n = fields.Char(string='RUT',
        compute='_compute_data',
        store=True, )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=False,
        default=lambda self: self.env.user.company_id)

    sequence_id = fields.Many2one(
        'ir.sequence',
        'Sequence',
        required=True)

    use_level = fields.Float(string="Use Level", compute='_use_level')

    @api.onchange("caf_file",)
    def load_caf(self, flags=False):
        if not self.caf_file:
            return
        result = self.decode_caf()['AUTORIZACION']['CAF']['DA']
        self.start_nm = result['RNG']['D']
        self.final_nm = result['RNG']['H']
        self.sii_document_class = result['TD']
        self.issued_date = result['FA']
        self.rut_n = 'CL' + result['RE'].replace('-','')
        if self.rut_n != self.company_id.vat.replace('L0','L'):
            raise UserError(_(
                'Company vat %s should be the same that assigned company\'s vat: %s!') % (self.rut_n, self.company_id.vat))
        elif self.sii_document_class != self.sequence_id.sii_document_class:
            raise UserError(_(
                '''SII Document Type for this CAF is %s and selected sequence associated document class is %s. This values should be equal for DTE Invoicing to work properly!''') % (self.sii_document_class, self.sequence_id.sii_document_class))
        if flags:
            return True
        self.status = 'in_use'
        self._use_level()

    def _use_level(self):
        for r in self:
            if r.status not in ['draft','cancelled']:
                folio = r.sequence_id.number_next_actual
                try:
                    r.use_level = 100.0 * ((int(folio) - r.start_nm) / float(r.final_nm - r.start_nm + 1))
                except ZeroDivisionError:
                    r.use_level = 0
            else:
                r.use_level = 0

    @api.multi
    def action_enable(self):
        #if self._check_caf():
        if self.load_caf(flags=True):
            self.status = 'in_use'

    @api.multi
    def action_cancel(self):
        self.status = 'cancelled'

    def _get_filename(self):
        for r in self:
            r.name = r.filename

    def decode_caf(self):
        post = base64.b64decode(self.caf_file)
        post = xmltodict.parse(post.replace(
            '<?xml version="1.0"?>','',1))
        return post

class sequence_caf(models.Model):
    _inherit = "ir.sequence"

    def _check_dte(self):
        for r in self:
            obj = r.env['account.journal.sii_document_class'].search([('sequence_id', '=', r.id)], limit=1)
            if not obj: # si s guía de despacho
                obj = self.env['stock.location'].search([('sequence_id','=', r.id)], limit=1)
            if obj:
                r.is_dte = obj.sii_document_class_id.dte and obj.sii_document_class_id.document_type in ['invoice', 'debit_note', 'credit_note','stock_picking']

    def _get_sii_document_class(self):
        for r in self:
            obj = self.env['account.journal.sii_document_class'].search([('sequence_id', '=', r.id)], limit=1)
            if not obj: # si s guía de despacho
                obj = self.env['stock.location'].search([('sequence_id','=', r.id)], limit=1)
            r.sii_document_class = obj.sii_document_class_id.sii_code

    def get_qty_available(self, folio=None):
        folio = folio or self._get_folio()
        try:
            cafs = self.get_caf_files(folio)
        except:
            cafs = False
        available = 0
        folio = int(folio)
        if cafs:
            for c in cafs:
                if folio >= c.start_nm and folio <= c.final_nm:
                    available += c.final_nm - folio
                elif folio <= c.final_nm:
                    available +=  c.final_nm - c.start_nm
                if folio > c.start_nm:
                    available +=1
        return available

    def _qty_available(self):
        for i in self:
            i.qty_available = i.get_qty_available()

    sii_document_class = fields.Integer('SII Code',
        readonly=True,
        compute='_get_sii_document_class')

    is_dte = fields.Boolean('IS DTE?',
        readonly=True,
        compute='_check_dte')

    dte_caf_ids = fields.One2many(
        'dte.caf',
        'sequence_id',
        'DTE Caf')

    qty_available = fields.Integer(
        string="Quantity Available",
        compute="_qty_available"
    )
    forced_by_caf = fields.Boolean(
        string="Forced By CAF",
        default=True,
    )

    def _get_folio(self):
        return self.number_next_actual

    def get_caf_file(self, folio=False):
        folio = folio or self._get_folio()
        caffiles = self.get_caf_files(folio)
        if not caffiles:
            raise UserError(_('''There is no CAF file available or in use \
for this Document. Please enable one.'''))
        for caffile in caffiles:
            if int(folio) >= caffile.start_nm and int(folio) <= caffile.final_nm:
                return caffile.decode_caf()
        msg = '''No Hay caf para el documento: {}, está fuera de rango . Solicite un nuevo CAF en el sitio \
www.sii.cl'''.format(folio)
        raise UserError(_(msg))

    def get_caf_files(self, folio=None):
        '''
            Devuelvo caf actual y futuros
        '''
        folio = folio or self._get_folio()
        if not self.dte_caf_ids:
            raise UserError(_('''There is no CAF file available or in use \
for this Document. Please enable one.'''))
        cafs = self.dte_caf_ids
        sorted(cafs, key=lambda e: e.start_nm)
        result = []
        for caffile in cafs:
            if int(folio) <= caffile.final_nm:
                result.append(caffile)
        if result:
            return result
        return False

    def update_next_by_caf(self, folio=None):
        folio = folio or self._get_folio()
        menor = False
        cafs = self.get_caf_files(folio)
        if not cafs:
            raise UserError(_('No quedan CAFs disponibles'))
        for c in cafs:
            if not menor or c.start_nm < menor.start_nm:
                menor = c
        if menor and int(folio) < menor.start_nm:
            self.sudo(SUPERUSER_ID).write({'number_next': menor.start_nm})

    def _next_do(self):
        number_next = self.number_next
        if self.implementation == 'standard':
            number_next = self.number_next_actual
        folio = super(sequence_caf, self)._next_do()
        if self.forced_by_caf and self.dte_caf_ids:
            self.update_next_by_caf(folio)
            actual = self.number_next
            if self.implementation == 'standard':
                actual = self.number_next_actual
            if number_next +1 != actual: #Fue actualizado
                number_next = actual
            folio = self.get_next_char(number_next)
        return folio
