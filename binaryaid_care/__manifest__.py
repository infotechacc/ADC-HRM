{
    'name': 'BinaryAid Care Operations',
    'version': '19.0.2.4.0',
    'category': 'Human Resources',
    'summary': 'Clients, care plans, worker documents, team messages and care roster rules',
    'description': 'Australian Diversity Care operations: simple client records with care plans and documents, '
                   'linked to rostered employees, versioned worker documents, team announcements and '
                   'care-specific shift validation. No CRM or sales pipeline is used.',
    'author': 'BinaryAid',
    'license': 'LGPL-3',
    'depends': ['binaryaid_roster_planning', 'hr_holidays'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/care_data.xml',
        'wizard/document_upload_views.xml',
        'views/document_views.xml',
        'views/client_views.xml',
        'views/shift_views.xml',
        'views/employee_views.xml',
        'views/announcement_views.xml',
        'views/leave_views.xml',
        'views/settings_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'binaryaid_care/static/src/shift_form.js',
            'binaryaid_care/static/src/dashboard_care.xml',
            'binaryaid_care/static/src/dashboard_care.scss',
        ],
    },
    'post_init_hook': '_prepare_document_slots',
    'installable': True,
}
