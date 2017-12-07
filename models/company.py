from odoo import fields, models, api, _


class dteEmail(models.Model):
    '''
    Email for DTE stuff
    '''
    _inherit = 'res.company'

    dte_email = fields.Char(
            string='DTE Email',
            related='partner_id.dte_email'
    )
    dte_service_provider = fields.Selection(
            (
                ('SIICERT', 'SII - Certification process'),
                ('SII', 'www.sii.cl'),
            ), 'DTE Service Provider', help='''Please select your company service \
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
            "res.country.state",
            'Ubication',
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
        )
    start_date = fields.Date(
        related='partner_id.start_date',
        string='Start-up Date',)
    invoice_vat_discrimination_default = fields.Selection(
        [('no_discriminate_default', 'Yes, No Discriminate Default'),
         ('discriminate_default', 'Yes, Discriminate Default')],
        'Invoice VAT discrimination default',
        default='no_discriminate_default',
        required=True,
        help="""Define behaviour on invoices reports. Discrimination or not \
        will depend in partner and company responsability and SII letters\
        setup:
            * If No Discriminate Default, if no match found it won't \
            discriminate by default.
            * If Discriminate Default, if no match found it would \
            discriminate by default.
            """)
    tp_sii_code = fields.Char(
        'Tax Payer SII Code',
        related='partner_id.tp_sii_code',
        readonly=True,
    )
    activity_description = fields.Many2one(
        string='Glosa Giro',
        related='partner_id.activity_description',
        relation='sii.activity.description',
    )
    city_id = fields.Many2one(
            "res.country.state.city",
            string='City',
        )

    @api.multi
    def _asign_city(self, source):
        if self.city_id:
            return {'value':{'city': self.city_id.name}}
