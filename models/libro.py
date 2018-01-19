# -*- coding: utf-8 -*-
from odoo import fields, models, api, tools
from odoo.tools.translate import _
from odoo.exceptions import UserError
from datetime import datetime, timedelta
import dateutil.relativedelta as relativedelta
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT as DTF
import logging
from lxml import etree
from lxml.etree import Element, SubElement
from lxml import objectify
from lxml.etree import XMLSyntaxError
from odoo import SUPERUSER_ID

import xml.dom.minidom
import pytz
import struct


import socket
import collections
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

#urllib3.disable_warnings()
pool = urllib3.PoolManager(timeout=30)

import textwrap

_logger = logging.getLogger(__name__)

try:
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    import OpenSSL
    from OpenSSL import crypto
    type_ = crypto.FILETYPE_PEM
except:
    _logger.warning('Cannot import OpenSSL library')

try:
    import xmltodict
except ImportError:
    _logger.info('Cannot import xmltodict library')

try:
    import dicttoxml
    dicttoxml.set_debug(False)
except ImportError:
    _logger.info('Cannot import dicttoxml library')

try:
    import base64
except ImportError:
    _logger.info('Cannot import base64 library')

try:
    import hashlib
except ImportError:
    _logger.info('Cannot import hashlib library')

try:
    import cchardet
except ImportError:
    _logger.info('Cannot import cchardet library')

server_url = {'SIICERT':'https://maullin.sii.cl/DTEWS/','SII':'https://palena.sii.cl/DTEWS/'}

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

allowed_docs = [29, 30, 32, 33, 34, 35, 38, 39, 40,
                41, 43, 45, 46, 48, 53, 55, 56, 60,
                61, 101, 102, 103, 104, 105, 106, 108,
                109, 110, 111, 112, 175, 180, 185, 900,
                901, 902, 903, 904, 905, 906, 907, 909,
                910, 911, 914, 918, 919, 920, 921, 922,
                924, 500, 501,
                ]

