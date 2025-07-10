# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    
    # Basic WhatsApp Settings
    whatsapp_enabled = fields.Boolean(
        string='Enable WhatsApp Integration',
        config_parameter='whatsapp.enabled',
        default=True
    )
    
    whatsapp_default_account_id = fields.Many2one(
        'whatsapp.account',
        string='Default WhatsApp Account',
        config_parameter='whatsapp.default_account_id'
    )
    
    # Server Configuration
    whatsapp_server_url = fields.Char(
        string='WhatsApp Server URL',
        config_parameter='whatsapp.server_url',
        default='http://localhost:3000'
    )
    
    whatsapp_server_token = fields.Char(
        string='Server Token',
        config_parameter='whatsapp.server_token',
        default='your-secret-token'
    )
    
    # Auto Reply Settings
    whatsapp_auto_reply_enabled = fields.Boolean(
        string='Enable Auto Reply',
        config_parameter='whatsapp.auto_reply_enabled',
        default=False
    )
    
    whatsapp_auto_reply_message = fields.Text(
        string='Auto Reply Message',
        config_parameter='whatsapp.auto_reply_message',
        default='Thank you for your message. We will get back to you soon.'
    )
    
    # CRM Integration
    whatsapp_create_lead_from_message = fields.Boolean(
        string='Create Lead from Messages',
        config_parameter='whatsapp.create_lead_from_message',
        default=False
    )
    
    whatsapp_lead_source_id = fields.Many2one(
        'utm.source',
        string='Lead Source',
        config_parameter='whatsapp.lead_source_id'
    )
    
    # Notification Settings
    whatsapp_notification_enabled = fields.Boolean(
        string='Enable Notifications',
        config_parameter='whatsapp.notification_enabled',
        default=True
    )
    
    whatsapp_notification_sound = fields.Boolean(
        string='Notification Sound',
        config_parameter='whatsapp.notification_sound',
        default=True
    )
    
    # Message Settings
    whatsapp_message_retention_days = fields.Integer(
        string='Message Retention Days',
        config_parameter='whatsapp.message_retention_days',
        default=365,
        help='Number of days to keep WhatsApp messages (0 = forever)'
    )
    
    whatsapp_max_file_size = fields.Integer(
        string='Max File Size (MB)',
        config_parameter='whatsapp.max_file_size',
        default=50,
        help='Maximum file size for WhatsApp attachments in MB'
    )
    
    # Webhook Settings
    whatsapp_webhook_enabled = fields.Boolean(
        string='Enable Webhooks',
        config_parameter='whatsapp.webhook_enabled',
        default=True
    )
    
    whatsapp_webhook_secret = fields.Char(
        string='Webhook Secret',
        config_parameter='whatsapp.webhook_secret',
        default='your-webhook-secret'
    )
    
    # Advanced Settings
    whatsapp_rate_limit = fields.Integer(
        string='Rate Limit (messages/minute)',
        config_parameter='whatsapp.rate_limit',
        default=10,
        help='Maximum messages per minute per account'
    )
    
    whatsapp_debug_mode = fields.Boolean(
        string='Debug Mode',
        config_parameter='whatsapp.debug_mode',
        default=False
    )
    
    @api.constrains('whatsapp_message_retention_days')
    def _check_message_retention_days(self):
        for record in self:
            if record.whatsapp_message_retention_days < 0:
                raise ValidationError(_('Message retention days must be positive or zero.'))
    
    @api.constrains('whatsapp_max_file_size')
    def _check_max_file_size(self):
        for record in self:
            if record.whatsapp_max_file_size <= 0 or record.whatsapp_max_file_size > 100:
                raise ValidationError(_('Max file size must be between 1 and 100 MB.'))
    
    @api.constrains('whatsapp_rate_limit')
    def _check_rate_limit(self):
        for record in self:
            if record.whatsapp_rate_limit <= 0:
                raise ValidationError(_('Rate limit must be positive.'))
    
    def action_test_whatsapp_connection(self):
        """Test connection to WhatsApp server"""
        try:
            # Test the connection to WhatsApp server
            import requests
            
            server_url = self.whatsapp_server_url
            if not server_url:
                raise ValidationError(_('Please configure the WhatsApp server URL first.'))
            
            # Test endpoint
            response = requests.get(f'{server_url}/status', timeout=10)
            
            if response.status_code == 200:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Connection Test'),
                        'message': _('WhatsApp server connection successful!'),
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                raise ValidationError(_('Server responded with status code: %s') % response.status_code)
                
        except requests.exceptions.RequestException as e:
            raise ValidationError(_('Connection failed: %s') % str(e))
        except Exception as e:
            raise ValidationError(_('Unexpected error: %s') % str(e))
    
    def action_cleanup_old_messages(self):
        """Clean up old WhatsApp messages"""
        if self.whatsapp_message_retention_days <= 0:
            raise ValidationError(_('Message retention days must be greater than 0 to cleanup messages.'))
        
        try:
            from datetime import datetime, timedelta
            
            cutoff_date = datetime.now() - timedelta(days=self.whatsapp_message_retention_days)
            
            # Delete old messages
            old_messages = self.env['whatsapp.message'].search([
                ('timestamp', '<', cutoff_date)
            ])
            
            message_count = len(old_messages)
            old_messages.unlink()
            
            # Delete old notifications
            old_notifications = self.env['whatsapp.notification'].search([
                ('timestamp', '<', cutoff_date)
            ])
            
            notification_count = len(old_notifications)
            old_notifications.unlink()
            
            # Delete old attachments
            old_attachments = self.env['whatsapp.attachment'].search([
                ('upload_date', '<', cutoff_date)
            ])
            
            attachment_count = len(old_attachments)
            old_attachments.unlink()
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Cleanup Complete'),
                    'message': _('Cleaned up %d messages, %d notifications, and %d attachments.') % (
                        message_count, notification_count, attachment_count),
                    'type': 'success',
                    'sticky': False,
                }
            }
            
        except Exception as e:
            raise ValidationError(_('Cleanup failed: %s') % str(e))
    
    def action_setup_whatsapp_lead_source(self):
        """Setup WhatsApp lead source"""
        try:
            # Create or get WhatsApp lead source
            lead_source = self.env['utm.source'].search([('name', '=', 'WhatsApp')], limit=1)
            
            if not lead_source:
                lead_source = self.env['utm.source'].create({
                    'name': 'WhatsApp',
                    'active': True,
                })
            
            # Update configuration
            self.whatsapp_lead_source_id = lead_source.id
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Setup Complete'),
                    'message': _('WhatsApp lead source has been configured successfully.'),
                    'type': 'success',
                    'sticky': False,
                }
            }
            
        except Exception as e:
            raise ValidationError(_('Setup failed: %s') % str(e))
    
    def _get_int_param(self, param_name, default=0):
        """安全地获取整数参数"""
        param_value = self.env['ir.config_parameter'].sudo().get_param(param_name, default=str(default))
        try:
            return int(param_value) if param_value else default
        except (ValueError, TypeError):
            return default

    def _get_bool_param(self, param_name, default=False):
        """安全地获取布尔参数"""
        param_value = self.env['ir.config_parameter'].sudo().get_param(param_name, default=str(default))
        return param_value in ('True', 'true', '1')
    
    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        
        # Get WhatsApp configuration values
        ICPSudo = self.env['ir.config_parameter'].sudo()
        
        res.update({
            'whatsapp_enabled': self._get_bool_param('whatsapp.enabled', True),
            'whatsapp_default_account_id': self._get_int_param('whatsapp.default_account_id') or False,
            'whatsapp_server_url': ICPSudo.get_param('whatsapp.server_url', default='http://localhost:3000'),
            'whatsapp_server_token': ICPSudo.get_param('whatsapp.server_token', default='your-secret-token'),
            'whatsapp_auto_reply_enabled': self._get_bool_param('whatsapp.auto_reply_enabled', False),
            'whatsapp_auto_reply_message': ICPSudo.get_param('whatsapp.auto_reply_message', default='Thank you for your message. We will get back to you soon.'),
            'whatsapp_create_lead_from_message': self._get_bool_param('whatsapp.create_lead_from_message', False),
            'whatsapp_lead_source_id': self._get_int_param('whatsapp.lead_source_id') or False,
            'whatsapp_notification_enabled': self._get_bool_param('whatsapp.notification_enabled', True),
            'whatsapp_notification_sound': self._get_bool_param('whatsapp.notification_sound', True),
            'whatsapp_message_retention_days': self._get_int_param('whatsapp.message_retention_days', 365),
            'whatsapp_max_file_size': self._get_int_param('whatsapp.max_file_size', 50),
            'whatsapp_webhook_enabled': self._get_bool_param('whatsapp.webhook_enabled', True),
            'whatsapp_webhook_secret': ICPSudo.get_param('whatsapp.webhook_secret', default='your-webhook-secret'),
            'whatsapp_rate_limit': self._get_int_param('whatsapp.rate_limit', 10),
            'whatsapp_debug_mode': self._get_bool_param('whatsapp.debug_mode', False),
        })
        
        return res
    
    def set_values(self):
        super(ResConfigSettings, self).set_values()
        
        # Set WhatsApp configuration values
        ICPSudo = self.env['ir.config_parameter'].sudo()
        
        ICPSudo.set_param('whatsapp.enabled', self.whatsapp_enabled)
        ICPSudo.set_param('whatsapp.default_account_id', self.whatsapp_default_account_id.id if self.whatsapp_default_account_id else False)
        ICPSudo.set_param('whatsapp.server_url', self.whatsapp_server_url)
        ICPSudo.set_param('whatsapp.server_token', self.whatsapp_server_token)
        ICPSudo.set_param('whatsapp.auto_reply_enabled', self.whatsapp_auto_reply_enabled)
        ICPSudo.set_param('whatsapp.auto_reply_message', self.whatsapp_auto_reply_message)
        ICPSudo.set_param('whatsapp.create_lead_from_message', self.whatsapp_create_lead_from_message)
        ICPSudo.set_param('whatsapp.lead_source_id', self.whatsapp_lead_source_id.id if self.whatsapp_lead_source_id else False)
        ICPSudo.set_param('whatsapp.notification_enabled', self.whatsapp_notification_enabled)
        ICPSudo.set_param('whatsapp.notification_sound', self.whatsapp_notification_sound)
        ICPSudo.set_param('whatsapp.message_retention_days', self.whatsapp_message_retention_days)
        ICPSudo.set_param('whatsapp.max_file_size', self.whatsapp_max_file_size)
        ICPSudo.set_param('whatsapp.webhook_enabled', self.whatsapp_webhook_enabled)
        ICPSudo.set_param('whatsapp.webhook_secret', self.whatsapp_webhook_secret)
        ICPSudo.set_param('whatsapp.rate_limit', self.whatsapp_rate_limit)
        ICPSudo.set_param('whatsapp.debug_mode', self.whatsapp_debug_mode)
