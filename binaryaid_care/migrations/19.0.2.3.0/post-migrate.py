def migrate(cr, version):
    cr.execute("DROP TABLE IF EXISTS binaryaid_care_client_contact CASCADE")
