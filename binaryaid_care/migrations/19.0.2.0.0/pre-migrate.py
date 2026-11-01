def migrate(cr, version):
    """Simplified clients: no client portal, one-line service locations, simple client documents."""
    # Client portal logins only served the removed client request portal.
    cr.execute("""
        UPDATE res_users SET active = false
        WHERE share AND id IN (SELECT user_id FROM binaryaid_care_client_contact WHERE user_id IS NOT NULL)
    """)
    # A service location becomes one text line: keep the address in its name.
    cr.execute("""
        UPDATE binaryaid_care_service_location
        SET name = concat_ws(', ', street, NULLIF(trim(concat_ws(' ', city,
                   (SELECT code FROM res_country_state WHERE id = state_id), zip)), ''))
        WHERE COALESCE(street, '') != ''
    """)
    # Client files move to the simple client document list (see post-migrate); the versioned
    # document records stay for workers only.
    cr.execute("""
        CREATE TABLE IF NOT EXISTS binaryaid_care_client_file_migration AS
        SELECT d.client_id, v.attachment_id, v.file_name, v.create_uid, v.create_date
        FROM binaryaid_care_document d
        JOIN binaryaid_care_document_version v ON v.document_id = d.id
        WHERE d.client_id IS NOT NULL AND v.state = 'approved' AND v.attachment_id IS NOT NULL
    """)
    cr.execute("""
        DELETE FROM binaryaid_care_document_access
        WHERE document_id IN (SELECT id FROM binaryaid_care_document WHERE client_id IS NOT NULL)
    """)
    cr.execute("""
        DELETE FROM binaryaid_care_document_version
        WHERE document_id IN (SELECT id FROM binaryaid_care_document WHERE client_id IS NOT NULL)
    """)
    cr.execute("DELETE FROM binaryaid_care_document WHERE client_id IS NOT NULL")
    cr.execute("""
        DELETE FROM ir_model_data WHERE model = 'binaryaid.care.document.category'
        AND res_id IN (SELECT id FROM binaryaid_care_document_category WHERE applies_to = 'client')
    """)
    cr.execute("DELETE FROM binaryaid_care_document_category WHERE applies_to = 'client'")
