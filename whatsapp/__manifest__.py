# -*- coding: utf-8 -*-

{
    'name': 'WhatsApp Integration',
    'version': '18.0.1.0.0',
    'category': 'Productivity/Discuss',
    'sequence': 146,
    'summary': 'WhatsApp Web API Integration for Odoo',
    'description': """
WhatsApp Integration for Odoo 18
=================================

This module provides comprehensive WhatsApp integration for Odoo using the WhatsApp Web API.

Key Features:
- Connect multiple WhatsApp accounts
- Send and receive messages in real-time
- Support for text, images, documents, and other media
- Contact synchronization with Odoo partners
- Group management capabilities
- Integration with CRM, Sales, and other business modules
- Real-time message notifications
- Message templates and bulk messaging
- Secure authentication and session management

Requirements:
- Node.js runtime for WhatsApp Web API
- whatsapp-web.js library
- Proper network configuration for WhatsApp Web access

Usage:
1. Install the module
2. Configure WhatsApp accounts in Settings
3. Scan QR codes to authenticate
4. Start sending and receiving messages
5. Integrate with business processes

Security:
- All WhatsApp sessions are encrypted
- Proper access control and permissions
- Secure token handling
- Data privacy compliance

Technical Implementation:
- Uses whatsapp-web.js library for WhatsApp Web API
- Real-time message handling with websockets
- Asynchronous message processing
- Integration with Odoo's messaging system
- Responsive web interface for chat
- Mobile-friendly design
""",
    'author': 'Odoo Expert Team',
    'website': 'https://www.odoo.com',
    'depends': [
        'base',
        'base_setup',
        'mail',
        'bus',
        'web',
        'web_tour',
        'crm',
        'sale',
        'contacts',
        'portal',
        'attachment_indexation',
    ],
    'external_dependencies': {
        'python': ['requests', 'websocket-client'],
    },
    'data': [
        'security/ir.model.access.csv',
        
        # 'data/whatsapp_data.xml',
        # 'data/ir_cron_data.xml',
        
        'views/whatsapp_account_views.xml',
        'views/whatsapp_message_views.xml',
        'views/whatsapp_contact_views.xml',
        'views/whatsapp_group_views.xml',
        'views/whatsapp_template_views.xml',
        'views/whatsapp_wizard_views.xml',
        'views/whatsapp_group_wizard_views.xml',
        'views/whatsapp_dashboard_views.xml',
        'views/whatsapp_menus.xml',
        
        'views/res_partner_views.xml',
        'views/res_config_settings_views.xml',
        'views/crm_lead_views.xml',
        'views/sale_order_views.xml',
    ],
    'demo': [
        # 'demo/whatsapp_demo.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'whatsapp/static/src/scss/whatsapp.scss',
            'whatsapp/static/src/js/whatsapp_service.js',
            'whatsapp/static/src/js/whatsapp_chat_window.js',
            'whatsapp/static/src/js/whatsapp_message_composer.js',
            'whatsapp/static/src/xml/whatsapp_templates.xml',
        ],
        'web.assets_qweb': [
            'whatsapp/static/src/xml/**/*',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'images': ['static/description/banner.png'],
    # 'post_init_hook': 'post_init_hook',
    # 'uninstall_hook': 'uninstall_hook',
}