class Libro(models.Model):
    _name = "account.move.book"

    sii_receipt = fields.Text(
        string='SII Message',
        copy=False)
    sii_message = fields.Text(
        string='SII Message',
        copy=False)
    sii_xml_request = fields.Text(
        string='SII XML Request',
        copy=False)
    sii_xml_response = fields.Text(
        string='SII XML Response',
        copy=False)
    sii_send_ident = fields.Text(
        string='SII Send Identification',
        copy=False)
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('NoEnviado', 'No Enviado'),
        ('Enviado', 'Enviado'),
        ('Aceptado', 'Aceptado'),
        ('Rechazado', 'Rechazado'),
        ('Reparo', 'Reparo'),
        ('Proceso', 'Proceso'),
        ('Reenviar', 'Reenviar'),
        ('Anulado', 'Anulado')],
        'Resultado'
        , index=True, readonly=True, default='draft',
        track_visibility='onchange', copy=False,
        help=" * The 'Draft' status is used when a user is encoding a new and unconfirmed Invoice.\n"
             " * The 'Pro-forma' status is used the invoice does not have an invoice number.\n"
             " * The 'Open' status is used when user create invoice, an invoice number is generated. Its in open status till user does not pay invoice.\n"
             " * The 'Paid' status is set automatically when the invoice is paid. Its related journal entries may or may not be reconciled.\n"
             " * The 'Cancelled' status is used when user cancel invoice.")
    move_ids = fields.Many2many('account.move',
        readonly=True,
        states={'draft': [('readonly', False)]})

    tipo_libro = fields.Selection([
                ('ESPECIAL','Especial'),
                ('MENSUAL','Mensual'),
                ('RECTIFICA', 'Rectifica'),
                ],
                string="Tipo de Libro",
                default='MENSUAL',
                required=True,
                readonly=True,
                states={'draft': [('readonly', False)]}
            )
    tipo_operacion = fields.Selection(
            [
                ('COMPRA','Compras'),
                ('VENTA','Ventas'),
                ('BOLETA','Boleta Electrónica'),
            ],
            string="Tipo de operación",
            default="COMPRA",
            required=True,
            readonly=True,
            states={'draft': [('readonly', False)]},
        )
    tipo_envio = fields.Selection(
            [
                ('AJUSTE','Ajuste'),
                ('TOTAL','Total'),
                ('PARCIAL','Parcial'),
                ('TOTAL','Total'),
            ],
            string="Tipo de Envío",
            default="TOTAL",
            required=True,
            readonly=True,
            states={'draft': [('readonly', False)]},
        )
    folio_notificacion = fields.Char(
            string="Folio de Notificación",
            readonly=True,
            states={'draft': [('readonly', False)]},
        )
    impuestos = fields.One2many(
            'account.move.book.tax',
            'book_id',
            string="Detalle Impuestos",
        )
    currency_id = fields.Many2one(
            'res.currency',
            string='Moneda',
            default=lambda self: self.env.user.company_id.currency_id,
            required=True,
            track_visibility='always',
        )
    total_afecto = fields.Monetary(
            string="Total Afecto",
            readonly=True,
            compute="set_resumen",
            store=True,
        )
    total_exento = fields.Monetary(
            string="Total Exento",
            readonly=True,
            compute='set_resumen',
            store=True,
        )
    total_iva = fields.Monetary(
            string="Total IVA",
            readonly=True,
            compute='set_resumen',
            store=True,
        )
    total_otros_imps = fields.Monetary(
            string="Total Otros Impuestos",
            readonly=True,
            compute='set_resumen',
            store=True,
        )
    total = fields.Monetary(
            string="Total Otros Impuestos",
            readonly=True,
            compute='set_resumen',
            store=True,
        )
    periodo_tributario = fields.Char(
            string='Periodo Tributario',
            required=True,
            readonly=True,
            states={'draft': [('readonly', False)]},
            default=lambda *a: datetime.now().strftime('%Y-%m'),
        )
    company_id = fields.Many2one(
            'res.company',
            string="Compañía",
            required=True,
            default=lambda self: self.env.user.company_id.id,
            readonly=True,
            states={'draft': [('readonly', False)]},
        )
    name = fields.Char(
            string="Detalle",
            required=True,
            readonly=True,
            states={'draft': [('readonly', False)]},
        )
    fact_prop = fields.Float(
            string="Factor proporcionalidad",
            readonly=True,
            states={'draft': [('readonly', False)]},
        )
    nro_segmento = fields.Integer(
            string="Número de Segmento",
            readonly=True,
            states={'draft': [('readonly', False)]},
        )
    date = fields.Date(
            string="Fecha",
            required=True,
            readonly=True,
            states={'draft': [('readonly', False)]},
            default=lambda *a: datetime.now(),
        )
    boletas = fields.One2many(
            'account.move.book.boletas',
            'book_id',
            string="Boletas",
            readonly=True,
            states={'draft': [('readonly', False)]},
        )
    codigo_rectificacion = fields.Char(
            string="Código de Rectificación",
        )

    @api.onchange('periodo_tributario', 'tipo_operacion', 'company_id')
    def set_movimientos(self):
        current = datetime.strptime( self.periodo_tributario + '-01', '%Y-%m-%d' )
        next_month = current + relativedelta.relativedelta(months=1)
        docs = [False, 70, 71]
        operator = 'not in'
        query = [
            ('company_id', '=', self.company_id.id),
            #('sended', '=', False),
            ('date' , '<', next_month.strftime('%Y-%m-%d')),
            ]
        domain = 'sale'
        if self.tipo_operacion in [ 'COMPRA' ]:
            two_month = current + relativedelta.relativedelta(months=-2)
            query.append(('date' , '>=', two_month.strftime('%Y-%m-%d')))
            domain = 'purchase'
        query.append(('journal_id.type', '=', domain))
        if self.tipo_operacion in [ 'VENTA' ]:
            libro_boletas = self.env['account.move.book'].search([
                ('state','not in', ['draft']),
                ('periodo_tributario','=', self.periodo_tributario),
                ('tipo_operacion','=', 'BOLETA'),
            ])
            cfs = self.env['account.move.consumo_folios'].search([
                ('state','not in', [ 'draft', 'Rechazado']),
                ('fecha_inicio','>=', current),
                ('fecha_inicio','<', next_month),
            ])
            if cfs:
                cantidad = {}
                for cf in cfs:
                    if not det.tpo_doc in cantidad:
                        cantidad[str(1)] += cf.total_boletas
                    else:
                        cantidad[str(1)] += cf.total_boletas
                lines = [[5,],]
                for det in cf.impuestos:
                    line = {
                        'currency_id' : self.env.user.company_id.currency_id,
                        'tipo_boleta' : self.env['sii.document_class'].search([('sii_code','=', 39)],limit=1).id,
                        'cantidad_boletas' : cantidad['1'] ,
                        'neto' : det.monto_neto,
                        'impuesto' : self.env['account.tax'].search([('sii_code','=', 14), ('type_tax_use','=','sale'),('company_id','=',self.company_id.id)],limit=1).id,
                        'monto_impuesto' : det.monto_iva,
                        'monto_exento': det.monto_exento,
                        }
                    lines.append([0,0, line])
                self.detalles = lines
        elif self.tipo_operacion in [ 'BOLETA' ]:
            docs = [35, 38, 39, 41]
            cfs = self.env['account.move.consumo_folios'].search([
                ('state','not in', ['draft']),
                ('fecha_inicio','>=', current),
                ('fecha_inicio','<', next_month),
            ])
            lines = [[5,],]
            monto_iva = 0
            monto_exento = 0
            for cf in cfs:
                for i in cf.impuestos:
                    monto_iva += i.monto_iva
                    monto_exento += i.monto_exento
            lines.extend([
                 [0,0, {'tax_id': self.env['account.tax'].search([('sii_code','=', 14), ('type_tax_use','=','sale'),('company_id','=',self.company_id.id)],limit=1).id, 'credit': monto_iva, 'currency_id' : self.env.user.company_id.currency_id.id}],
                 [0,0, {'tax_id': self.env['account.tax'].search([('sii_code','=', 0), ('type_tax_use','=','sale'),('company_id','=',self.company_id.id)],limit=1).id, 'credit': monto_exento, 'currency_id' : self.env.user.company_id.currency_id.id}]
                 ])
            self.impuestos = lines
            operator = 'in'
        if self.tipo_operacion in [ 'VENTA', 'BOLETA' ]:
            query.append(('date' , '>=', current.strftime('%Y-%m-%d')))

        query.append(('document_class_id.sii_code', operator, docs))
        self.move_ids = self.env['account.move'].search(query)


    def _get_imps(self):
        imp = {}
        for move in self.move_ids:
            if move.document_class_id.sii_code not in [35, 38, 39, 41, False, 0]:
                move_imps = move._get_move_imps()
                for key, i in move_imps.items():
                    if not key in imp:
                        imp[key] = i
                    else:
                        imp[key]['credit'] += i['credit']
                        imp[key]['debit'] += i['debit']
        return imp

    @api.onchange('move_ids')
    def set_resumen(self):
        for mov in self.move_ids:
            totales = mov.totales_por_movimiento()
            self.total_afecto += totales['neto']
            self.total_exento += totales['exento']
            self.total_iva += totales['iva']
            self.total_otros_imps += totales['otros_imps']
            self.total += mov.amount

    @api.onchange('move_ids')
    def compute_taxes(self):
        if self.tipo_operacion not in [ 'BOLETA' ]:
            imp = self._get_imps()
            if self.boletas:
                for bol in self.boletas:
                    imp[bol.impuesto.id]['credit'] += bol.monto_impuesto
            if self.impuestos and isinstance(self.id, int):
                self._cr.execute("DELETE FROM account_move_book_tax WHERE book_id=%s", (self.id,))
                self.invalidate_cache()
            lines = [[5,],]
            for key, i in imp.items():
                i['currency_id'] = self.env.user.company_id.currency_id.id
                lines.append([0,0, i])
            self.impuestos = lines

    @api.multi
    def unlink(self):
        for libro in self:
            if libro.state not in ('draft', 'cancel'):
                raise UserError(_('You cannot delete a Validated book.'))
        return super(Libro, self).unlink()

    def split_cert(self, cert):
        certf, j = '', 0
        for i in range(0, 29):
            certf += cert[76 * i:76 * (i + 1)] + '\n'
        return certf

    def create_template_envio(self, RutEmisor, PeriodoTributario, FchResol, NroResol, EnvioDTE,signature_d,TipoOperacion='VENTA',TipoLibro='MENSUAL',TipoEnvio='TOTAL',FolioNotificacion="123", IdEnvio='SetDoc'):
        if TipoOperacion == 'BOLETA' and TipoLibro not in ['ESPECIAL', 'RECTIFICA']:
            raise UserError("Boletas debe ser solamente Tipo Operación ESPECIAL")
        CodigoRectificacion = ''
        if TipoLibro in ['ESPECIAL'] or TipoOperacion in ['BOLETA']:
            FolioNotificacion = '\n<FolioNotificacion>' + FolioNotificacion + '</FolioNotificacion>'
        else:
            FolioNotificacion =''
        if TipoLibro == 'RECTIFICA':
            CodigoRectificacion = '\n<CodAutRec>' + self.codigo_rectificacion + '</CodAutRec>'

        if TipoOperacion in ['BOLETA']:
            TipoOperacion = ''
        else:
            TipoOperacion = '\n<TipoOperacion>'+TipoOperacion+'</TipoOperacion>'
        xml = '''<EnvioLibro ID="{10}">
<Caratula>
<RutEmisorLibro>{0}</RutEmisorLibro>
<RutEnvia>{1}</RutEnvia>
<PeriodoTributario>{2}</PeriodoTributario>
<FchResol>{3}</FchResol>
<NroResol>{4}</NroResol>{5}
<TipoLibro>{6}</TipoLibro>
<TipoEnvio>{7}</TipoEnvio>{8}{11}
</Caratula>
{9}
</EnvioLibro>
'''.format(RutEmisor,
           signature_d['subject_serial_number'],
           PeriodoTributario,
           FchResol,
           NroResol,
           TipoOperacion,
           TipoLibro,
           TipoEnvio,
           FolioNotificacion,
           EnvioDTE,
           IdEnvio,
           CodigoRectificacion,
       )
        return xml

    def time_stamp(self, formato='%Y-%m-%dT%H:%M:%S'):
        tz = pytz.timezone('America/Santiago')
        return datetime.now(tz).strftime(formato)

    def xml_validator(self, some_xml_string, validacion='doc'):
        validacion_type = {
            'doc': 'DTE_v10.xsd',
            'env': 'EnvioDTE_v10.xsd',
            'sig': 'xmldsignature_v10.xsd',
            'libro': 'LibroCV_v10.xsd',
            'libroS': 'LibroCVS_v10.xsd',
            'libro_boleta': 'LibroBOLETA_v10.xsd',
        }
        xsd_file = xsdpath+validacion_type[validacion]
        try:
            xmlschema_doc = etree.parse(xsd_file)
            xmlschema = etree.XMLSchema(xmlschema_doc)
            xml_doc = etree.XML(some_xml_string)
            result = xmlschema.validate(xml_doc)
            if not result:
                xmlschema.assert_(xml_doc)
            return result
        except AssertionError as e:
            _logger.warning(some_xml_string)
            raise UserError(_('XML Malformed Error:  %s') % e.args)

    def get_seed(self, company_id):
        return self.env['account.invoice'].get_seed(company_id)

    def create_template_env(self, doc,simplificado=False):
        simp = 'http://www.sii.cl/SiiDte LibroCV_v10.xsd'
        if simplificado:
            simp ='http://www.sii.cl/SiiDte LibroCVS_v10.xsd'
        xml = '''<LibroCompraVenta xmlns="http://www.sii.cl/SiiDte" \
xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" \
xsi:schemaLocation="{0}" \
version="1.0">
{1}</LibroCompraVenta>'''.format(simp, doc)
        return xml

    def create_template_env_boleta(self, doc):
        xsd = 'http://www.sii.cl/SiiDte LibroBOLETA_v10.xsd'
        xml = '''<LibroBoleta xmlns="http://www.sii.cl/SiiDte" \
xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" \
xsi:schemaLocation="{0}" \
version="1.0">
{1}</LibroBoleta>'''.format(xsd, doc)
        return xml

    def sign_seed(self, message, privkey, cert):
        return self.env['account.invoice'].sign_seed(message, privkey, cert)

    def get_token(self, seed_file, company_id):
        return self.env['account.invoice'].get_token(seed_file, company_id)

    def create_template_seed(self, seed):
        return self.env['account.invoice'].create_template_seed(seed)

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

    def sign_full_xml(self, message, privkey, cert, uri, type='libro'):
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
        att = 'xmlns="http://www.w3.org/2000/09/xmldsig#" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
        #@TODO Find better way to add xmlns:xsi attrib
        signed_info_c14n = signed_info_c14n.decode().replace("<SignedInfo>", "<SignedInfo %s>" % att )
        xmlns = 'http://www.w3.org/2000/09/xmldsig#'
        sig_root = Element("Signature",attrib={'xmlns':xmlns})
        sig_root.append(etree.fromstring(signed_info_c14n))
        signature_value = SubElement(sig_root, "SignatureValue")
        key = crypto.load_privatekey(type_,privkey.encode('ascii'))
        signature = crypto.sign(key,signed_info_c14n,'sha1')
        signature_value.text =textwrap.fill(base64.b64encode(signature).decode(),64)
        key_info = SubElement(sig_root, "KeyInfo")
        key_value = SubElement(key_info, "KeyValue")
        rsa_key_value = SubElement(key_value, "RSAKeyValue")
        modulus = SubElement(rsa_key_value, "Modulus")
        key = load_pem_private_key(privkey.encode('ascii'),password=None, backend=default_backend())
        modulus.text =  textwrap.fill(base64.b64encode(self.long_to_bytes(key.public_key().public_numbers().n)).decode(),64)
        exponent = SubElement(rsa_key_value, "Exponent")
        exponent.text = self.ensure_str(base64.b64encode(self.long_to_bytes(key.public_key().public_numbers().e)))
        x509_data = SubElement(key_info, "X509Data")
        x509_certificate = SubElement(x509_data, "X509Certificate")
        x509_certificate.text = '\n'+textwrap.fill(cert,64)
        msg = etree.tostring(sig_root).decode('iso-8859-1')
        if type != 'libro_boleta':
            msg = msg if self.xml_validator(msg, 'sig') else ''
        if type == 'libro':
            fulldoc = message.replace('</LibroCompraVenta>','%s\n</LibroCompraVenta>' % msg)
        elif type == 'libro_boleta':
            resp = fulldoc = message.replace('</LibroBoleta>','%s\n</LibroBoleta>' % msg)
            xmlns = 'xmlns="http://www.w3.org/2000/09/xmldsig#"'
            xmlns_sii = 'xmlns="http://www.sii.cl/SiiDte"'
            msg = msg.replace(xmlns, xmlns_sii)
            fulldoc = message.replace('</LibroBoleta>', '%s\n</LibroBoleta>' % msg)
        fulldoc = fulldoc if self.xml_validator(fulldoc, type) else ''
        return '<?xml version="1.0" encoding="ISO-8859-1"?>\n%s' % fulldoc

    def get_digital_signature_pem(self, comp_id):
        obj = user = False
        if 'responsable_envio' in self and self._ids:
            obj = user = self[0].responsable_envio
        if not obj:
            obj = user = self.env.user
        if not obj.cert:
            obj = self.env['res.users'].search([("authorized_users_ids","=", user.id)])
            if not obj or not obj.cert:
                obj = self.env['res.company'].browse([comp_id.id])
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
            obj = self.env['res.users'].search([("authorized_users_ids","=", user.id)])
            if not obj or not obj.cert:
                obj = self.env['res.company'].browse([comp_id.id])
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

    @api.multi
    def send_xml_file(self, envio_dte=None, file_name="envio",company_id=False):
        if not company_id.dte_service_provider:
            raise UserError(_("Not Service provider selected!"))
        try:
            signature_d = self.get_digital_signature_pem( company_id )
            seed = self.get_seed(company_id)
            template_string = self.create_template_seed(seed)
            seed_firmado = self.sign_seed(
                template_string,
                signature_d['priv_key'],
                signature_d['cert'])
            token = self.get_token(seed_firmado,company_id)
        except Exception as e:
            _logger.info(connection_status)
            raise UserError(tools.ustr(e))

        url = 'https://palena.sii.cl'
        if company_id.dte_service_provider == 'SIICERT':
            url = 'https://maullin.sii.cl'
        post = '/cgi_dte/UPL/DTEUpload'
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
        params = collections.OrderedDict()
        params['rutSender'] = signature_d['subject_serial_number'][:8]
        params['dvSender'] = signature_d['subject_serial_number'][-1]
        params['rutCompany'] = company_id.vat[2:-1]
        params['dvCompany'] = company_id.vat[-1]
        file_name = file_name + '.xml'
        params['archivo'] = (file_name,envio_dte,"text/xml")
        multi  = urllib3.filepost.encode_multipart_formdata(params)
        headers.update({'Content-Length': '{}'.format(len(multi[0]))})
        response = pool.request_encode_body('POST', url+post, params, headers)
        retorno = {'sii_xml_response': response.data, 'sii_result': 'NoEnviado','sii_send_ident':''}
        if response.status != 200:
            return retorno
        respuesta_dict = xmltodict.parse(response.data)
        if respuesta_dict['RECEPCIONDTE']['STATUS'] != '0':
            _logger.info('l736-status no es 0')
            _logger.info(respuesta_dict)
            _logger.info(connection_status[respuesta_dict['RECEPCIONDTE']['STATUS']])
        else:
            retorno.update({'sii_result': 'Enviado','sii_send_ident':respuesta_dict['RECEPCIONDTE']['TRACKID']})
        return retorno

    @api.multi
    def get_xml_file(self):
        return {
            'type' : 'ir.actions.act_url',
            'url': '/download/xml/libro/%s' % (self.id),
            'target': 'self',
        }

    def format_vat(self, value):
        if not value or value=='' or value == 0:
            value ="CL666666666"
            #@TODO opción de crear código de cliente en vez de rut genérico
        rut = value[:10] + '-' + value[10:]
        rut = rut.replace('CL0','').replace('CL','')
        return rut

    def digest(self, data):
        sha1 = hashlib.new('sha1', data)
        return sha1.digest()

    @api.onchange('periodo_tributario', 'tipo_operacion')
    def _setName(self):
        self.name = self.tipo_operacion
        if self.periodo_tributario:
            self.name += " " + self.periodo_tributario

    @api.multi
    def validar_libro(self):
        self._validar()
        return self.write({'state': 'NoEnviado'})


    def _acortar_str(self, texto, size=1):
        c = 0
        cadena = ""
        while c < size and c < len(texto):
            cadena += texto[c]
            c += 1
        return cadena

    def _TpoImp(self, tasa):
        #if tasa.sii_code in [14, 1]:
        return 1
        #if tasa.sii_code in []: determinar cuando es 18.211 // zona franca
        #    return 2

    def getResumen(self, rec):
        no_product = False
        ob = self.env['account.invoice']
        inv = ob.search([
                        ('move_id','=',rec.id),
                        ])
        det = collections.OrderedDict()
        det['TpoDoc'] = rec.document_class_id.sii_code
        #det['Emisor']
        #det['IndFactCompra']
        if self.tipo_operacion in ['COMPRA']:
            det['NroDoc'] = int(rec.ref)
        else:
            det['NroDoc'] = int(rec.sii_document_number)
        if rec.canceled:
            det['Anulado'] = 'A'
        #det['Operacion']
        #det['TotalesServicio']
        imp = {}
        TaxMnt = 0
        MntExe = 0
        MntIVA = 0
        Neto = 0
        ActivoFijo = [0,0]
        ivas = {}
        for l in rec.line_ids:
            if l.tax_line_id:
                if l.tax_line_id and l.tax_line_id.amount > 0:
                    if l.tax_line_id.sii_code in [14, 15, 17, 18, 19, 30,31, 32 ,33, 34, 36, 37, 38, 39, 41, 47, 48]: # diferentes tipos de IVA retenidos o no
                        if not l.tax_line_id.id in ivas:
                            ivas[l.tax_line_id.id] = {'det': l.tax_line_id, 'credit':0, 'debit': 0}
                        if l.credit > 0:
                            ivas[l.tax_line_id.id]['credit'] += l.credit
                            if l.tax_line_id.activo_fijo:
                                ActivoFijo[1] += l.credit
                        else:
                            ivas[l.tax_line_id.id]['debit'] += l.debit
                            if l.tax_line_id.activo_fijo:
                                ActivoFijo[1] += l.debit
                    else:
                        if not l.tax_line_id.id in imp:
                            imp[l.tax_line_id.id] = {'imp':l.tax_line_id, 'Mnt':0}
                        if l.credit > 0:
                            imp[l.tax_line_id.id]['Mnt'] += l.credit
                            TaxMnt += l.credit
                        else:
                            imp[l.tax_line_id.id]['Mnt'] += l.debit
                            TaxMnt += l.debit
            elif l.tax_ids and l.tax_ids[0].no_rec:
                if not l.tax_ids[0].id in imp:
                    imp[l.tax_ids[0].id] = {'imp':l.tax_ids[0], 'Mnt':0}
                if l.credit > 0:
                    imp[l.tax_ids[0].id]['Mnt'] += l.credit
                    TaxMnt += l.credit
                else:
                    imp[l.tax_ids[0].id]['Mnt'] += l.debit
                    TaxMnt += l.debit
            elif l.tax_ids and l.tax_ids[0].amount > 0:
                if l.credit > 0:
                    Neto += l.credit
                    if l.tax_ids[0].activo_fijo:
                        ActivoFijo[0] += l.credit
                else:
                    Neto += l.debit
                    if l.tax_ids[0].activo_fijo:
                        ActivoFijo[0] += l.debit
            elif l.tax_ids and l.tax_ids[0].amount == 0: #caso monto exento
                if l.credit > 0:
                    MntExe += l.credit
                else:
                    MntExe += l.debit
        if ivas:
            for i, value in ivas.items():
                det['TpoImp'] = self._TpoImp(value['det'])
                det['TasaImp'] = round(value['det'].amount,2)
                continue
        #det['IndServicio']
        #det['IndSinCosto']
        det['FchDoc'] = rec.date
        if rec.journal_id.sii_code:
            det['CdgSIISucur'] = rec.journal_id.sii_code
        det['RUTDoc'] = self.format_vat(rec.partner_id.vat)
        det['RznSoc'] = rec.partner_id.name[:50]
        refs = []
        for ref in inv.referencias:
            if ref.sii_referencia_CodRef and ref.sii_referencia_TpoDocRef.sii_code in allowed_docs:
                ref_line = collections.OrderedDict()
                ref_line['TpoDocRef'] = ref.sii_referencia_TpoDocRef.sii_code
                ref_line['FolioDocRef'] = ref.origen
                refs.append(ref_line)
        if refs:
            det['item_refs'] = refs
        if MntExe > 0 :
            det['MntExe'] = int(round(MntExe,0))
        elif self.tipo_operacion in ['VENTA'] and not Neto > 0:
            det['MntExe'] = 0
        if Neto > 0:
            det['MntNeto'] = int(round(Neto))
            if ivas: # Es algún tipo de iva que puede ser adicional o anticipado
                MntIVA = 0
                for key, i in ivas.items():
                    Mnt = i['credit'] or i['debit']
                    if round(i['credit'] - i['debit']) != 0:
                        Mnt = i['credit'] + i['debit']
                    if i['det'].sii_code not in [14]:
                        imp[i['det'].id] = {'imp': i['det'], 'Mnt': Mnt}
                    MntIVA += int(round(Mnt))
                if not rec.no_rec_code and not rec.iva_uso_comun:
                    det['MntIVA'] = MntIVA
                if ActivoFijo != [0,0]:
                    det['MntActivoFijo'] = Activofijo[0]
                    det['MntIVAActivoFijo'] = Activofijo[1]
                if rec.no_rec_code:
                    det['IVANoRec'] = collections.OrderedDict()
                    det['IVANoRec']['CodIVANoRec'] = rec.no_rec_code
                    det['IVANoRec']['MntIVANoRec'] = MntIVA
                if rec.iva_uso_comun:
                    det['IVAUsoComun'] = MntIVA
        if imp:
            imps = []
            for key, t in imp.items():
                otro = {}
                if t['imp'].no_rec:
                    otro['MntSinCred'] = int(round(t['Mnt']))
                else:
                    otro['OtrosImp'] = collections.OrderedDict()
                    otro['OtrosImp']['CodImp'] = t['imp'].sii_code
                    otro['OtrosImp']['TasaImp'] = round(t['imp'].amount,2)
                    otro['OtrosImp']['MntImp'] = int(round(t['Mnt']))
                imps.append(otro)
            det['itemOtrosImp'] = imps
        if ivas:
            for key, i in ivas.items():
                tasa = i['det']
                if tasa.sii_type in ['R']:
                    if tasa.retencion == tasa.amount:
                        det['IVARetTotal'] = int(round(i['credit'] or i['debit']))
                        MntIVA -= det['IVARetTotal']
                    else:
                        reten = i['credit']
                        tax = i['debit']
                        if self.tipo_operacion in ['VENTA']:
                            tax = i['credit']
                            reten = i['debit']
                        det['IVARetParcial'] = int(round(reten))
                        det['IVANoRetenido'] = int(round(tax))
                        MntIVA -= det['IVARetParcial']
        monto_total = int(round((Neto + MntExe + TaxMnt + MntIVA), 0))
        if no_product :
            monto_total = 0
        det['MntTotal'] = monto_total
        return det

    def _setResumenBoletas(self, rec):
        det = collections.OrderedDict()
        det['TpoDoc'] = rec.tipo_boleta.sii_code
        det['TotDoc'] = det['NroDoc'] = rec.cantidad_boletas
        if rec.impuesto.amount > 0:
            #det['TpoImp'] = self._TpoImp(rec.impuesto)
            det['TasaImp'] = round(rec.impuesto.amount,2)
            det['MntNeto'] = int(round(rec.neto))
            det['MntIVA'] = int(round(rec.monto_impuesto))
        else:
            det['MntExe'] = int(round(rec.neto))
        det['MntTotal'] = int(round(rec.monto_total))
        return det

    def _process_imps(self, tax_line_id, totales=0, currency=None, Neto=0, TaxMnt=0, MntExe=0, ivas={}, imp={}):
        mnt = tax_line_id.compute_all(totales,  currency, 1)['taxes'][0]
        if mnt['amount'] < 0:
            mnt['amount'] *= -1
            mnt['base'] *= -1
        if tax_line_id.sii_code in [14, 15, 17, 18, 19, 30,31, 32 ,33, 34, 36, 37, 38, 39, 41, 47, 48]: # diferentes tipos de IVA retenidos o no
            ivas.setdefault(tax_line_id.id, [ tax_line_id, 0])
            ivas[tax_line_id.id][1] += mnt['amount']
            TaxMnt += mnt['amount']
            Neto += mnt['base']
        else:
            imp.setdefault(tax_line_id.id, [tax_line_id, 0])
            imp[tax_line_id.id][1] += mnt['amount']
            if tax_line_id.amount == 0:
                MntExe += mnt['base']
        return Neto, TaxMnt, MntExe, ivas, imp

    def getResumenBoleta(self, rec):
        det = collections.OrderedDict()
        det['TpoDoc'] = rec.document_class_id.sii_code
        det['FolioDoc'] = int(rec.sii_document_number)
        #if self.env['account.invoice.referencias'].search(
        #        [('origen', '=', det['FolioDoc']),
        #         ('sii_referencia_TpoDocRef', '=', rec.document_class_id.id),
        #         ('sii_referencia_CodRef', '=', '1')
        #        ]) or  \
        #    (rec.document_class_id.sii_code in [39, 41] and
        #     self.env['pos.order.referencias'].search([
        #         ('origen', '=', det['FolioDoc']),
        #         ('sii_referencia_TpoDocRef', '=', rec.document_class_id.id),
        #         ('sii_referencia_CodRef', '=', '1')
        #        ])
        #    ):
        #    det['Anulado'] = 'A'
        det['TpoServ'] = 3
        try:
            det['FchEmiDoc'] = rec.date
            det['FchVencDoc'] = rec.date
        except:
            util_model = self.env['cl.utils']
            fields_model = self.env['ir.fields.converter']
            from_zone = pytz.UTC
            to_zone = pytz.timezone('America/Santiago')
            date_order = util_model._change_time_zone(datetime.strptime(rec.date_order, DTF), from_zone, to_zone).strftime(DTF)
            til_model = self.env['cl.utils']
            fields_model = self.env['ir.fields.converter']
            from_zone = pytz.UTC
            to_zone = pytz.timezone('America/Santiago')
            date_order = util_model._change_time_zone(datetime.strptime(rec.date_order, DTF), from_zone, to_zone).strftime(DTF)
            det['FchEmiDoc'] = date_order[:10]
            det['FchVencDoc'] = date_order[:10]
        #det['PeriodoDesde']
        #det['PeriodoHasta']
        #det['CdgSIISucur']
        Neto = 0
        MntExe = 0
        TaxMnt = 0
        tasa = False
        ivas = {}
        imp = {}
        impuestos = {}
        if 'lines' in rec:
            for line in rec.lines:
                if line.tax_ids:
                    for t in line.tax_ids:
                        impuestos.setdefault(t.id, [t, 0])
                        impuestos[t.id][1] += line.price_subtotal_incl
            for key, t in impuestos.items():
                Neto, TaxMnt, MntExe, ivas, imp = self._process_imps(t[0], t[1], rec.pricelist_id.currency_id, Neto, TaxMnt, MntExe, ivas, imp)
        else:  # si la boleta fue hecha por contabilidad
            for l in rec.line_ids:
                if l.tax_line_id:
                    if l.tax_line_id and l.tax_line_id.amount > 0: #supuesto iva único
                        if l.tax_line_id.sii_code in [14, 15, 17, 18, 19, 30,31, 32 ,33, 34, 36, 37, 38, 39, 41, 47, 48]: # diferentes tipos de IVA retenidos o no
                            if not l.tax_line_id.id in ivas:
                                ivas[l.tax_line_id.id] = [l.tax_line_id, 0]
                            if l.credit > 0:
                                ivas[l.tax_line_id.id][1] += l.credit
                            else:
                                ivas[l.tax_line_id.id][1] += l.debit
                        else:
                            if not l.tax_line_id.id in imp:
                                imp[l.tax_line_id.id] = [l.tax_line_id, 0]
                            if l.credit > 0:
                                imp[l.tax_line_id.id][1] += l.credit
                                TaxMnt += l.credit
                            else:
                                imp[l.tax_line_id.id][1] += l.debit
                                TaxMnt += l.debit
                elif l.tax_ids and l.tax_ids[0].amount > 0:
                    if l.credit > 0:
                        Neto += l.credit
                    else:
                        Neto += l.debit
                elif l.tax_ids and l.tax_ids[0].amount == 0: #caso monto exento
                    if l.credit > 0:
                        MntExe += l.credit
                    else:
                        MntExe += l.debit
        #det['IndServicio']
        #det['IndSinCosto']
        det['RUTCliente'] = self.format_vat(rec.partner_id.vat)
        if TaxMnt > 0:
            det['MntIVA'] = int(round(TaxMnt))
            for key, t in ivas.items():
                det['TasaIVA'] = t[0].amount
        #det['CodIntCLi']
        if MntExe > 0 :
            det['MntExe'] = int(round(MntExe,0))
        monto_total = int(round((Neto + MntExe + TaxMnt), 0))
        det['MntTotal'] = monto_total
        det['MntNeto'] = int(round(Neto))
        det['MntIVA'] = int(round(TaxMnt))
        return det

    def _procesar_otros_imp(self, resumen, resumenP):
        no_rec = 0 if 'TotImpSinCredito' not in resumenP else resumenP['TotImpSinCredito']
        if not 'itemOtrosImp' in resumenP :
            tots = []
            for o in resumen['itemOtrosImp']:
                tot = {}
                if 'MntSinCred' not in o:
                    cod = o['OtrosImp']['CodImp']
                    tot['TotOtrosImp'] = collections.OrderedDict()
                    tot['TotOtrosImp']['CodImp']  = cod
                    tot['TotOtrosImp']['TotMntImp']  = o['OtrosImp']['MntImp']
                    #tot['FctImpAdic']
                    tot['TotOtrosImp']['TotCredImp']  = o['OtrosImp']['MntImp']
                    tots.append(tot)
                else:
                    no_rec += o['MntSinCred']
            if tots:
                resumenP['itemOtrosImp'] = tots
            if no_rec > 0:
                resumenP['TotImpSinCredito'] = no_rec
            return resumenP
        seted = False
        itemOtrosImp = []
        for r in resumen['itemOtrosImp']:
            cod = r['OtrosImp']['CodImp'].replace('_no_rec','')
            for o in resumenP['itemOtrosImp']:
                if o['TotOtrosImp']['CodImp'] == cod:
                    o['TotOtrosImp']['TotMntImp'] += r['OtrosImp']['MntImp']
                    if cod == r['OtrosImp']['CodImp'] and not 'TotCredImp' in o['TotOtrosImp']:
                        o['TotOtrosImp']['TotCredImp'] = r['OtrosImp']['MntImp']
                    elif cod == r['OtrosImp']['CodImp']:
                        o['TotOtrosImp']['TotCredImp'] += r['OtrosImp']['MntImp']
                    seted = True
                    itemOtrosImp.append(o)
                else:
                    no_rec += o['OtrosImp']['MntImp']
            if not seted:
                if cod == o['OtrosImp']['CodImp']:
                    tot = {}
                    tot['TotOtrosImp'] = collections.OrderedDict()
                    tot['TotOtrosImp']['CodImp']  = cod
                    tot['TotOtrosImp']['TotMntImp']  = r['OtrosImp']['MntImp']
                    #tot['FctImpAdic']
                    tot['TotOtrosImp']['TotCredImp'] += o['OtrosImp']['MntImp']
                    itemOtrosImp.append(tot)
                else:
                    no_rec += o['OtrosImp']['MntImp']

        resumenP['itemOtrosImp'] = itemOtrosImp
        if not 'TotImpSinCredito' in resumenP and no_rec > 0:
            resumenP['TotImpSinCredito'] += no_rec
        elif no_rec:
            resumenP['TotImpSinCredito'] = no_rec
        return resumenP

    def _setResumenPeriodo(self,resumen,resumenP):
        resumenP['TpoDoc'] = resumen['TpoDoc']
        if 'TpoImp' in resumen:
            resumenP['TpoImp'] = resumen['TpoImp'] or 1
        if not 'TotDoc' in resumenP:
            resumenP['TotDoc'] =  1
            if 'TotDoc' in resumen:
                resumenP['TotDoc'] = resumen['TotDoc']
        else:
            resumenP['TotDoc'] += 1
        if 'TotAnulado' in resumenP and 'Anulado' in resumen:
            resumenP['TotAnulado'] += 1
            return resumenP
        elif 'Anulado' in resumen:
            resumenP['TotAnulado'] = 1
            return resumenP
        if 'MntExe' in resumen and not 'TotMntExe' in resumenP:
            resumenP['TotMntExe'] = resumen['MntExe']
        elif 'MntExe' in resumen:
            resumenP['TotMntExe'] += resumen['MntExe']
        elif not 'TotMntExe' in resumenP:
            resumenP['TotMntExe'] = 0
        if 'MntNeto' in resumen and not 'TotMntNeto' in resumenP:
            resumenP['TotMntNeto'] = resumen['MntNeto']
        elif 'MntNeto' in resumen:
            resumenP['TotMntNeto'] += resumen['MntNeto']
        elif not 'TotMntNeto' in resumenP:
            resumenP['TotMntNeto'] = 0
        if 'TotOpIVARec' in resumen:
            resumenP['TotOpIVARec'] = resumen['OpIVARec']
        if 'MntIVA' in resumen and not 'TotMntIVA' in resumenP:
            resumenP['TotMntIVA'] = resumen['MntIVA']
        elif 'MntIVA' in resumen:
            resumenP['TotMntIVA'] += resumen['MntIVA']
        elif not 'TotMntIVA' in resumenP:
            resumenP['TotMntIVA'] = 0
        if 'MntActivoFijo' in resumen and not 'TotOpActivoFijo'in resumenP:
            resumenP['TotOpActivoFijo'] = resumen['MntActivoFijo']
            resumenP['TotMntIVAActivoFijo'] = resumen['MntIVAActivoFijo']
        elif 'MntActivoFijo' in resumen:
            resumenP['TotOpActivoFijo'] += resumen['MntActivoFijo']
            resumenP['TotMntIVAActivoFijo'] += resumen['MntIVAActivoFijo']
        if 'IVANoRec' in resumen and not 'itemNoRec' in resumenP:
            tot = {}
            tot['TotIVANoRec'] = collections.OrderedDict()
            tot['TotIVANoRec']['CodIVANoRec'] = resumen['IVANoRec']['CodIVANoRec']
            tot['TotIVANoRec']['TotOpIVANoRec'] = 1
            tot['TotIVANoRec']['TotMntIVANoRec'] = resumen['IVANoRec']['MntIVANoRec']
            resumenP['itemNoRec'] = [tot]
        elif 'IVANoRec' in resumen:
            seted = False
            itemNoRec = []
            for r in resumenP['itemNoRec']:
                if r['TotIVANoRec']['CodIVANoRec'] == resumen['IVANoRec']['CodIVANoRec']:
                    r['TotIVANoRec']['TotOpIVANoRec'] += 1
                    r['TotIVANoRec']['TotMntIVANoRec'] += resumen['IVANoRec']['MntIVANoRec']
                    seted = True
                itemNoRec.extend([r])
            if not seted:
                tot = {}
                tot['TotIVANoRec'] = collections.OrderedDict()
                tot['TotIVANoRec']['CodIVANoRec'] = resumen['IVANoRec']['CodIVANoRec']
                tot['TotIVANoRec']['TotOpIVANoRec'] = 1
                tot['TotIVANoRec']['TotMntIVANoRec'] = resumen['IVANoRec']['MntIVANoRec']
                itemNoRec.extend([tot])
            resumenP['itemNoRec'] = itemNoRec

        if 'IVAUsoComun' in resumen and not 'TotOpIVAUsoComun' in resumenP:
            resumenP['TotOpIVAUsoComun'] = 1
            resumenP['TotIVAUsoComun'] = resumen['IVAUsoComun']
            resumenP['FctProp'] = self.fact_prop
            resumenP['TotCredIVAUsoComun'] = int(round((resumen['IVAUsoComun'] * self.fact_prop )))
        elif 'IVAUsoComun' in resumen:
            resumenP['TotOpIVAUsoComun'] += 1
            resumenP['TotIVAUsoComun'] += resumen['IVAUsoComun']
            resumenP['TotCredIVAUsoComun'] += int(round((resumen['IVAUsoComun'] * self.fact_prop )))
        if 'itemOtrosImp' in resumen:
            resumenP = self._procesar_otros_imp(resumen, resumenP)
        if 'IVARetTotal' in resumen and not 'TotOpIVARetTotal' in resumenP:
            resumenP['TotIVARetTotal'] = resumen['IVARetTotal']
        elif 'IVARetTotal' in resumen:
            resumenP['TotIVARetTotal'] += resumen['IVARetTotal']
        if 'IVARetParcial' in resumen and not 'TotOpIVARetParcial' in resumenP:
            resumenP['TotIVARetParcial'] = resumen['IVARetParcial']
            resumenP['TotIVANoRetenido'] = resumen['IVANoRetenido']
        elif 'IVARetParcial' in resumen:
            resumenP['TotIVARetParcial'] += resumen['IVARetParcial']
            resumenP['TotIVANoRetenido'] += resumen['IVANoRetenido']

        #@TODO otros tipos IVA
        if not 'TotMntTotal' in resumenP:
            resumenP['TotMntTotal'] = resumen['MntTotal']
        else:
            resumenP['TotMntTotal'] += resumen['MntTotal']
        return resumenP

    def _setResumenPeriodoBoleta(self, resumen, resumenP):
        resumenP['TpoDoc'] = resumen['TpoDoc']
        if 'Anulado' in resumen and 'TotAnulado' in resumenP:
            resumenP['TotAnulado'] += 1
            return resumenP
        elif 'Anulado' in resumen:
            resumenP['TotAnulado'] = 1
            return resumenP
        if not 'TotalesServicio' in resumenP:
            resumenP['TotalesServicio'] = collections.OrderedDict()
            resumenP['TotalesServicio']['TpoServ'] = resumen['TpoServ']#@TODO separar por tipo de servicio
            resumenP['TotalesServicio']['TotDoc'] = 0
        resumenP['TotalesServicio']['TotDoc'] += 1
        if 'MntExe' in resumen and not 'TotMntExe' in resumenP['TotalesServicio']:
            resumenP['TotalesServicio']['TotMntExe'] = resumen['MntExe']
        elif 'MntExe' in resumen:
            resumenP['TotalesServicio']['TotMntExe'] += resumen['MntExe']
        elif not 'TotMntExe' in resumenP['TotalesServicio']:
            resumenP['TotalesServicio']['TotMntExe'] = 0
        if 'MntNeto' in resumen and not 'TotMntNeto' in resumenP['TotalesServicio']:
            resumenP['TotalesServicio']['TotMntNeto'] = resumen['MntNeto']
        elif 'MntNeto' in resumen:
            resumenP['TotalesServicio']['TotMntNeto'] += resumen['MntNeto']
        elif not 'TotMntNeto' in resumenP['TotalesServicio']:
            resumenP['TotalesServicio']['TotMntNeto'] = 0
        if 'MntIVA' in resumen and resumen['MntIVA'] > 0:
            resumenP['TotalesServicio']['TasaIVA'] = resumen['TasaIVA']
        if 'MntIVA' in resumen and not 'TotMntIVA' in resumenP['TotalesServicio']:
            resumenP['TotalesServicio']['TotMntIVA'] = resumen['MntIVA']
        elif 'MntIVA' in resumen:
            resumenP['TotalesServicio']['TotMntIVA'] += resumen['MntIVA']
        elif not 'TotMntIVA' in resumenP['TotalesServicio']:
            resumenP['TotalesServicio']['TotMntIVA'] = 0
        if not 'TotMntTotal' in resumenP['TotalesServicio']:
            resumenP['TotalesServicio']['TotMntTotal'] = resumen['MntTotal']
        else:
            resumenP['TotalesServicio']['TotMntTotal'] += resumen['MntTotal']
        return resumenP

    def _validar(self):
        dicttoxml.set_debug(False)
        cant_doc_batch = 0
        company_id = self.company_id
        dte_service = company_id.dte_service_provider
        signature_d = self.get_digital_signature(company_id)
        if not signature_d:
            raise UserError(_('''There is no Signer Person with an \
        authorized signature for you in the system. Please make sure that \
        'user_signature_key' module has been installed and enable a digital \
        signature, for you or make the signer to authorize you to use his \
        signature.'''))
        certp = signature_d['cert'].replace(
            BC, '').replace(EC, '').replace('\n', '')
        resumenes = []
        resumenesPeriodo = {}
        for rec in self.with_context(lang='es_CL').move_ids:
            rec.sended = True
            TpoDoc = rec.document_class_id.sii_code
            if not TpoDoc in resumenesPeriodo:
                resumenesPeriodo[TpoDoc] = {}
            if self.tipo_operacion == 'BOLETA' and rec.document_class_id not in [False, 0] and rec.sii_document_number in [False, 0]:
                if not rec.sii_document_number:
                    orders = sorted(self.env['pos.order'].search(
                            [('account_move', '=', rec.id),
                             ('invoice_id' , '=', False),
                             ('sii_document_number', 'not in', [False, '0']),
                             ('document_class_id.sii_code', 'in', [39, 41]),
                            ]).with_context(lang='es_CL'), key=lambda r: r.sii_document_number)
                    for order in orders:
                        TpoDoc = order.document_class_id.sii_code
                        if not TpoDoc in resumenesPeriodo:
                            resumenesPeriodo[TpoDoc] = {}
                        resumen = self.getResumenBoleta(order)
                        resumenesPeriodo[TpoDoc] = self._setResumenPeriodoBoleta(resumen, resumenesPeriodo[TpoDoc])
                        del(resumen['MntNeto'])
                        del(resumen['MntIVA'])
                        if 'TasaIVA' in resumen:
                            del(resumen['TasaIVA'])
                        resumenes.extend([{'Detalle':resumen}])
                else:
                    resumen = self.getResumenBoleta(rec)
                    resumenesPeriodo[TpoDoc] = self._setResumenPeriodoBoleta(resumen, resumenesPeriodo[TpoDoc])
                    del(resumen['MntNeto'])
                    del(resumen['MntIVA'])
                    del(resumen['TasaIVA'])
            else:
                resumen = self.getResumen(rec)
                resumenes.extend([{'Detalle':resumen}])
            if self.tipo_operacion != 'BOLETA':
                resumenesPeriodo[TpoDoc] = self._setResumenPeriodo(resumen, resumenesPeriodo[TpoDoc])
        if self.boletas:#no es el libro de boletas especial
            for boletas in self.boletas:
                resumenesPeriodo[boletas.tipo_boleta.id] = {}
                resumen = self._setResumenBoletas(boletas)
                del(resumen['TotDoc'])
                resumenesPeriodo[boletas.tipo_boleta.id] = self._setResumenPeriodo(resumen, resumenesPeriodo[boletas.tipo_boleta.id])
                #resumenes.extend([{'Detalle':resumen}])
        lista = ['TpoDoc', 'TpoImp', 'TotDoc', 'TotAnulado', 'TotMntExe', 'TotMntNeto', 'TotalesServicio', 'TotOpIVARec',
                'TotMntIVA', 'TotMntIVA', 'TotOpActivoFijo', 'TotMntIVAActivoFijo', 'itemNoRec', 'TotOpIVAUsoComun',
                'TotIVAUsoComun', 'FctProp', 'TotCredIVAUsoComun', 'itemOtrosImp', 'TotImpSinCredito', 'TotIVARetTotal',
                  'TotIVARetParcial', 'TotMntTotal', 'TotIVANoRetenido',
                 'TotTabPuros', 'TotTabCigarrillos', 'TotTabElaborado', 'TotImpVehiculo',]
        ResumenPeriodo=[]
        for r, value in resumenesPeriodo.items():
            total = collections.OrderedDict()
            if value:
                for v in lista:
                    if v in value:
                        total[v] = value[v]
                ResumenPeriodo.extend([{'TotalesPeriodo':total}])
        dte = collections.OrderedDict()
        if ResumenPeriodo:
            dte['ResumenPeriodo'] = ResumenPeriodo
            dte['item'] = resumenes
        dte['TmstFirma'] = self.time_stamp()
        resol_data = self.get_resolution_data(company_id)
        RUTEmisor = self.format_vat(company_id.vat)
        RUTRecep = "60803000-K" # RUT SII
        xml = dicttoxml.dicttoxml(
            dte, root=False, attr_type=False).decode()
        doc_id =  self.tipo_operacion+'_'+self.periodo_tributario
        libro = self.create_template_envio( RUTEmisor, self.periodo_tributario,
            resol_data['dte_resolution_date'],
            resol_data['dte_resolution_number'],
            xml, signature_d,self.tipo_operacion,self.tipo_libro,self.tipo_envio,self.folio_notificacion, doc_id)
        xml  = self.create_template_env(libro)
        env = 'libro'
        if self.tipo_operacion in['BOLETA']:
                xml  = self.create_template_env_boleta(libro)
                env = 'libro_boleta'
        root = etree.XML( xml )
        xml_pret = etree.tostring(root, pretty_print=True).decode('iso-8859-1')\
                .replace('<item/>','\n')\
                .replace('<item>','\n').replace('</item>','')\
                .replace('<itemNoRec>','').replace('</itemNoRec>','\n')\
                .replace('<itemOtrosImp>','').replace('</itemOtrosImp>','\n')\
                .replace('<item_refs>','').replace('</item_refs>','\n')\
                .replace('_no_rec','')
        envio_dte = self.sign_full_xml(
            xml_pret,
            signature_d['priv_key'],
            certp,
            doc_id,
            env)
        self.sii_xml_request = envio_dte
        return envio_dte, doc_id

    @api.multi
    def do_dte_send_book(self):
        if self.state not in ['NoEnviado', 'Rechazado']:
            raise UserError("El Libro  ya ha sido enviado")
        envio_dte, doc_id =  self._validar()
        company_id = self.company_id
        result = self.send_xml_file(envio_dte, doc_id+'.xml', company_id)
        self.write({
            'sii_xml_response':result['sii_xml_response'],
            'sii_send_ident':result['sii_send_ident'],
            'state': result['sii_result'],
            'sii_xml_request':envio_dte
            })

    def _get_send_status(self, track_id, signature_d,token):
        url = server_url[self.company_id.dte_service_provider] + 'QueryEstUp.jws?WSDL'
        _server = Client(url)
        respuesta = _server.service.getEstUp(self.company_id.vat[2:-1],self.company_id.vat[-1],track_id,token)
        self.sii_receipt = respuesta
        resp = xmltodict.parse(respuesta)
        status = False
        if resp['SII:RESPUESTA']['SII:RESP_HDR']['ESTADO'] == "-11":
            status =  {'warning':{'title':_('Error -11'), 'message': _("Error -11: Espere a que sea aceptado por el SII, intente en 5s más")}}
        if resp['SII:RESPUESTA']['SII:RESP_HDR']['ESTADO'] == "LOK":
            self.state = "Proceso"
            if 'SII:RESP_BODY' in resp['SII:RESPUESTA'] and resp['SII:RESPUESTA']['SII:RESP_BODY']['RECHAZADOS'] == "1":
                self.sii_result = "Rechazado"
        elif resp['SII:RESPUESTA']['SII:RESP_HDR']['ESTADO'] == "LRH":
            self.state = "Rechazado"
            status = {'warning':{'title':_('Error RCT'), 'message': _(resp['SII:RESPUESTA']['SII:RESP_HDR']['GLOSA'])}}
        return status

    @api.multi
    def ask_for_dte_status(self):
        try:
            signature_d = self.get_digital_signature_pem(
                self.company_id)
            seed = self.get_seed(self.company_id)
            template_string = self.create_template_seed(seed)
            seed_firmado = self.sign_seed(
                template_string, signature_d['priv_key'],
                signature_d['cert'])
            token = self.get_token(seed_firmado,self.company_id)
        except:
            raise UserError(connection_status[response.e])
        xml_response = xmltodict.parse(self.sii_xml_response)
        if self.state == 'Enviado':
            status = self._get_send_status(self.sii_send_ident, signature_d, token)
            #if self.state != 'Proceso':
            return status

