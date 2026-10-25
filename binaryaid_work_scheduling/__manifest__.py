{
    'name': 'BinaryAid Work Scheduling',
    'version': '19.0.1.5.0',
    'category': 'Human Resources',
    'summary': 'Weekly employee rosters and shift task assignments',
    'description': 'Weekly published employee shifts with existing work tasks and HRMS dashboard integration.',
    'author': 'BinaryAid',
    'license': 'LGPL-3',
    'depends': ['binaryaid_hrms_dashboard'],
    'data': ['security/shift_security.xml', 'security/ir.model.access.csv', 'views/shift_views.xml'],
    'installable': True,
}
