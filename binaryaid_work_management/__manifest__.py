{
    'name': 'BinaryAid Work Management',
    'version': '19.0.1.2.0',
    'category': 'Human Resources/Employees',
    'summary': 'Employee assignments and dated work history using Odoo tasks',
    'description': 'Assign native Odoo tasks to employees and review dated work notes and completion history from Employees.',
    'author': 'BinaryAid',
    'license': 'LGPL-3',
    'depends': ['hr', 'project'],
    'data': [
        'security/work_security.xml',
        'security/ir.model.access.csv',
        'views/work_views.xml',
        'wizard/work_update_views.xml',
        'views/hr_employee_views.xml',
        'views/work_employee_views.xml',
    ],
    'installable': True,
}
