{
    'name': 'BinaryAid Care Operations',
    'version': '19.0.1.3.0',
    'category': 'Human Resources',
    'summary': 'Clients, client requests, care documents, team messages and care roster rules',
    'description': 'Australian Diversity Care operations: custom client management linked to rostered '
                   'employees, a restricted client request portal, versioned client and worker documents, '
                   'team announcements and care-specific shift validation. No CRM or sales pipeline is used.',
    'author': 'BinaryAid',
    'license': 'LGPL-3',
    'depends': ['binaryaid_roster_planning', 'hr_holidays', 'portal'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/care_data.xml',
        'wizard/document_upload_views.xml',
        'views/document_views.xml',
        'views/client_views.xml',
        'views/request_views.xml',
        'views/shift_views.xml',
        'views/employee_views.xml',
        'views/announcement_views.xml',
        'views/leave_views.xml',
        'views/settings_views.xml',
        'views/menus.xml',
        'views/portal_templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'binaryaid_care/static/src/**/*',
        ],
    },
    'post_init_hook': '_prepare_document_slots',
    'installable': True,
}
