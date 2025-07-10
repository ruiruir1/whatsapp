# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import json
import logging
import base64
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)


class WhatsAppMessage(models.Model):
    _name = 'whatsapp.message'
    _description = 'WhatsApp Message'
    _order = 'timestamp desc'
    _rec_name = 'message'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # Message identification
    message_id = fields.Char('Message ID', required=True, index=True)
    wa_message_id = fields.Char('WhatsApp Message ID', help='Original WhatsApp message ID')
    
    # Account and contact
    account_id = fields.Many2one('whatsapp.account', 'WhatsApp Account', required=True, ondelete='cascade')
    contact_id = fields.Many2one('whatsapp.contact', 'Contact', ondelete='cascade')
    group_id = fields.Many2one('whatsapp.group', 'Group', ondelete='cascade')
    
    # Message details
    message = fields.Text('Message Content', required=True)
    message_type = fields.Selection([
        ('text', 'Text'),
        ('image', 'Image'),
        ('video', 'Video'),
        ('audio', 'Audio'),
        ('voice', 'Voice Note'),
        ('document', 'Document'),
        ('sticker', 'Sticker'),
        ('location', 'Location'),
        ('contact', 'Contact'),
        ('poll', 'Poll'),
        ('reaction', 'Reaction'),
        ('system', 'System Message'),
    ], string='Message Type', default='text', required=True)
    
    # Direction and status
    direction = fields.Selection([
        ('incoming', 'Incoming'),
        ('outgoing', 'Outgoing'),
    ], string='Direction', required=True)
    
    status = fields.Selection([
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('read', 'Read'),
        ('failed', 'Failed'),
        ('error', 'Error'),
    ], string='Status', default='pending', tracking=True)
    
    # Phone numbers
    from_number = fields.Char('From Number', index=True)
    to_number = fields.Char('To Number', index=True)
    from_name = fields.Char('From Name')
    to_name = fields.Char('To Name')
    
    # Timestamps
    timestamp = fields.Datetime('Timestamp', default=fields.Datetime.now, required=True)
    sent_date = fields.Datetime('Sent Date')
    delivered_date = fields.Datetime('Delivered Date')
    read_date = fields.Datetime('Read Date')
    
    # Attachments and media
    attachment_id = fields.Many2one('ir.attachment', 'Attachment', ondelete='cascade')
    media_url = fields.Char('Media URL')
    media_type = fields.Char('Media Type')
    media_size = fields.Integer('Media Size (bytes)')
    thumbnail = fields.Binary('Thumbnail')
    
    # Location data
    latitude = fields.Float('Latitude')
    longitude = fields.Float('Longitude')
    location_name = fields.Char('Location Name')
    location_address = fields.Text('Location Address')
    
    # Contact data (for contact messages)
    contact_name = fields.Char('Contact Name')
    contact_phone = fields.Char('Contact Phone')
    contact_vcard = fields.Text('Contact VCard')
    
    # Message context
    reply_to_message_id = fields.Many2one('whatsapp.message', 'Reply To Message', ondelete='cascade')
    forward_from_message_id = fields.Many2one('whatsapp.message', 'Forward From Message', ondelete='cascade')
    is_forwarded = fields.Boolean('Is Forwarded', default=False)
    forward_count = fields.Integer('Forward Count', default=0)
    
    # System message details
    system_message_type = fields.Selection([
        ('user_joined', 'User Joined'),
        ('user_left', 'User Left'),
        ('user_added', 'User Added'),
        ('user_removed', 'User Removed'),
        ('group_created', 'Group Created'),
        ('group_subject_changed', 'Group Subject Changed'),
        ('group_description_changed', 'Group Description Changed'),
        ('group_picture_changed', 'Group Picture Changed'),
        ('group_settings_changed', 'Group Settings Changed'),
    ], string='System Message Type')
    
    # Reaction data
    reaction_emoji = fields.Char('Reaction Emoji')
    reaction_to_message_id = fields.Many2one('whatsapp.message', 'Reaction To Message', ondelete='cascade')
    
    # Business integration
    partner_id = fields.Many2one('res.partner', 'Related Partner', ondelete='set null')
    lead_id = fields.Many2one('crm.lead', 'Related Lead', ondelete='set null')
    sale_order_id = fields.Many2one('sale.order', 'Related Sale Order', ondelete='set null')
    
    # Auto-reply and template
    template_id = fields.Many2one('whatsapp.template', 'Template Used', ondelete='set null')
    is_auto_reply = fields.Boolean('Is Auto Reply', default=False)
    
    # Delivery report
    delivery_report = fields.Text('Delivery Report')
    error_message = fields.Text('Error Message')
    
    # Metadata
    raw_data = fields.Text('Raw Data', help='Original message data from WhatsApp API')
    company_id = fields.Many2one('res.company', 'Company', related='account_id.company_id', store=True)
    
    _sql_constraints = [
        ('unique_message_id', 'unique(message_id)', 'Message ID must be unique!'),
    ]

    @api.model
    def create(self, vals):
        # Auto-generate message_id if not provided
        if not vals.get('message_id'):
            vals['message_id'] = self._generate_message_id()
        
        # Set contact and partner based on phone number
        if vals.get('from_number') and vals.get('direction') == 'incoming':
            contact = self._get_or_create_contact(vals['from_number'], vals.get('from_name'))
            vals['contact_id'] = contact.id
            if contact.partner_id:
                vals['partner_id'] = contact.partner_id.id
        
        elif vals.get('to_number') and vals.get('direction') == 'outgoing':
            contact = self._get_or_create_contact(vals['to_number'], vals.get('to_name'))
            vals['contact_id'] = contact.id
            if contact.partner_id:
                vals['partner_id'] = contact.partner_id.id
        
        message = super(WhatsAppMessage, self).create(vals)
        
        # Process message after creation
        message._process_message()
        
        return message

    def _generate_message_id(self):
        """Generate unique message ID"""
        import uuid
        return str(uuid.uuid4())

    def _get_or_create_contact(self, phone_number, name=None):
        """Get or create WhatsApp contact"""
        account_id = self.env.context.get('default_account_id') or self.account_id.id
        
        contact = self.env['whatsapp.contact'].search([
            ('account_id', '=', account_id),
            ('phone_number', '=', phone_number)
        ], limit=1)
        
        if not contact:
            contact_vals = {
                'account_id': account_id,
                'name': name or phone_number,
                'phone_number': phone_number,
            }
            contact = self.env['whatsapp.contact'].create(contact_vals)
        
        return contact

    def _process_message(self):
        """Process message after creation"""
        self.ensure_one()
        
        # Handle auto-reply for incoming messages
        if self.direction == 'incoming' and self.account_id.auto_reply and self.message_type == 'text':
            self._handle_auto_reply()
        
        # Create lead if configured
        if self.direction == 'incoming' and self.account_id.create_lead_from_message:
            self._create_lead_from_message()
        
        # Update contact last seen
        if self.contact_id:
            self.contact_id.last_seen = self.timestamp
        
        # Send notification
        self._send_notification()

    def _handle_auto_reply(self):
        """Handle auto-reply for incoming messages"""
        self.ensure_one()
        
        if not self.account_id.auto_reply_message:
            return
        
        # Check if auto-reply was already sent recently
        recent_auto_reply = self.search([
            ('account_id', '=', self.account_id.id),
            ('to_number', '=', self.from_number),
            ('direction', '=', 'outgoing'),
            ('is_auto_reply', '=', True),
            ('timestamp', '>', fields.Datetime.now() - timedelta(hours=1))
        ], limit=1)
        
        if recent_auto_reply:
            return
        
        # Send auto-reply
        try:
            self.account_id.send_message(
                to=self.from_number,
                message=self.account_id.auto_reply_message,
                message_type='text'
            )
        except Exception as e:
            _logger.error(f'Error sending auto-reply: {e}')

    def _create_lead_from_message(self):
        """Create CRM lead from message"""
        self.ensure_one()
        
        if self.lead_id:
            return
        
        # Find existing lead for this contact
        existing_lead = self.env['crm.lead'].search([
            ('phone', '=', self.from_number),
            ('stage_id.is_won', '=', False),
        ], limit=1)
        
        if existing_lead:
            self.lead_id = existing_lead.id
            return
        
        # Create new lead
        lead_vals = {
            'name': f'WhatsApp Lead from {self.from_name or self.from_number}',
            'phone': self.from_number,
            'description': f'WhatsApp message: {self.message}',
            'source_id': self.env.ref('whatsapp.lead_source_whatsapp').id,
            'user_id': self.account_id.user_id.id,
            'team_id': self.account_id.user_id.team_id.id,
        }
        
        if self.partner_id:
            lead_vals['partner_id'] = self.partner_id.id
        
        lead = self.env['crm.lead'].create(lead_vals)
        self.lead_id = lead.id

    def _send_notification(self):
        """Send notification for new message"""
        self.ensure_one()
        
        if self.direction == 'incoming':
            # Use Odoo 18 message_notify for better integration
            try:
                self.message_notify(
                    partner_ids=[self.account_id.user_id.partner_id.id],
                    subject=f'WhatsApp Message from {self.from_name or self.from_number}',
                    body=f'<p>{self.message}</p>',
                    subtype_xmlid='mail.mt_comment'
                )
            except Exception as e:
                _logger.error(f'Error sending notification via message_notify: {e}')
                # Fallback to bus notification
                self.env['bus.bus']._sendone(
                    self.account_id.user_id.partner_id,
                    'mail.message/inbox',
                    {
                        'type': 'info',
                        'title': 'WhatsApp Message',
                        'message': f'New WhatsApp message from {self.from_name or self.from_number}',
                    }
                )
            
            # Send bus notification for WhatsApp module
            self.env['bus.bus']._sendone(
                self.account_id.user_id.partner_id,
                'whatsapp.message/new',
                {
                    'type': 'whatsapp_message',
                    'message_id': self.id,
                    'account_id': self.account_id.id,
                    'from_number': self.from_number,
                    'from_name': self.from_name,
                    'message': self.message,
                    'message_type': self.message_type,
                }
            )

    def action_reply(self):
        """Open reply dialog"""
        self.ensure_one()
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Reply to Message',
            'res_model': 'whatsapp.send.message',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_account_id': self.account_id.id,
                'default_to_number': self.from_number,
                'default_reply_to_message_id': self.id,
            }
        }

    def action_forward(self):
        """Open forward dialog"""
        self.ensure_one()
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Forward Message',
            'res_model': 'whatsapp.send.message',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_account_id': self.account_id.id,
                'default_message': self.message,
                'default_forward_from_message_id': self.id,
            }
        }

    def action_create_lead(self):
        """Create lead from message"""
        self.ensure_one()
        
        if self.lead_id:
            return self.lead_id.get_formview_action()
        
        lead_vals = {
            'name': f'WhatsApp Lead from {self.from_name or self.from_number}',
            'phone': self.from_number,
            'description': f'WhatsApp message: {self.message}',
            'source_id': self.env.ref('whatsapp.lead_source_whatsapp').id,
            'user_id': self.account_id.user_id.id,
        }
        
        if self.partner_id:
            lead_vals['partner_id'] = self.partner_id.id
        
        lead = self.env['crm.lead'].create(lead_vals)
        self.lead_id = lead.id
        
        return lead.get_formview_action()

    def action_create_partner(self):
        """Create partner from message"""
        self.ensure_one()
        
        if self.partner_id:
            return self.partner_id.get_formview_action()
        
        partner_vals = {
            'name': self.from_name or self.from_number,
            'phone': self.from_number,
            'is_company': False,
            'supplier_rank': 0,
            'customer_rank': 1,
        }
        
        partner = self.env['res.partner'].create(partner_vals)
        self.partner_id = partner.id
        
        # Update contact
        if self.contact_id:
            self.contact_id.partner_id = partner.id
        
        return partner.get_formview_action()

    def mark_as_read(self):
        """Mark message as read"""
        self.ensure_one()
        
        if self.status != 'read':
            self.status = 'read'
            self.read_date = fields.Datetime.now()
            
            # Send read receipt to WhatsApp
            try:
                self.account_id._send_read_receipt(self.wa_message_id)
            except Exception as e:
                _logger.error(f'Error sending read receipt: {e}')

    def download_attachment(self):
        """Download media attachment"""
        self.ensure_one()
        
        if not self.media_url:
            raise UserError(_('No media URL available'))
        
        try:
            # Download media from WhatsApp API
            import requests
            response = requests.get(self.media_url)
            
            if response.status_code == 200:
                # Create attachment
                attachment_vals = {
                    'name': f'WhatsApp_{self.message_type}_{self.id}',
                    'datas': base64.b64encode(response.content),
                    'res_model': 'whatsapp.message',
                    'res_id': self.id,
                    'mimetype': response.headers.get('content-type', 'application/octet-stream'),
                }
                
                attachment = self.env['ir.attachment'].create(attachment_vals)
                self.attachment_id = attachment.id
                
                return attachment.get_formview_action()
            else:
                raise UserError(_('Failed to download media'))
                
        except Exception as e:
            _logger.error(f'Error downloading attachment: {e}')
            raise UserError(_('Error downloading attachment: %s') % str(e))

    @api.model
    def process_webhook_message(self, webhook_data):
        """Process message from webhook"""
        try:
            # Parse webhook data
            message_data = webhook_data.get('message', {})
            account_id = webhook_data.get('account_id')
            
            if not account_id:
                _logger.error('No account_id in webhook data')
                return
            
            # Create message record
            message_vals = {
                'account_id': account_id,
                'wa_message_id': message_data.get('id'),
                'message': message_data.get('body', ''),
                'message_type': message_data.get('type', 'text'),
                'direction': 'incoming',
                'from_number': message_data.get('from', '').replace('@c.us', ''),
                'from_name': message_data.get('name'),
                'timestamp': fields.Datetime.now(),
                'raw_data': json.dumps(webhook_data),
            }
            
            # Handle different message types
            if message_data.get('type') == 'image':
                message_vals.update({
                    'media_url': message_data.get('media_url'),
                    'media_type': message_data.get('mime_type'),
                    'media_size': message_data.get('file_size'),
                })
            
            # Create message
            message = self.create(message_vals)
            
            return message
            
        except Exception as e:
            _logger.error(f'Error processing webhook message: {e}')
            return None