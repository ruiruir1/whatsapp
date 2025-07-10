# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import logging

_logger = logging.getLogger(__name__)


class WhatsAppContact(models.Model):
    _name = 'whatsapp.contact'
    _description = 'WhatsApp Contact'
    _order = 'name'
    _rec_name = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # Basic info
    name = fields.Char('Name', required=True, tracking=True)
    phone_number = fields.Char('Phone Number', required=True, index=True, tracking=True)
    display_name = fields.Char('Display Name', tracking=True)
    
    # WhatsApp specific
    wa_id = fields.Char('WhatsApp ID', help='WhatsApp contact ID (phone@c.us)')
    push_name = fields.Char('Push Name', help='Name set by the contact')
    profile_pic_url = fields.Char('Profile Picture URL')
    about = fields.Text('About/Status')
    
    # Contact type
    is_business = fields.Boolean('Is Business', default=False, tracking=True)
    is_group = fields.Boolean('Is Group', default=False, tracking=True)
    is_blocked = fields.Boolean('Is Blocked', default=False, tracking=True)
    is_contact = fields.Boolean('Is Contact', default=True, help='Is in phone contacts')
    
    # Status
    status = fields.Selection([
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('blocked', 'Blocked'),
        ('deleted', 'Deleted'),
    ], string='Status', default='active', tracking=True)
    
    # Timestamps
    last_seen = fields.Datetime('Last Seen', tracking=True)
    created_date = fields.Datetime('Created Date', default=fields.Datetime.now)
    
    # Account relation
    account_id = fields.Many2one('whatsapp.account', 'WhatsApp Account', required=True, ondelete='cascade')
    
    # Odoo integration
    partner_id = fields.Many2one('res.partner', 'Related Partner', ondelete='set null', tracking=True)
    user_id = fields.Many2one('res.users', 'Related User', ondelete='set null')
    
    # Messages
    message_ids = fields.One2many('whatsapp.message', 'contact_id', 'Messages')
    message_count = fields.Integer('Message Count', compute='_compute_message_count', store=True)
    last_message_date = fields.Datetime('Last Message Date', compute='_compute_last_message_date', store=True)
    
    # Business info
    business_name = fields.Char('Business Name')
    business_category = fields.Char('Business Category')
    business_description = fields.Text('Business Description')
    business_website = fields.Char('Business Website')
    business_email = fields.Char('Business Email')
    business_address = fields.Text('Business Address')
    
    # Labels and tags
    tag_ids = fields.Many2many('whatsapp.contact.tag', string='Tags')
    
    # Statistics
    messages_sent = fields.Integer('Messages Sent', default=0)
    messages_received = fields.Integer('Messages Received', default=0)
    
    # Company
    company_id = fields.Many2one('res.company', 'Company', related='account_id.company_id', store=True)
    
    _sql_constraints = [
        ('unique_phone_account', 'unique(phone_number, account_id)', 'Phone number must be unique per account!'),
    ]

    @api.depends('message_ids')
    def _compute_message_count(self):
        for contact in self:
            contact.message_count = len(contact.message_ids)

    @api.depends('message_ids.timestamp')
    def _compute_last_message_date(self):
        for contact in self:
            if contact.message_ids:
                contact.last_message_date = max(contact.message_ids.mapped('timestamp'))
            else:
                contact.last_message_date = False

    @api.model
    def create(self, vals):
        # Format phone number
        if vals.get('phone_number'):
            vals['phone_number'] = self._format_phone_number(vals['phone_number'])
        
        # Generate WA ID
        if not vals.get('wa_id') and vals.get('phone_number'):
            vals['wa_id'] = f"{vals['phone_number']}@c.us"
        
        contact = super(WhatsAppContact, self).create(vals)
        
        # Try to link with existing partner
        contact._link_with_partner()
        
        return contact

    def write(self, vals):
        # Format phone number
        if vals.get('phone_number'):
            vals['phone_number'] = self._format_phone_number(vals['phone_number'])
            vals['wa_id'] = f"{vals['phone_number']}@c.us"
        
        result = super(WhatsAppContact, self).write(vals)
        
        # Update partner if phone changed
        if 'phone_number' in vals:
            self._link_with_partner()
        
        return result

    def _format_phone_number(self, phone):
        """Format phone number to international format"""
        if not phone:
            return phone
        
        # Remove all non-digit characters except +
        import re
        phone = re.sub(r'[^\d+]', '', phone)
        
        # Add + if not present
        if not phone.startswith('+'):
            phone = '+' + phone
        
        return phone

    def _link_with_partner(self):
        """Link contact with existing partner"""
        self.ensure_one()
        
        if self.partner_id:
            return
        
        # Search for existing partner by phone
        partner = self.env['res.partner'].search([
            ('phone', '=', self.phone_number)
        ], limit=1)
        
        if not partner:
            partner = self.env['res.partner'].search([
                ('mobile', '=', self.phone_number)
            ], limit=1)
        
        if partner:
            self.partner_id = partner.id

    def action_send_message(self):
        """Send message to contact"""
        self.ensure_one()
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Send Message',
            'res_model': 'whatsapp.send.message',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_account_id': self.account_id.id,
                'default_to_number': self.phone_number,
                'default_contact_id': self.id,
            }
        }

    def action_create_partner(self):
        """Create partner from contact"""
        self.ensure_one()
        
        if self.partner_id:
            return self.partner_id.get_formview_action()
        
        partner_vals = {
            'name': self.name,
            'phone': self.phone_number,
            'is_company': self.is_business,
            'supplier_rank': 0,
            'customer_rank': 1,
        }
        
        if self.business_email:
            partner_vals['email'] = self.business_email
        
        if self.business_website:
            partner_vals['website'] = self.business_website
        
        partner = self.env['res.partner'].create(partner_vals)
        self.partner_id = partner.id
        
        return partner.get_formview_action()

    def action_create_lead(self):
        """Create lead from contact"""
        self.ensure_one()
        
        lead_vals = {
            'name': f'WhatsApp Lead from {self.name}',
            'phone': self.phone_number,
            'description': f'WhatsApp contact: {self.name}',
            'source_id': self.env.ref('whatsapp.lead_source_whatsapp').id,
            'user_id': self.account_id.user_id.id,
        }
        
        if self.partner_id:
            lead_vals['partner_id'] = self.partner_id.id
        
        if self.business_email:
            lead_vals['email_from'] = self.business_email
        
        lead = self.env['crm.lead'].create(lead_vals)
        
        return lead.get_formview_action()

    def action_block_contact(self):
        """Block contact"""
        self.ensure_one()
        
        try:
            # Call WhatsApp API to block contact
            self.account_id._block_contact(self.phone_number)
            
            self.write({
                'is_blocked': True,
                'status': 'blocked',
            })
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': _('Contact blocked successfully'),
                    'type': 'success',
                }
            }
            
        except Exception as e:
            _logger.error(f'Error blocking contact: {e}')
            raise UserError(_('Error blocking contact: %s') % str(e))

    def action_unblock_contact(self):
        """Unblock contact"""
        self.ensure_one()
        
        try:
            # Call WhatsApp API to unblock contact
            self.account_id._unblock_contact(self.phone_number)
            
            self.write({
                'is_blocked': False,
                'status': 'active',
            })
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': _('Contact unblocked successfully'),
                    'type': 'success',
                }
            }
            
        except Exception as e:
            _logger.error(f'Error unblocking contact: {e}')
            raise UserError(_('Error unblocking contact: %s') % str(e))

    def action_sync_profile(self):
        """Sync contact profile from WhatsApp"""
        self.ensure_one()
        
        try:
            # Call WhatsApp API to get contact info
            contact_info = self.account_id._get_contact_info(self.phone_number)
            
            if contact_info:
                self.write({
                    'name': contact_info.get('name', self.name),
                    'push_name': contact_info.get('pushname'),
                    'profile_pic_url': contact_info.get('profile_pic_url'),
                    'about': contact_info.get('about'),
                    'is_business': contact_info.get('is_business', False),
                    'business_name': contact_info.get('business_name'),
                    'business_category': contact_info.get('business_category'),
                    'business_description': contact_info.get('business_description'),
                    'last_seen': fields.Datetime.now(),
                })
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': _('Contact profile synced successfully'),
                    'type': 'success',
                }
            }
            
        except Exception as e:
            _logger.error(f'Error syncing contact profile: {e}')
            raise UserError(_('Error syncing contact profile: %s') % str(e))

    def action_view_messages(self):
        """View messages with contact"""
        self.ensure_one()
        
        return {
            'type': 'ir.actions.act_window',
            'name': f'Messages with {self.name}',
            'res_model': 'whatsapp.message',
            'view_mode': 'tree,form',
            'domain': [('contact_id', '=', self.id)],
            'context': {
                'default_account_id': self.account_id.id,
                'default_contact_id': self.id,
            }
        }

    def action_open_chat(self):
        """Open chat with contact"""
        self.ensure_one()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'whatsapp_chat',
            'params': {
                'account_id': self.account_id.id,
                'contact_id': self.id,
            }
        }

    @api.model
    def sync_contacts_from_whatsapp(self, account_id):
        """Sync contacts from WhatsApp"""
        account = self.env['whatsapp.account'].browse(account_id)
        
        if not account.exists():
            return
        
        try:
            # Get contacts from WhatsApp API
            contacts_data = account._get_contacts()
            
            for contact_data in contacts_data:
                phone_number = contact_data.get('id', '').replace('@c.us', '')
                
                # Check if contact exists
                existing_contact = self.search([
                    ('account_id', '=', account_id),
                    ('phone_number', '=', phone_number)
                ], limit=1)
                
                contact_vals = {
                    'account_id': account_id,
                    'name': contact_data.get('name') or contact_data.get('pushname') or phone_number,
                    'phone_number': phone_number,
                    'wa_id': contact_data.get('id'),
                    'push_name': contact_data.get('pushname'),
                    'profile_pic_url': contact_data.get('profile_pic_url'),
                    'is_business': contact_data.get('is_business', False),
                    'is_group': contact_data.get('is_group', False),
                    'is_contact': contact_data.get('is_contact', True),
                    'last_seen': fields.Datetime.now(),
                }
                
                if existing_contact:
                    existing_contact.write(contact_vals)
                else:
                    self.create(contact_vals)
            
            return True
            
        except Exception as e:
            _logger.error(f'Error syncing contacts: {e}')
            return False


class WhatsAppContactTag(models.Model):
    _name = 'whatsapp.contact.tag'
    _description = 'WhatsApp Contact Tag'
    _order = 'name'

    name = fields.Char('Tag Name', required=True)
    color = fields.Integer('Color Index', default=0)
    active = fields.Boolean('Active', default=True)
    
    contact_ids = fields.Many2many('whatsapp.contact', string='Contacts')
    
    _sql_constraints = [
        ('unique_name', 'unique(name)', 'Tag name must be unique!'),
    ]