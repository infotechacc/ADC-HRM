def migrate(cr, version):
    """The alternative contact list becomes single name, phone and email fields on the client."""
    cr.execute("SELECT to_regclass('binaryaid_care_client_contact')")
    if not cr.fetchone()[0]:
        return
    for column in ('contact_name', 'contact_phone', 'contact_email'):
        cr.execute(f'ALTER TABLE binaryaid_care_client ADD COLUMN IF NOT EXISTS {column} varchar')
    # Keep the first contact of each client (the order shown on the old list).
    cr.execute("""
        UPDATE binaryaid_care_client c
        SET contact_name = f.name, contact_phone = f.phone, contact_email = f.email
        FROM (SELECT DISTINCT ON (client_id) client_id, name, phone, email
              FROM binaryaid_care_client_contact ORDER BY client_id, sequence, id) f
        WHERE f.client_id = c.id
    """)
