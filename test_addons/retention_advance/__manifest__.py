# -*- coding: utf-8 -*-
{
    'name': 'Retention & Advance Recovery on Invoices',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Accounting',
    'summary': 'Retention and advance recovery on customer progress invoices',
    'description': """
Contracting companies: hold back retention and recover customer advances on progress invoices.
Retention sits in its own account with its own due date, advances are matched against the
invoice, and the accountant can release retention later. Includes an as-at-date report with Excel export.
    """,
    'depends': ['account', 'sale'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/account_move_views.xml',
        'views/account_payment_views.xml',
        'views/res_partner_views.xml',
        'wizard/ra_release_wizard_views.xml',
        'wizard/ra_report_wizard_views.xml',
        'views/menus.xml',
        'report/report_invoice.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
