# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from odoo.tools import ustr
import json
import logging
import requests
import subprocess
import os
import time
import uuid
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)


class WhatsAppAccount(models.Model):
    _name = 'whatsapp.account'
    _description = 'WhatsApp Account'
    _order = 'name'
    _rec_name = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char('Account Name', required=True, tracking=True)
    phone_number = fields.Char('Phone Number', required=True, tracking=True)
    country_code = fields.Char('Country Code', default='+1', tracking=True)
    display_name = fields.Char('Display Name', tracking=True)
    about = fields.Text('About/Status', tracking=True)
    
    # Authentication
    status = fields.Selection([
        ('disconnected', 'Disconnected'),
        ('connecting', 'Connecting'),
        ('qr_code', 'QR Code Required'),
        ('authenticated', 'Authenticated'),
        ('ready', 'Ready'),
        ('error', 'Error'),
        ('maintenance', 'Maintenance'),
    ], string='Status', default='disconnected', tracking=True)
    
    qr_code = fields.Text('QR Code', help='QR code for authentication')
    qr_code_image = fields.Binary('QR Code Image', attachment=True)
    session_data = fields.Text('Session Data', help='Encrypted session data')
    last_seen = fields.Datetime('Last Seen', tracking=True)
    
    # Configuration
    active = fields.Boolean('Active', default=True, tracking=True)
    auto_reply = fields.Boolean('Auto Reply', default=False, tracking=True)
    auto_reply_message = fields.Text('Auto Reply Message')
    webhook_url = fields.Char('Webhook URL', tracking=True)
    webhook_secret = fields.Char('Webhook Secret')
    
    # API Settings
    api_endpoint = fields.Char('API Endpoint', default='http://localhost:3000')
    api_key = fields.Char('API Key')
    session_name = fields.Char('Session Name', compute='_compute_session_name', store=True)
    
    # Statistics
    messages_sent = fields.Integer('Messages Sent', default=0, tracking=True)
    messages_received = fields.Integer('Messages Received', default=0, tracking=True)
    contacts_count = fields.Integer('Contacts Count', compute='_compute_contacts_count', store=True)
    groups_count = fields.Integer('Groups Count', compute='_compute_groups_count', store=True)
    
    # Business Integration
    company_id = fields.Many2one('res.company', 'Company', default=lambda self: self.env.company)
    user_id = fields.Many2one('res.users', 'Responsible User', default=lambda self: self.env.user, tracking=True)
    
    # Relations
    message_ids = fields.One2many('whatsapp.message', 'account_id', 'Messages')
    contact_ids = fields.One2many('whatsapp.contact', 'account_id', 'Contacts')
    group_ids = fields.One2many('whatsapp.group', 'account_id', 'Groups')
    template_ids = fields.One2many('whatsapp.template', 'account_id', 'Templates')
    # webhook_ids = fields.One2many('whatsapp.webhook', 'account_id', 'Webhooks')  # Commented out - model doesn't exist
    
    # Node.js Process
    process_id = fields.Integer('Process ID', help='Node.js process ID')
    process_status = fields.Selection([
        ('stopped', 'Stopped'),
        ('starting', 'Starting'),
        ('running', 'Running'),
        ('stopping', 'Stopping'),
        ('error', 'Error'),
    ], string='Process Status', default='stopped')
    
    _sql_constraints = [
        ('unique_phone_number', 'unique(phone_number)', 'Phone number must be unique!'),
        ('unique_session_name', 'unique(session_name)', 'Session name must be unique!'),
    ]

    @api.depends('name', 'phone_number')
    def _compute_session_name(self):
        for record in self:
            if record.phone_number:
                phone_clean = record.phone_number.replace('+', '').replace(' ', '_')
                record.session_name = f"whatsapp_session_{phone_clean}"
            else:
                record.session_name = f"whatsapp_session_{record.id or 'new'}"

    @api.depends('contact_ids')
    def _compute_contacts_count(self):
        for record in self:
            record.contacts_count = len(record.contact_ids)

    @api.depends('group_ids')
    def _compute_groups_count(self):
        for record in self:
            record.groups_count = len(record.group_ids)

    @api.model
    def create(self, vals):
        # Generate session name if not provided
        if not vals.get('session_name'):
            phone = vals.get('phone_number', '')
            if phone:
                phone_clean = phone.replace('+', '').replace(' ', '_')
                vals['session_name'] = f"whatsapp_session_{phone_clean}_{uuid.uuid4().hex[:8]}"
            else:
                vals['session_name'] = f"whatsapp_session_new_{uuid.uuid4().hex[:8]}"
        
        account = super(WhatsAppAccount, self).create(vals)
        account._setup_webhook()
        return account

    def write(self, vals):
        result = super(WhatsAppAccount, self).write(vals)
        if 'webhook_url' in vals or 'webhook_secret' in vals:
            self._setup_webhook()
        return result

    def _setup_webhook(self):
        """Setup webhook for this account"""
        # TODO: Implement webhook setup when whatsapp.webhook model is available
        pass

    def action_connect(self):
        """Connect to WhatsApp Web"""
        self.ensure_one()
        if self.status in ['connecting', 'authenticated', 'ready']:
            raise UserError(_('Account is already connected or connecting.'))
        
        self.status = 'connecting'
        self._start_whatsapp_process()
        return True

    def action_disconnect(self):
        """Disconnect from WhatsApp Web"""
        self.ensure_one()
        self._stop_whatsapp_process()
        self.status = 'disconnected'
        self.qr_code = False
        self.qr_code_image = False
        return True

    def action_restart(self):
        """Restart WhatsApp connection"""
        self.ensure_one()
        self.action_disconnect()
        time.sleep(2)
        self.action_connect()
        return True

    def action_get_qr_code(self):
        """Get QR code for authentication"""
        self.ensure_one()
        if self.status != 'qr_code':
            raise UserError(_('QR code is only available when status is "QR Code Required".'))
        
        # Call Node.js API to get QR code
        try:
            response = requests.get(f'{self.api_endpoint}/qr/{self.session_name}')
            if response.status_code == 200:
                data = response.json()
                self.qr_code = data.get('qr_code')
                self.qr_code_image = data.get('qr_image')
                return {
                    'type': 'ir.actions.client',
                    'tag': 'whatsapp_qr_code_dialog',
                    'params': {
                        'qr_code': self.qr_code,
                        'qr_image': self.qr_code_image,
                    }
                }
            else:
                raise UserError(_('Failed to get QR code: %s') % response.text)
        except Exception as e:
            _logger.error(f'Error getting QR code: {e}')
            raise UserError(_('Error getting QR code: %s') % str(e))

    def _start_whatsapp_process(self):
        """Start Node.js WhatsApp process"""
        self.ensure_one()
        
        # Check if process is already running
        if self.process_id and self._is_process_running():
            _logger.info(f'WhatsApp process already running for {self.name}')
            return
        
        try:
            # Node.js script path
            script_path = os.path.join(os.path.dirname(__file__), '..', 'node_modules', 'whatsapp_server.js')
            
            # Start Node.js process
            cmd = [
                'node', script_path,
                '--session', self.session_name,
                '--webhook', self.webhook_url or '',
                '--api-key', self.api_key or '',
                '--phone', self.phone_number,
            ]
            
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.process_id = process.pid
            self.process_status = 'starting'
            
            _logger.info(f'Started WhatsApp process {process.pid} for {self.name}')
            
        except Exception as e:
            _logger.error(f'Error starting WhatsApp process: {e}')
            self.process_status = 'error'
            self.status = 'error'
            raise UserError(_('Error starting WhatsApp process: %s') % str(e))

    def _stop_whatsapp_process(self):
        """Stop Node.js WhatsApp process"""
        self.ensure_one()
        
        if not self.process_id:
            return
        
        try:
            # Kill the process
            import signal
            os.kill(self.process_id, signal.SIGTERM)
            
            # Wait for process to stop
            time.sleep(2)
            
            # Force kill if still running
            if self._is_process_running():
                os.kill(self.process_id, signal.SIGKILL)
            
            self.process_id = 0
            self.process_status = 'stopped'
            
            _logger.info(f'Stopped WhatsApp process for {self.name}')
            
        except Exception as e:
            _logger.error(f'Error stopping WhatsApp process: {e}')
            self.process_status = 'error'

    def _is_process_running(self):
        """Check if Node.js process is running"""
        self.ensure_one()
        
        if not self.process_id:
            return False
        
        try:
            # Check if process exists
            os.kill(self.process_id, 0)
            return True
        except OSError:
            return False

    def send_message(self, to, message, message_type='text', attachment=None):
        """Send message via WhatsApp"""
        self.ensure_one()
        
        if self.status != 'ready':
            raise UserError(_('WhatsApp account is not ready to send messages.'))
        
        try:
            # Prepare message data
            message_data = {
                'to': to,
                'message': message,
                'type': message_type,
                'session': self.session_name,
            }
            
            if attachment:
                message_data['attachment'] = attachment
            
            # Send via API
            response = requests.post(
                f'{self.api_endpoint}/send',
                json=message_data,
                headers={'Authorization': f'Bearer {self.api_key}'}
            )
            
            if response.status_code == 200:
                result = response.json()
                
                # Create message record
                message_vals = {
                    'account_id': self.id,
                    'message_id': result.get('message_id'),
                    'to_number': to,
                    'message': message,
                    'message_type': message_type,
                    'direction': 'outgoing',
                    'status': 'sent',
                    'sent_date': fields.Datetime.now(),
                }
                
                if attachment:
                    message_vals['attachment_id'] = attachment.id
                
                whatsapp_message = self.env['whatsapp.message'].create(message_vals)
                
                # Update statistics
                self.messages_sent += 1
                
                return whatsapp_message
            else:
                raise UserError(_('Failed to send message: %s') % response.text)
                
        except Exception as e:
            _logger.error(f'Error sending message: {e}')
            raise UserError(_('Error sending message: %s') % str(e))

    def sync_contacts(self):
        """Sync contacts from WhatsApp"""
        self.ensure_one()
        
        if self.status != 'ready':
            raise UserError(_('WhatsApp account is not ready.'))
        
        try:
            response = requests.get(
                f'{self.api_endpoint}/contacts/{self.session_name}',
                headers={'Authorization': f'Bearer {self.api_key}'}
            )
            
            if response.status_code == 200:
                contacts_data = response.json()
                
                for contact_data in contacts_data.get('contacts', []):
                    self._sync_contact(contact_data)
                
                return True
            else:
                raise UserError(_('Failed to sync contacts: %s') % response.text)
                
        except Exception as e:
            _logger.error(f'Error syncing contacts: {e}')
            raise UserError(_('Error syncing contacts: %s') % str(e))

    def _sync_contact(self, contact_data):
        """Sync individual contact"""
        self.ensure_one()
        
        phone_number = contact_data.get('id', '').replace('@c.us', '')
        name = contact_data.get('name') or contact_data.get('pushname') or phone_number
        
        # Check if contact already exists
        existing_contact = self.env['whatsapp.contact'].search([
            ('account_id', '=', self.id),
            ('phone_number', '=', phone_number)
        ], limit=1)
        
        contact_vals = {
            'account_id': self.id,
            'name': name,
            'phone_number': phone_number,
            'profile_pic_url': contact_data.get('profilePicUrl'),
            'is_business': contact_data.get('isBusiness', False),
            'is_group': contact_data.get('isGroup', False),
            'last_seen': fields.Datetime.now(),
        }
        
        if existing_contact:
            existing_contact.write(contact_vals)
        else:
            self.env['whatsapp.contact'].create(contact_vals)

    def action_open_dashboard(self):
        """Open WhatsApp dashboard"""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'whatsapp_dashboard',
            'params': {
                'account_id': self.id,
            }
        }

    def action_open_chat(self):
        """Open chat interface"""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'whatsapp_chat',
            'params': {
                'account_id': self.id,
            }
        }

    @api.model
    def cron_check_account_status(self):
        """Cron job to check account status"""
        accounts = self.search([('active', '=', True)])
        for account in accounts:
            try:
                account._check_account_status()
            except Exception as e:
                _logger.error(f'Error checking account status for {account.name}: {e}')

    def _check_account_status(self):
        """Check account status via API"""
        self.ensure_one()
        
        try:
            response = requests.get(
                f'{self.api_endpoint}/status/{self.session_name}',
                headers={'Authorization': f'Bearer {self.api_key}'},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                status = data.get('status', 'disconnected')
                
                # Map API status to our status
                status_mapping = {
                    'disconnected': 'disconnected',
                    'connecting': 'connecting',
                    'qr': 'qr_code',
                    'authenticated': 'authenticated',
                    'ready': 'ready',
                    'error': 'error',
                }
                
                new_status = status_mapping.get(status, 'error')
                
                if new_status != self.status:
                    self.status = new_status
                    self.last_seen = fields.Datetime.now()
                    
                    # Handle QR code
                    if new_status == 'qr_code':
                        self.qr_code = data.get('qr_code')
                        self.qr_code_image = data.get('qr_image')
                
                # Update process status
                if self._is_process_running():
                    self.process_status = 'running'
                else:
                    self.process_status = 'stopped'
                    
        except Exception as e:
            _logger.error(f'Error checking account status: {e}')
            self.status = 'error'
            self.process_status = 'error'