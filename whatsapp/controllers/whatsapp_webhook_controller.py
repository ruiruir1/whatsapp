# -*- coding: utf-8 -*-

from odoo import http, fields, _
from odoo.exceptions import AccessError, UserError
from odoo.http import request
import json
import logging
import hmac
import hashlib
import base64

_logger = logging.getLogger(__name__)


class WhatsAppWebhookController(http.Controller):
    
    @http.route('/whatsapp/webhook/<int:account_id>', type='json', auth='public', methods=['POST'], csrf=False)
    def whatsapp_webhook(self, account_id, **kwargs):
        """Handle WhatsApp webhook events"""
        try:
            # Get account
            account = request.env['whatsapp.account'].sudo().browse(account_id)
            if not account.exists():
                _logger.error(f'Account {account_id} not found')
                return {'error': 'Account not found'}
            
            # Verify webhook signature if configured
            if account.webhook_secret:
                if not self._verify_webhook_signature(account.webhook_secret, request.httprequest.data):
                    _logger.error('Invalid webhook signature')
                    return {'error': 'Invalid signature'}
            
            # Get webhook data
            webhook_data = request.jsonrequest
            event_type = webhook_data.get('event')
            
            _logger.info(f'Received webhook event: {event_type} for account {account.name}')
            
            # Process different event types
            if event_type == 'message':
                self._process_message_event(account, webhook_data)
            elif event_type == 'status':
                self._process_status_event(account, webhook_data)
            elif event_type == 'qr':
                self._process_qr_event(account, webhook_data)
            elif event_type == 'ready':
                self._process_ready_event(account, webhook_data)
            elif event_type == 'disconnected':
                self._process_disconnected_event(account, webhook_data)
            elif event_type == 'group_join':
                self._process_group_join_event(account, webhook_data)
            elif event_type == 'group_leave':
                self._process_group_leave_event(account, webhook_data)
            else:
                _logger.warning(f'Unknown event type: {event_type}')
            
            return {'success': True}
            
        except Exception as e:
            _logger.error(f'Error processing webhook: {e}')
            return {'error': str(e)}
    
    def _verify_webhook_signature(self, secret, payload):
        """Verify webhook signature"""
        try:
            signature = request.httprequest.headers.get('X-Hub-Signature-256')
            if not signature:
                return False
            
            expected_signature = hmac.new(
                secret.encode('utf-8'),
                payload,
                hashlib.sha256
            ).hexdigest()
            
            return hmac.compare_digest(signature, f'sha256={expected_signature}')
            
        except Exception as e:
            _logger.error(f'Error verifying signature: {e}')
            return False
    
    def _process_message_event(self, account, webhook_data):
        """Process message event"""
        try:
            message_data = webhook_data.get('data', {})
            
            # Create message record
            message_vals = {
                'account_id': account.id,
                'wa_message_id': message_data.get('id'),
                'message': message_data.get('body', ''),
                'message_type': message_data.get('type', 'text'),
                'direction': 'incoming',
                'from_number': message_data.get('from', '').replace('@c.us', ''),
                'from_name': message_data.get('notifyName') or message_data.get('pushname'),
                'to_number': message_data.get('to', '').replace('@c.us', ''),
                'timestamp': fields.Datetime.now(),
                'status': 'delivered',
                'raw_data': json.dumps(webhook_data),
            }
            
            # Handle group messages
            if message_data.get('isGroupMsg'):
                group_id = message_data.get('chatId', '').replace('@g.us', '')
                group = request.env['whatsapp.group'].sudo().search([
                    ('account_id', '=', account.id),
                    ('group_id', '=', group_id)
                ], limit=1)
                
                if group:
                    message_vals['group_id'] = group.id
            
            # Handle media messages
            if message_data.get('type') in ['image', 'video', 'audio', 'document']:
                message_vals.update({
                    'media_url': message_data.get('body'),
                    'media_type': message_data.get('mimetype'),
                    'media_size': message_data.get('size'),
                })
            
            # Handle location messages
            if message_data.get('type') == 'location':
                message_vals.update({
                    'latitude': message_data.get('lat'),
                    'longitude': message_data.get('lng'),
                    'location_name': message_data.get('loc'),
                })
            
            # Handle quoted messages (replies)
            if message_data.get('quotedMsg'):
                quoted_msg_id = message_data.get('quotedMsg', {}).get('id')
                if quoted_msg_id:
                    quoted_message = request.env['whatsapp.message'].sudo().search([
                        ('wa_message_id', '=', quoted_msg_id)
                    ], limit=1)
                    if quoted_message:
                        message_vals['reply_to_message_id'] = quoted_message.id
            
            # Create message
            message = request.env['whatsapp.message'].sudo().create(message_vals)
            
            # Update account statistics
            account.sudo().write({
                'messages_received': account.messages_received + 1,
                'last_seen': fields.Datetime.now(),
            })
            
            _logger.info(f'Created message {message.id} from webhook')
            
        except Exception as e:
            _logger.error(f'Error processing message event: {e}')
    
    def _process_status_event(self, account, webhook_data):
        """Process status event"""
        try:
            status_data = webhook_data.get('data', {})
            status = status_data.get('status')
            
            # Update account status
            status_mapping = {
                'disconnected': 'disconnected',
                'connecting': 'connecting',
                'qr': 'qr_code',
                'authenticated': 'authenticated',
                'ready': 'ready',
                'error': 'error',
            }
            
            new_status = status_mapping.get(status, 'error')
            account.sudo().write({
                'status': new_status,
                'last_seen': fields.Datetime.now(),
            })
            
            _logger.info(f'Updated account {account.name} status to {new_status}')
            
        except Exception as e:
            _logger.error(f'Error processing status event: {e}')
    
    def _process_qr_event(self, account, webhook_data):
        """Process QR code event"""
        try:
            qr_data = webhook_data.get('data', {})
            
            # Update account with QR code
            account.sudo().write({
                'status': 'qr_code',
                'qr_code': qr_data.get('qr'),
                'qr_code_image': qr_data.get('qr_image'),
                'last_seen': fields.Datetime.now(),
            })
            
            _logger.info(f'Updated QR code for account {account.name}')
            
        except Exception as e:
            _logger.error(f'Error processing QR event: {e}')
    
    def _process_ready_event(self, account, webhook_data):
        """Process ready event"""
        try:
            # Update account status
            account.sudo().write({
                'status': 'ready',
                'last_seen': fields.Datetime.now(),
            })
            
            # Sync contacts
            try:
                account.sudo().sync_contacts()
            except Exception as e:
                _logger.error(f'Error syncing contacts after ready: {e}')
            
            _logger.info(f'Account {account.name} is ready')
            
        except Exception as e:
            _logger.error(f'Error processing ready event: {e}')
    
    def _process_disconnected_event(self, account, webhook_data):
        """Process disconnected event"""
        try:
            # Update account status
            account.sudo().write({
                'status': 'disconnected',
                'qr_code': False,
                'qr_code_image': False,
                'last_seen': fields.Datetime.now(),
            })
            
            _logger.info(f'Account {account.name} disconnected')
            
        except Exception as e:
            _logger.error(f'Error processing disconnected event: {e}')
    
    def _process_group_join_event(self, account, webhook_data):
        """Process group join event"""
        try:
            group_data = webhook_data.get('data', {})
            group_id = group_data.get('id', '').replace('@g.us', '')
            
            # Create or update group
            group = request.env['whatsapp.group'].sudo().search([
                ('account_id', '=', account.id),
                ('group_id', '=', group_id)
            ], limit=1)
            
            group_vals = {
                'account_id': account.id,
                'group_id': group_id,
                'name': group_data.get('name', 'Unknown Group'),
                'description': group_data.get('desc', ''),
                'is_member': True,
                'member_count': len(group_data.get('participants', [])),
            }
            
            if group:
                group.write(group_vals)
            else:
                group = request.env['whatsapp.group'].sudo().create(group_vals)
            
            _logger.info(f'Joined group {group.name}')
            
        except Exception as e:
            _logger.error(f'Error processing group join event: {e}')
    
    def _process_group_leave_event(self, account, webhook_data):
        """Process group leave event"""
        try:
            group_data = webhook_data.get('data', {})
            group_id = group_data.get('id', '').replace('@g.us', '')
            
            # Update group
            group = request.env['whatsapp.group'].sudo().search([
                ('account_id', '=', account.id),
                ('group_id', '=', group_id)
            ], limit=1)
            
            if group:
                group.write({
                    'is_member': False,
                    'left_date': fields.Datetime.now(),
                })
            
            _logger.info(f'Left group {group.name if group else group_id}')
            
        except Exception as e:
            _logger.error(f'Error processing group leave event: {e}')


