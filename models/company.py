from odoo import fields, models, api
from odoo.tools.translate import _
import re


class DTECompany(models.Model):
    _inherit = 'res.company'


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

    dte_email = fields.Char(
            string='DTE Email',
            related='partner_id.dte_email'
    )
    dte_service_provider = fields.Selection(
            (
                ('SIICERT', 'SII - Certification process'),
                ('SII', 'www.sii.cl'),
            ),
            string='DTE Service Provider',
            help='''Please select your company service \
provider for DTE service.
    ''',
            default='SIICERT',
        )
    dte_resolution_number = fields.Char(
            string='SII Exempt Resolution Number',
            help='''This value must be provided \
and must appear in your pdf or printed tribute document, under the electronic \
stamp to be legally valid.''',
            default='0',
    )
    dte_resolution_date = fields.Date(
            'SII Exempt Resolution Date',
    )
    sii_regional_office_id = fields.Many2one(
            'sii.regional.offices',
            string='SII Regional Office',
        )
    state_id = fields.Many2one(
            related='partner_id.state_id',
            relation="res.country.state",
            string='Ubication',
        )
    company_activities_ids = fields.Many2many(
            string='Activities Names',
            related='partner_id.partner_activities_ids',
            relation='partner.activities',
        )
    responsability_id = fields.Many2one(
            related='partner_id.responsability_id',
            relation='sii.responsability',
            string="Responsability",
            default=lambda self: self._get_default_tp_type(),
        )
    start_date = fields.Date(
            related='partner_id.start_date',
            string='Start-up Date',
        )
    invoice_vat_discrimination_default = fields.Selection(
            [
                    ('no_discriminate_default', 'Yes, No Discriminate Default'),
                    ('discriminate_default', 'Yes, Discriminate Default')
            ],
            string='Invoice VAT discrimination default',
            default='no_discriminate_default',
            required=True,
            help="""Define behaviour on invoices reports. Discrimination or not \
 will depend in partner and company responsability and SII letters\
        setup:
            * If No Discriminate Default, if no match found it won't \
            discriminate by default.
            * If Discriminate Default, if no match found it would \
            discriminate by default.
            """
        )
    activity_description = fields.Many2one(
            string='Glosa Giro',
            related='partner_id.activity_description',
            relation='sii.activity.description',
        )
    city_id = fields.Many2one(
            related='partner_id.city_id',
            relation="res.country.state.city",
            string='City',
        )
    document_number = fields.Char(
            related='partner_id.document_number',
            string="Document Number",
            required=True,
        )
    document_type_id = fields.Many2one(
            related="partner_id.document_type_id",
            relation='sii.document_type',
            string='Document type',
            default=lambda self: self._get_default_doc_type(),
            required=True,
        )

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
            if not self.partner_id.check_vat_cl(document_number):
                self.vat = ''
                self.document_number = ''
                return {'warning': {'title': _('Rut Erróneo'),
                                    'message': _('Rut Erróneo'),
                                    }
                        }
            vat = 'CL%s' % document_number
            exist = self.env['res.partner'].search(
                [
                    ('vat','=', vat),
                    ('vat', '!=',  'CL555555555'),
                    ('commercial_partner_id', '!=', self.id ),
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
