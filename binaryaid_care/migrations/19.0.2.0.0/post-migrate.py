import base64

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Remove the client request data and recreate the saved client files as simple client documents."""
    cr.execute('DROP TABLE IF EXISTS binaryaid_care_client_request CASCADE')
    cr.execute("SELECT to_regclass('binaryaid_care_client_file_migration')")
    if not cr.fetchone()[0]:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("SELECT client_id, attachment_id, file_name, create_uid, create_date "
               "FROM binaryaid_care_client_file_migration ORDER BY create_date")
    Attachment = env['ir.attachment']
    for client_id, attachment_id, file_name, create_uid, create_date in cr.fetchall():
        attachment = Attachment.browse(attachment_id).exists()
        if not attachment:
            continue
        document = env['binaryaid.care.client.document'].create({
            'client_id': client_id, 'name': file_name or attachment.name,
            'file': base64.b64encode(attachment.raw or b'')})
        cr.execute('UPDATE binaryaid_care_client_document SET create_uid = %s, create_date = %s WHERE id = %s',
                   [create_uid, create_date, document.id])
        attachment.unlink()
    cr.execute('DROP TABLE binaryaid_care_client_file_migration')
