{
    'name': 'BinaryAid Roster Planning',
    'version': '19.0.1.0.1',
    'category': 'Human Resources',
    'summary': 'Versioned roster patterns, bulk assignments, automation and exceptions',
    'description': 'Reusable effective-dated employee rosters with controlled generation, shift coverage and attendance reconciliation.',
    'author': 'BinaryAid',
    'license': 'LGPL-3',
    'depends': ['binaryaid_work_scheduling', 'hr_attendance', 'hr_holidays'],
    'data': ['security/security.xml', 'security/ir.model.access.csv', 'views/planning_views.xml',
             'wizard/planning_wizard_views.xml', 'views/shift_views.xml', 'data/cron.xml'],
    'assets': {'web.assets_backend': ['binaryaid_roster_planning/static/src/dashboard.xml']},
    'installable': True,
}
