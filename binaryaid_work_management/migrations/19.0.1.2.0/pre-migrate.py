def migrate(cr, version):
    # Preserve existing dates while changing their meaning to user-selected work dates.
    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'project_task' AND column_name IN
            ('binaryaid_assignment_date', 'binaryaid_work_date')
    """)
    columns = {row[0] for row in cr.fetchall()}
    if 'binaryaid_assignment_date' in columns and 'binaryaid_work_date' not in columns:
        cr.execute('ALTER TABLE project_task RENAME COLUMN binaryaid_assignment_date TO binaryaid_work_date')
        cr.execute('ALTER INDEX IF EXISTS project_task__binaryaid_assignment_date_index RENAME TO project_task__binaryaid_work_date_index')
        cr.execute("""
            UPDATE ir_model_fields SET name = 'binaryaid_work_date'
            WHERE model = 'project.task' AND name = 'binaryaid_assignment_date'
        """)
        cr.execute("""
            UPDATE ir_model_data SET name = 'field_project_task__binaryaid_work_date'
            WHERE module = 'binaryaid_work_management' AND model = 'ir.model.fields'
              AND name = 'field_project_task__binaryaid_assignment_date'
        """)
        for column in ('domain', 'context', 'sort'):
            cr.execute(f"""
                UPDATE ir_filters SET {column} = replace({column}, 'binaryaid_assignment_date', 'binaryaid_work_date')
                WHERE model_id = 'project.task' AND {column} LIKE '%binaryaid_assignment_date%'
            """)
