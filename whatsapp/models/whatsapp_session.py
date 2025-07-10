# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import json
import logging
import uuid
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)


class WhatsAppSession(models.Model):
    _name = 'whatsapp.session'
    _description = 'WhatsApp Session'
    _order = 'start_time desc'
    _rec_name = 'session_id'

    session_id = fields.Char('Session ID', required=True, index=True)
    account_id = fields.Many2one('whatsapp.account', 'WhatsApp Account', required=True, ondelete='cascade')
    
    # Session info
    start_time = fields.Datetime('Start Time', default=fields.Datetime.now, required=True)
    end_time = fields.Datetime('End Time')
    duration = fields.Integer('Duration (seconds)', compute='_compute_duration', store=True)
    
    # Session data
    session_data = fields.Text('Session Data', help='Encrypted session data')
    user_agent = fields.Char('User Agent')
    ip_address = fields.Char('IP Address')
    
    # Status
    status = fields.Selection([
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('terminated', 'Terminated'),
        ('error', 'Error'),
    ], string='Status', default='active', required=True)
    
    # Statistics
    messages_sent = fields.Integer('Messages Sent', default=0)
    messages_received = fields.Integer('Messages Received', default=0)
    
    # Company
    company_id = fields.Many2one('res.company', 'Company', related='account_id.company_id', store=True)
    
    @api.depends('start_time', 'end_time')
    def _compute_duration(self):
        for session in self:
            if session.start_time and session.end_time:
                delta = session.end_time - session.start_time
                session.duration = int(delta.total_seconds())
            else:
                session.duration = 0

    def terminate_session(self):
        """Terminate session"""
        self.ensure_one()
        
        self.write({
            'status': 'terminated',
            'end_time': fields.Datetime.now(),
        })
        
        # Terminate associated WhatsApp client
        if self.account_id:
            self.account_id.action_disconnect()

    @api.model
    def cleanup_expired_sessions(self):
        """Clean up expired sessions"""
        expired_threshold = fields.Datetime.now() - timedelta(days=7)
        
        expired_sessions = self.search([
            ('status', '=', 'active'),
            ('start_time', '<', expired_threshold)
        ])
        
        for session in expired_sessions:
            session.write({
                'status': 'expired',
                'end_time': fields.Datetime.now(),
            })
        
        return len(expired_sessions)


class WhatsAppNotification(models.Model):
    _name = 'whatsapp.notification'
    _description = 'WhatsApp Notification'
    _order = 'create_date desc'
    _rec_name = 'title'

    title = fields.Char('Title', required=True)
    message = fields.Text('Message', required=True)
    notification_type = fields.Selection([
        ('info', 'Info'),
        ('success', 'Success'),
        ('warning', 'Warning'),
        ('error', 'Error'),
    ], string='Type', default='info', required=True)
    
    # Recipients
    user_id = fields.Many2one('res.users', 'User', required=True, ondelete='cascade')
    account_id = fields.Many2one('whatsapp.account', 'Account', ondelete='cascade')
    
    # Status
    is_read = fields.Boolean('Read', default=False)
    read_date = fields.Datetime('Read Date')
    
    # Actions
    action_url = fields.Char('Action URL')
    action_model = fields.Char('Action Model')
    action_res_id = fields.Integer('Action Resource ID')
    
    # Company
    company_id = fields.Many2one('res.company', 'Company', default=lambda self: self.env.company)

    def mark_as_read(self):
        """Mark notification as read"""
        self.ensure_one()
        
        self.write({
            'is_read': True,
            'read_date': fields.Datetime.now(),
        })

    def action_open(self):
        """Open notification action"""
        self.ensure_one()
        
        # Mark as read
        self.mark_as_read()
        
        if self.action_url:
            return {
                'type': 'ir.actions.act_url',
                'url': self.action_url,
                'target': 'new',
            }
        elif self.action_model and self.action_res_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': self.action_model,
                'res_id': self.action_res_id,
                'view_mode': 'form',
                'target': 'current',
            }
        
        return False

    @api.model
    def create_notification(self, user_id, title, message, notification_type='info', account_id=None, action_url=None, action_model=None, action_res_id=None):
        """Create notification"""
        vals = {
            'title': title,
            'message': message,
            'notification_type': notification_type,
            'user_id': user_id,
            'account_id': account_id,
            'action_url': action_url,
            'action_model': action_model,
            'action_res_id': action_res_id,
        }
        
        notification = self.create(vals)
        
        # Send bus notification
        self.env['bus.bus']._sendone(
            (self._cr.dbname, 'whatsapp.notification', user_id),
            {
                'type': 'whatsapp_notification',
                'notification_id': notification.id,
                'title': title,
                'message': message,
                'notification_type': notification_type,
            }
        )
        
        return notification

    @api.model
    def get_user_notifications(self, user_id=None, unread_only=False):
        """Get user notifications"""
        if not user_id:
            user_id = self.env.user.id
        
        domain = [('user_id', '=', user_id)]
        if unread_only:
            domain.append(('is_read', '=', False))
        
        return self.search(domain)