class WhatsAppAPIController(http.Controller):
    
    @http.route('/whatsapp/api/status/<int:account_id>', type='json', auth='user', methods=['GET'])
    def get_account_status(self, account_id):
        """Get account status"""
        try:
            account = request.env['whatsapp.account'].browse(account_id)
            if not account.exists():
                return {'error': 'Account not found'}
            
            return {
                'success': True,
                'status': account.status,
                'name': account.name,
                'phone_number': account.phone_number,
                'last_seen': account.last_seen.isoformat() if account.last_seen else None,
                'messages_sent': account.messages_sent,
                'messages_received': account.messages_received,
                'contacts_count': account.contacts_count,
                'groups_count': account.groups_count,
            }
            
        except Exception as e:
            _logger.error(f'Error getting account status: {e}')
            return {'error': str(e)}
    
    @http.route('/whatsapp/api/send_message', type='json', auth='user', methods=['POST'])
    def send_message(self, account_id, to_number, message, message_type='text', **kwargs):
        """Send message via API"""
        try:
            account = request.env['whatsapp.account'].browse(account_id)
            if not account.exists():
                return {'error': 'Account not found'}
            
            # Send message
            whatsapp_message = account.send_message(
                to=to_number,
                message=message,
                message_type=message_type,
                attachment=kwargs.get('attachment')
            )
            
            return {
                'success': True,
                'message_id': whatsapp_message.id,
                'wa_message_id': whatsapp_message.wa_message_id,
                'status': whatsapp_message.status,
            }
            
        except Exception as e:
            _logger.error(f'Error sending message: {e}')
            return {'error': str(e)}
    
    @http.route('/whatsapp/api/contacts/<int:account_id>', type='json', auth='user', methods=['GET'])
    def get_contacts(self, account_id):
        """Get contacts for account"""
        try:
            account = request.env['whatsapp.account'].browse(account_id)
            if not account.exists():
                return {'error': 'Account not found'}
            
            contacts = account.contact_ids.search([
                ('account_id', '=', account_id),
                ('status', '=', 'active')
            ])
            
            contacts_data = []
            for contact in contacts:
                contacts_data.append({
                    'id': contact.id,
                    'name': contact.name,
                    'phone_number': contact.phone_number,
                    'profile_pic_url': contact.profile_pic_url,
                    'is_business': contact.is_business,
                    'last_seen': contact.last_seen.isoformat() if contact.last_seen else None,
                    'message_count': contact.message_count,
                })
            
            return {
                'success': True,
                'contacts': contacts_data,
            }
            
        except Exception as e:
            _logger.error(f'Error getting contacts: {e}')
            return {'error': str(e)}
    
    @http.route('/whatsapp/api/messages/<int:account_id>', type='json', auth='user', methods=['GET'])
    def get_messages(self, account_id, contact_id=None, limit=50, offset=0):
        """Get messages for account"""
        try:
            account = request.env['whatsapp.account'].browse(account_id)
            if not account.exists():
                return {'error': 'Account not found'}
            
            domain = [('account_id', '=', account_id)]
            if contact_id:
                domain.append(('contact_id', '=', contact_id))
            
            messages = request.env['whatsapp.message'].search(
                domain, 
                order='timestamp desc', 
                limit=limit, 
                offset=offset
            )
            
            messages_data = []
            for message in messages:
                messages_data.append({
                    'id': message.id,
                    'message': message.message,
                    'message_type': message.message_type,
                    'direction': message.direction,
                    'status': message.status,
                    'from_number': message.from_number,
                    'from_name': message.from_name,
                    'to_number': message.to_number,
                    'timestamp': message.timestamp.isoformat(),
                    'contact_id': message.contact_id.id if message.contact_id else None,
                    'contact_name': message.contact_id.name if message.contact_id else None,
                })
            
            return {
                'success': True,
                'messages': messages_data,
            }
            
        except Exception as e:
            _logger.error(f'Error getting messages: {e}')
            return {'error': str(e)}
    
    @http.route('/whatsapp/api/qr_code/<int:account_id>', type='json', auth='user', methods=['GET'])
    def get_qr_code(self, account_id):
        """Get QR code for account"""
        try:
            account = request.env['whatsapp.account'].browse(account_id)
            if not account.exists():
                return {'error': 'Account not found'}
            
            if account.status != 'qr_code':
                return {'error': 'QR code not available'}
            
            return {
                'success': True,
                'qr_code': account.qr_code,
                'qr_code_image': account.qr_code_image,
            }
            
        except Exception as e:
            _logger.error(f'Error getting QR code: {e}')
            return {'error': str(e)}


class WhatsAppPublicController(http.Controller):
    
    @http.route('/whatsapp/public/send', type='json', auth='public', methods=['POST'], csrf=False)
    def public_send_message(self, **kwargs):
        """Public endpoint for sending messages (for integrations)"""
        try:
            # Get API key from headers
            api_key = request.httprequest.headers.get('Authorization', '').replace('Bearer ', '')
            
            if not api_key:
                return {'error': 'API key required'}
            
            # Find account by API key
            account = request.env['whatsapp.account'].sudo().search([
                ('api_key', '=', api_key)
            ], limit=1)
            
            if not account:
                return {'error': 'Invalid API key'}
            
            # Get message data
            data = request.jsonrequest
            to_number = data.get('to')
            message = data.get('message')
            message_type = data.get('type', 'text')
            
            if not to_number or not message:
                return {'error': 'Missing required fields'}
            
            # Send message
            whatsapp_message = account.send_message(
                to=to_number,
                message=message,
                message_type=message_type
            )
            
            return {
                'success': True,
                'message_id': whatsapp_message.id,
                'status': whatsapp_message.status,
            }
            
        except Exception as e:
            _logger.error(f'Error in public send message: {e}')
            return {'error': str(e)}