class Boletas(models.Model):
    _name = 'account.move.book.boletas'

    currency_id = fields.Many2one('res.currency',
        string='Moneda',
        default=lambda self: self.env.user.company_id.currency_id,
        required=True,
        track_visibility='always')
    tipo_boleta = fields.Many2one('sii.document_class',
        string="Tipo de Boleta",
        required=True,
        domain=[('document_letter_id.name','in',['B','M'])])
    rango_inicial = fields.Integer(
        string="Rango Inicial",
        required=True)
    rango_final = fields.Integer(
        string="Rango Final",
        required=True)
    cantidad_boletas = fields.Integer(
        string="Cantidad Boletas",
        rqquired=True)
    neto = fields.Monetary(
        string="Monto Neto",
        required=True)
    impuesto = fields.Many2one('account.tax',
        string="Impuesto",
        required=True,
        domain=[('type_tax_use','!=','none'), '|', ('active', '=', False), ('active', '=', True)])
    monto_impuesto = fields.Monetary(
        compute='_monto_total',
        string="Monto Impuesto",
        required=True)
    monto_total = fields.Monetary(
        compute='_monto_total',
        string="Monto Total",
        required=True)
    book_id = fields.Many2one('account.move.book')

    @api.onchange( 'neto', 'impuesto')
    def _monto_total(self):
        for b in self:
            monto_impuesto = 0
            if b.impuesto and b.impuesto.amount > 0:
                monto_impuesto = b.monto_impuesto = b.neto * (b.impuesto.amount / 100)
            b.monto_total = b.neto + monto_impuesto

    @api.onchange('rango_inicial', 'rango_final')
    def get_cantidad(self):
        if not self.rango_inicial or not self.rango_final:
            return
        if self.rango_final < self.rango_inicial:
            raise UserError("¡El rango Final no puede ser menor al inicial")
        self.cantidad_boletas = self.rango_final - self.rango_inicial +1

class ImpuestosLibro(models.Model):
    _name="account.move.book.tax"

    def get_monto(self):
        for t in self:
            t.amount = t.debit - t.credit
            if t.book_id.tipo_operacion in [ 'VENTA' ]:
                t.amount = t.credit - t.debit

    tax_id = fields.Many2one('account.tax', string="Impuesto")
    credit = fields.Monetary(string="Créditos", default=0.00)
    debit = fields.Monetary(string="Débitos", default=0.00)
    amount = fields.Monetary(compute="get_monto", string="Monto")
    currency_id = fields.Many2one('res.currency',
        string='Moneda',
        default=lambda self: self.env.user.company_id.currency_id,
        required=True,
        track_visibility='always')
    book_id = fields.Many2one('account.move.book', string="Libro")
