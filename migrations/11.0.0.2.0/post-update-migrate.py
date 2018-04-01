# -*- coding: utf-8 -*-
import logging
_logger = logging.getLogger(__name__)


def migrate(cr, installed_version):
    _logger.warning('Post Migrating l10n_cl_fe from version %s to 11.0.0.2.0' % installed_version)

    cr.execute('ALTER TABLE sii_xml_envio ADD COLUMN invoice_temp INTEGER')
    cr.execute(
        "INSERT INTO sii_xml_envio (invoice_temp, xml_envio, company_id, sii_send_ident, sii_receipt, sii_xml_response, state, name ) SELECT id, xml_temp, company_id, sii_send_ident, sii_receipt_temp, sii_xml_response_temp, sii_result, sii_send_file_name_temp FROM account_invoice ai WHERE ai.xml_temp!=''")
    cr.execute(
        "ALTER TABLE account_invoice DROP COLUMN sii_receipt_temp, DROP COLUMN xml_temp, DROP COLUMN sii_xml_response_temp, DROP COLUMN sii_send_ident_temp, DROP COLUMN sii_send_file_name_temp")
    cr.execute("UPDATE account_invoice ai SET sii_xml_request=sr.id FROM sii_xml_envio sr WHERE ai.id=sr.invoice_temp")
    cr.execute("ALTER TABLE sii_xml_envio DROP COLUMN invoice_temp")
