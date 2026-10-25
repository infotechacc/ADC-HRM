{
    'name': 'BinaryAid Care Fortnightly Timesheets',
    'version': '19.0.1.0.0',
    'category': 'Human Resources',
    'summary': 'Fortnightly timesheet review, corrections, approval, locking, reports and export',
    'description': 'Planned shifts, actual clock events, notes and exceptions per employee and fortnight. '
                   'Original attendance is preserved beside reviewer adjustments; incomplete and unresolved rows '
                   'are excluded from approved totals. Export of approved timesheets does not run payroll.',
    'author': 'BinaryAid',
    'license': 'LGPL-3',
    'depends': ['binaryaid_care_attendance'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/timesheet_data.xml',
        'wizard/timesheet_wizard_views.xml',
        'views/timesheet_views.xml',
        'views/settings_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
}
