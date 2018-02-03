# -*- encoding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError
from odoo.tools.translate import _
import re
import logging
_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _get_default_tp_type(self):
        try:
            return self.env.ref('l10n_cl_fe.res_IVARI')
        except:
            return self.env['sii.responsability']

    def _get_default_doc_type(self):
        try:
            return self.env.ref('l10n_cl_fe.dt_RUT')
        except:
            return self.env['sii.document_type']

    @api.model
    def _get_default_country(self):
        return self.env.user.company_id.country_id.id or self.env.user.partner_id.country_id.id

    state_id = fields.Many2one(
            "res.country.state",
            'Ubication',
        )
    partner_activities_ids = fields.Many2many(
            'partner.activities',
            id1='partner_id',
            id2='activities_id',
            string='Activities Names'
        )
    city_id = fields.Many2one(
            "res.country.state.city",
            'City',
        )
    responsability_id = fields.Many2one(
        'sii.responsability',
        string='Responsability',
        default=lambda self: self._get_default_tp_type(),
    )
    document_type_id = fields.Many2one(
        'sii.document_type',
        string='Document type',
        default=lambda self: self._get_default_doc_type(),
    )
    document_number = fields.Char(
        string='Document number',
        size=64,
    )
    start_date = fields.Date(
        string='Start-up Date',
    )
    tp_sii_code = fields.Char(
        'Tax Payer SII Code',
        compute='_get_tp_sii_code',
        readonly=True,
    )
    activity_description = fields.Many2one(
            'sii.activity.description',
            string='Glosa Giro', ondelete="restrict",
        )
    dte_email = fields.Char(
            string='DTE Email',
        )

    @api.multi
    @api.onchange('responsability_id')
    def _get_tp_sii_code(self):
        for record in self:
            record.tp_sii_code=str(record.responsability_id.tp_sii_code)

    @api.onchange('document_number', 'document_type_id')
    def onchange_document(self):
        mod_obj = self.env['ir.model.data']
        if self.document_number and ((
            'sii.document_type',
            self.document_type_id.id) == mod_obj.get_object_reference(
                'l10n_cl_fe', 'dt_RUT') or ('sii.document_type',
                self.document_type_id.id) == mod_obj.get_object_reference(
                    'l10n_cl_fe', 'dt_RUN')):
            document_number = (
                re.sub('[^1234567890Kk]', '', str(
                    self.document_number))).zfill(9).upper()
            if not self.check_vat_cl(document_number):
                return {'warning': {'title': _('Rut Erróneo'),
                                    'message': _('Rut Erróneo'),
                                    }
                        }
            vat = 'CL%s' % document_number
            exist = self.env['res.partner'].search(
                [
                    ('vat','=', vat),
                    ('vat', '!=',  'CL555555555'),
                    ('commercial_partner_id', '!=', self.commercial_partner_id.id ),
                ],
                limit=1,
            )
            if exist:
                self.vat = ''
                self.document_number = ''
                return {'warning': {'title': 'Informacion para el Usuario',
                                    'message': _("El usuario %s está utilizando este documento" ) % exist.name,
                                    }}
            self.vat = vat
            self.document_number = '%s.%s.%s-%s' % (
                                        document_number[0:2], document_number[2:5],
                                        document_number[5:8], document_number[-1],
                                    )
        elif self.document_number and (
            'sii.document_type',
            self.document_type_id.id) == mod_obj.get_object_reference(
                'l10n_cl_fe',
                'dt_Sigd',
            ):
            self.document_number = ''
        else:
            self.vat = ''

    @api.onchange('city_id')
    def _asign_city(self):
        if self.city_id:
            self.city = self.city_id.name

    @api.constrains('vat', 'commercial_partner_id')
    def _rut_unique(self):
        for r in self:
            if not r.vat or r.parent_id:
                continue
            partner = self.env['res.partner'].search(
                [
                    ('vat','=', r.vat),
                    ('id','!=', r.id),
                    ('commercial_partner_id', '!=', r.commercial_partner_id.id),
                ])
            if r.vat !="CL555555555" and partner:
                raise UserError(_('El rut: %s debe ser único') % r.vat)
                return False

    def check_vat_cl(self, vat):
        body, vdig = '', ''
        if len(vat) != 9:
            return False
        else:
            body, vdig = vat[:-1], vat[-1].upper()
        try:
            vali = list(range(2,8)) + [2,3]
            operar = '0123456789K0'[11 - (
                sum([int(digit)*factor for digit, factor in zip(
                    body[::-1],vali)]) % 11)]
            if operar == vdig:
                return True
            else:
                return False
        except IndexError:
            return False