class WhatsAppBot(models.Model):
    _name = 'whatsapp.bot'
    _description = 'WhatsApp Bot'
    _order = 'name'
    _rec_name = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char('Bot Name', required=True, tracking=True)
    description = fields.Text('Description')
    
    # Bot configuration
    active = fields.Boolean('Active', default=True, tracking=True)
    account_id = fields.Many2one('whatsapp.account', 'WhatsApp Account', required=True, ondelete='cascade')
    
    # Trigger configuration
    trigger_type = fields.Selection([
        ('keyword', 'Keyword'),
        ('pattern', 'Pattern'),
        ('command', 'Command'),
        ('all', 'All Messages'),
    ], string='Trigger Type', default='keyword', required=True)
    
    trigger_value = fields.Char('Trigger Value', help='Keyword, pattern, or command')
    case_sensitive = fields.Boolean('Case Sensitive', default=False)
    
    # Response configuration
    response_type = fields.Selection([
        ('text', 'Text Response'),
        ('template', 'Template Response'),
        ('action', 'Action Response'),
    ], string='Response Type', default='text', required=True)
    
    response_text = fields.Text('Response Text')
    template_id = fields.Many2one('whatsapp.template', 'Response Template')
    action_code = fields.Text('Action Code', help='Python code to execute')
    
    # Conditions
    conditions = fields.Text('Conditions', help='JSON conditions for bot activation')
    
    # Statistics
    trigger_count = fields.Integer('Trigger Count', default=0, readonly=True)
    last_triggered = fields.Datetime('Last Triggered', readonly=True)
    
    # Company
    company_id = fields.Many2one('res.company', 'Company', related='account_id.company_id', store=True)

    def check_trigger(self, message):
        """Check if message triggers this bot"""
        self.ensure_one()
        
        if not self.active:
            return False
        
        message_text = message.get('body', '').strip()
        
        if self.trigger_type == 'keyword':
            if self.case_sensitive:
                return self.trigger_value in message_text
            else:
                return self.trigger_value.lower() in message_text.lower()
        
        elif self.trigger_type == 'pattern':
            import re
            pattern = self.trigger_value
            flags = 0 if self.case_sensitive else re.IGNORECASE
            return bool(re.search(pattern, message_text, flags))
        
        elif self.trigger_type == 'command':
            command = self.trigger_value
            if not self.case_sensitive:
                command = command.lower()
                message_text = message_text.lower()
            return message_text.startswith(command)
        
        elif self.trigger_type == 'all':
            return True
        
        return False

    def process_message(self, message):
        """Process message and generate response"""
        self.ensure_one()
        
        if not self.check_trigger(message):
            return None
        
        # Update statistics
        self.trigger_count += 1
        self.last_triggered = fields.Datetime.now()
        
        try:
            if self.response_type == 'text':
                return self.response_text
            
            elif self.response_type == 'template':
                if self.template_id:
                    # Extract variables from message
                    variables = self._extract_variables(message)
                    return self.template_id.render_template(variables)
                
            elif self.response_type == 'action':
                return self._execute_action(message)
            
        except Exception as e:
            _logger.error(f'Error processing bot message: {e}')
            return None
        
        return None

    def _extract_variables(self, message):
        """Extract variables from message"""
        variables = {
            'sender_name': message.get('contact', {}).get('name', ''),
            'sender_phone': message.get('from', '').replace('@c.us', ''),
            'message_text': message.get('body', ''),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        
        # Extract custom variables based on trigger pattern
        if self.trigger_type == 'pattern':
            import re
            match = re.search(self.trigger_value, message.get('body', ''))
            if match:
                variables.update(match.groupdict())
        
        return variables

    def _execute_action(self, message):
        """Execute action code"""
        if not self.action_code:
            return None
        
        try:
            # Create safe execution context
            context = {
                'message': message,
                'account': self.account_id,
                'bot': self,
                'env': self.env,
                'datetime': datetime,
                'json': json,
            }
            
            # Execute code
            exec(self.action_code, context)
            
            # Return response if set
            return context.get('response')
            
        except Exception as e:
            _logger.error(f'Error executing bot action: {e}')
            return None

    def test_bot(self):
        """Test bot with sample message"""
        self.ensure_one()
        
        sample_message = {
            'body': self.trigger_value or 'Test message',
            'from': '+1234567890@c.us',
            'contact': {
                'name': 'Test User',
                'phone': '+1234567890'
            },
            'timestamp': datetime.now().timestamp()
        }
        
        response = self.process_message(sample_message)
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Bot Test Result',
            'res_model': 'whatsapp.bot.test',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_bot_id': self.id,
                'default_test_message': json.dumps(sample_message, indent=2),
                'default_response': response or 'No response',
            }
        }

    @api.model
    def process_incoming_message(self, account_id, message):
        """Process incoming message with all active bots"""
        bots = self.search([
            ('account_id', '=', account_id),
            ('active', '=', True)
        ])
        
        responses = []
        for bot in bots:
            response = bot.process_message(message)
            if response:
                responses.append({
                    'bot_id': bot.id,
                    'bot_name': bot.name,
                    'response': response
                })
        
        return responses


