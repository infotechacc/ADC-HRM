{
    'name': 'BinaryAid HRMS Dashboard',
    'version': '19.0.1.5.0',
    'category': 'Human Resources',
    'summary': 'Centralised operations dashboard and worker home screen',
    'author': 'BinaryAid',
    'license': 'LGPL-3',
    'depends': ['binaryaid_work_management'],
    'data': ['views/dashboard.xml'],
    'assets': {'web.assets_backend': [
        'binaryaid_hrms_dashboard/static/src/dashboard.js',
        'binaryaid_hrms_dashboard/static/src/dashboard.xml',
        'binaryaid_hrms_dashboard/static/src/dashboard.scss',
        'binaryaid_hrms_dashboard/static/src/form_buttons.xml',
    ]},
    'installable': True,
    'application': True,
}
