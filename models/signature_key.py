# -*- coding: utf-8 -*-

import logging
from datetime import datetime

_logger = logging.getLogger(__name__)

try:
    from OpenSSL import crypto
    type_ = crypto.FILETYPE_PEM
except ImportError:
    _logger.warning('OpenSSL library not found, please install the library from https://pypi.python.org/pypi/pyOpenSSL')

from odoo import models, fields, api, tools
from odoo.tools.translate import _
from odoo.exceptions import UserError

zero_values = {
    "filename": "",
    "key_file": False,
    "dec_pass":"",
    "not_before": False,
    "not_after": False,
    "status": "unverified",
    "final_date": False,
    "subject_title": "",
    "subject_c": "",
    "subject_serial_number": "",
    "subject_common_name": "",
    "subject_email_address": "",
    "issuer_country": "",
    "issuer_serial_number": "",
    "issuer_common_name": "",
    "issuer_email_address": "",
    "issuer_organization": "",
    "cert_serial_number": "",
    "cert_signature_algor": "",
    "cert_version": "",
    "cert_hash": "",
    "private_key_bits": "",
    "private_key_check": "",
    "private_key_type": "",
    "cert": "",
}

class SignatureKey(models.AbstractModel):

    _name = 'signature.key'
    _description = 'Firma electronica'

    filename = fields.Char(string='File Name')
    key_file = fields.Binary(
        string='Signature File', required=False, store=True,
        help='Upload the Signature File')
    dec_pass = fields.Char(string='Pasword')
    # vigencia y estado
    not_before = fields.Date(
        string='Not Before', help='Not Before this Date', readonly=True)
    not_after = fields.Date(
        string='Not After', help='Not After this Date', readonly=True)
    status = fields.Selection(
        [('unverified', 'Unverified'), ('valid', 'Valid'), ('expired', 'Expired')],
        string='Status', default='unverified',
        help='''Draft: means it has not been checked yet.\nYou must press the\
"check" button.''')
    final_date = fields.Date(
        string='Last Date', help='Last Control Date', readonly=True)
    # sujeto
    subject_title = fields.Char(string='Subject Title', readonly=True)
    subject_c = fields.Char(string='Subject Country', readonly=True)
    subject_serial_number = fields.Char(
        string='Subject Serial Number')
    subject_common_name = fields.Char(
        string='Subject Common Name', readonly=True)
    subject_email_address = fields.Char(
        string='Subject Email Address', readonly=True)
    # emisor
    issuer_country = fields.Char(string='Issuer Country', readonly=True)
    issuer_serial_number = fields.Char(
        string='Issuer Serial Number', readonly=True)
    issuer_common_name = fields.Char(
        string='Issuer Common Name', readonly=True)
    issuer_email_address = fields.Char(
        string='Issuer Email Address', readonly=True)
    issuer_organization = fields.Char(
        string='Issuer Organization', readonly=True)
    # data del certificado
    cert_serial_number = fields.Char(string='Serial Number', readonly=True)
    cert_signature_algor = fields.Char(string='Signature Algorithm', readonly=True)
    cert_version  = fields.Char(string='Version', readonly=True)
    cert_hash = fields.Char(string='Hash', readonly=True)
    # data privad, readonly=Truea
    private_key_bits = fields.Char(string='Private Key Bits', readonly=True)
    private_key_check = fields.Char(string='Private Key Check', readonly=True)
    private_key_type = fields.Char(string='Private Key Type', readonly=True)
    cert = fields.Text(string='Certificate', readonly=True)
    priv_key = fields.Text(string='Private Key', readonly=True)
    
    def load_cert_pk12(self, filecontent):
        try:
            p12 = crypto.load_pkcs12(filecontent, self.dec_pass)
        except Exception as ex:
            raise UserError(tools.ustr(ex))
        
        cert = p12.get_certificate()
        privky = p12.get_privatekey()
        issuer = cert.get_issuer()
        subject = cert.get_subject()

        self.not_before = datetime.strptime(cert.get_notBefore().decode("utf-8") , '%Y%m%d%H%M%SZ')
        self.not_after = datetime.strptime(cert.get_notAfter().decode("utf-8") , '%Y%m%d%H%M%SZ')

        self.subject_c = subject.C
        self.subject_title = subject.title
        self.subject_common_name = subject.CN
        self.subject_serial_number = subject.serialNumber
        self.subject_email_address = subject.emailAddress

        self.issuer_country = issuer.C
        self.issuer_organization = issuer.O
        self.issuer_common_name = issuer.CN
        self.issuer_serial_number = issuer.serialNumber
        self.issuer_email_address = issuer.emailAddress
        self.status = 'expired' if cert.has_expired() else 'valid'

        self.cert_serial_number = cert.get_serial_number()
        self.cert_signature_algor = cert.get_signature_algorithm()
        self.cert_version  = cert.get_version()
        self.cert_hash = cert.subject_name_hash()

        # data privada
        self.private_key_bits = privky.bits()
        self.private_key_check = privky.check()
        self.private_key_type = privky.type()

        self.priv_key = crypto.dump_privatekey(type_, privky)
        self.cert = crypto.dump_certificate(type_, cert)