class WhatsAppIntegration(models.Model):
    _name = 'whatsapp.integration'
    _description = 'WhatsApp Integration'
    _order = 'name'
    _rec_name = 'name'

    name = fields.Char('Integration Name', required=True)
    description = fields.Text('Description')
    
    # Integration type
    integration_type = fields.Selection([
        ('crm', 'CRM Integration'),
        ('sale', 'Sales Integration'),
        ('support', 'Support Integration'),
        ('marketing', 'Marketing Integration'),
        ('custom', 'Custom Integration'),
    ], string='Integration Type', required=True)
    
    # Configuration
    active = fields.Boolean('Active', default=True)
    account_id = fields.Many2one('whatsapp.account', 'WhatsApp Account', required=True, ondelete='cascade')
    
    # Mapping configuration
    field_mappings = fields.Text('Field Mappings', help='JSON field mappings')
    conditions = fields.Text('Conditions', help='JSON conditions')
    
    # Actions
    create_records = fields.Boolean('Create Records', default=True)
    update_records = fields.Boolean('Update Records', default=False)
    
    # Target model
    target_model = fields.Char('Target Model', help='Target Odoo model')
    
    # Company
    company_id = fields.Many2one('res.company', 'Company', related='account_id.company_id', store=True)

    def process_message(self, message):
        """Process message for integration"""
        self.ensure_one()
        
        if not self.active:
            return
        
        try:
            if self.integration_type == 'crm':
                return self._process_crm_integration(message)
            elif self.integration_type == 'sale':
                return self._process_sale_integration(message)
            elif self.integration_type == 'support':
                return self._process_support_integration(message)
            elif self.integration_type == 'marketing':
                return self._process_marketing_integration(message)
            elif self.integration_type == 'custom':
                return self._process_custom_integration(message)
        
        except Exception as e:
            _logger.error(f'Error processing integration: {e}')

    def _process_crm_integration(self, message):
        """Process CRM integration"""
        # Create lead from WhatsApp message
        lead_vals = {
            'name': f'WhatsApp Lead from {message.get("contact", {}).get("name", "Unknown")}',
            'phone': message.get('from', '').replace('@c.us', ''),
            'description': message.get('body', ''),
            'source_id': self.env.ref('whatsapp.lead_source_whatsapp').id,
        }
        
        lead = self.env['crm.lead'].create(lead_vals)
        return lead

    def _process_sale_integration(self, message):
        """Process Sales integration"""
        # Create sales inquiry or quotation
        pass

    def _process_support_integration(self, message):
        """Process Support integration"""
        # Create support ticket
        pass

    def _process_marketing_integration(self, message):
        """Process Marketing integration"""
        # Add to marketing campaign
        pass

    def _process_custom_integration(self, message):
        """Process Custom integration"""
        # Execute custom logic
        pass