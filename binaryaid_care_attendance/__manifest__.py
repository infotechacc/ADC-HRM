{
    'name': 'BinaryAid Care Attendance, Notes and Incidents',
    'version': '19.0.1.0.0',
    'category': 'Human Resources',
    'summary': 'Location verified clock in/out, shift notes, attendance exceptions and incident reports',
    'description': 'Worker clock in/out for assigned published shifts, verified on the server within the '
                   'service location radius; reviewed exceptions; mandatory shift notes saved with clock out; '
                   'restricted incident reporting with media attachments. No continuous location tracking.',
    'author': 'BinaryAid',
    'license': 'LGPL-3',
    'depends': ['binaryaid_care', 'hr_attendance'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/attendance_data.xml',
        'views/attendance_views.xml',
        'views/note_views.xml',
        'views/incident_views.xml',
        'views/settings_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'binaryaid_care_attendance/static/src/**/*',
        ],
    },
    'installable': True,
}
