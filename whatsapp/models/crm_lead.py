# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    # WhatsApp integration fields
    whatsapp_number = fields.Char(
        'WhatsApp Number',
        help='WhatsApp phone number for this lead'
    )
    whatsapp_source = fields.Boolean(
        'WhatsApp Source',
        default=False,
        help='True if this lead was created from WhatsApp'
    )
    whatsapp_message_count = fields.Integer(
        'WhatsApp Messages',
        compute='_compute_whatsapp_message_count',
        help='Number of WhatsApp messages related to this lead'
    )
    whatsapp_last_message_date = fields.Datetime(
        'Last WhatsApp Message',
        compute='_compute_whatsapp_last_message_date',
        help='Date of the last WhatsApp message for this lead'
    )
    whatsapp_conversation_status = fields.Selection([
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('archived', 'Archived'),
    ], string='WhatsApp Conversation Status', default='inactive')
    
    # Related WhatsApp data
    whatsapp_contact_id = fields.Many2one(
        'whatsapp.contact',
        'WhatsApp Contact',
        ondelete='set null',
        help='Related WhatsApp contact'
    )
    whatsapp_message_ids = fields.One2many(
        'whatsapp.message',
        'lead_id',
        'WhatsApp Messages',
        help='WhatsApp messages related to this lead'
    )

    @api.depends('whatsapp_message_ids')
    def _compute_whatsapp_message_count(self):
        """Compute the number of WhatsApp messages for this lead"""
        for lead in self:
            lead.whatsapp_message_count = len(lead.whatsapp_message_ids)

    @api.depends('whatsapp_message_ids.timestamp')
    def _compute_whatsapp_last_message_date(self):
        """Compute the date of the last WhatsApp message"""
        for lead in self:
            if lead.whatsapp_message_ids:
                lead.whatsapp_last_message_date = max(
                    lead.whatsapp_message_ids.mapped('timestamp')
                )
            else:
                lead.whatsapp_last_message_date = False

    @api.model
    def create(self, vals):
        """Override create to handle WhatsApp-specific logic"""
        # Set WhatsApp number from phone if not provided
        if vals.get('phone') and not vals.get('whatsapp_number'):
            vals['whatsapp_number'] = vals['phone']
        
        # Check if this is a WhatsApp lead
        if vals.get('source_id'):
            source = self.env['utm.source'].browse(vals['source_id'])
            if source and source.name == 'WhatsApp':
                vals['whatsapp_source'] = True
                vals['whatsapp_conversation_status'] = 'active'
        
        lead = super(CrmLead, self).create(vals)
        
        # Link with WhatsApp contact if exists
        if lead.whatsapp_number:
            lead._link_whatsapp_contact()
        
        return lead

    def write(self, vals):
        """Override write to handle WhatsApp-specific logic"""
        # Update WhatsApp number if phone changes
        if 'phone' in vals and not vals.get('whatsapp_number'):
            vals['whatsapp_number'] = vals['phone']
        
        result = super(CrmLead, self).write(vals)
        
        # Re-link WhatsApp contact if phone number changed
        if 'phone' in vals or 'whatsapp_number' in vals:
            for lead in self:
                if lead.whatsapp_number:
                    lead._link_whatsapp_contact()
        
        return result

    def _link_whatsapp_contact(self):
        """Link lead with existing WhatsApp contact"""
        self.ensure_one()
        
        if not self.whatsapp_number:
            return
        
        # Search for existing WhatsApp contact
        contact = self.env['whatsapp.contact'].search([
            ('phone_number', '=', self.whatsapp_number)
        ], limit=1)
        
        if contact:
            self.whatsapp_contact_id = contact.id
            # Update conversation status
            if contact.message_ids:
                self.whatsapp_conversation_status = 'active'

    def action_send_whatsapp_message(self):
        """Send WhatsApp message to lead"""
        self.ensure_one()
        
        # Get WhatsApp number
        whatsapp_number = self.whatsapp_number or self.phone or self.mobile
        if not whatsapp_number:
            raise UserError(_('No WhatsApp number found for this lead.'))
        
        # Get available WhatsApp accounts
        accounts = self.env['whatsapp.account'].search([
            ('status', '=', 'ready'),
            ('active', '=', True)
        ])
        
        if not accounts:
            raise UserError(_('No active WhatsApp accounts found.'))
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Send WhatsApp Message'),
            'res_model': 'whatsapp.send.message',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_to_number': whatsapp_number,
                'default_account_id': accounts[0].id,
                'default_lead_id': self.id,
                'default_partner_id': self.partner_id.id if self.partner_id else False,
            }
        }

    def action_view_whatsapp_messages(self):
        """View WhatsApp messages for this lead"""
        self.ensure_one()
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('WhatsApp Messages for %s') % self.name,
            'res_model': 'whatsapp.message',
            'view_mode': 'tree,form',
            'domain': [('lead_id', '=', self.id)],
            'context': {
                'default_lead_id': self.id,
                'search_default_group_by_direction': 1,
            }
        }

    def action_create_whatsapp_contact(self):
        """Create WhatsApp contact for this lead"""
        self.ensure_one()
        
        whatsapp_number = self.whatsapp_number or self.phone or self.mobile
        if not whatsapp_number:
            raise UserError(_('No WhatsApp number found for this lead.'))
        
        # Get available WhatsApp accounts
        accounts = self.env['whatsapp.account'].search([
            ('status', '=', 'ready'),
            ('active', '=', True)
        ])
        
        if not accounts:
            raise UserError(_('No active WhatsApp accounts found.'))
        
        # Check if contact already exists
        existing_contact = self.env['whatsapp.contact'].search([
            ('phone_number', '=', whatsapp_number),
            ('account_id', '=', accounts[0].id)
        ], limit=1)
        
        if existing_contact:
            self.whatsapp_contact_id = existing_contact.id
            return existing_contact.get_formview_action()
        
        # Create new WhatsApp contact
        contact_vals = {
            'name': self.contact_name or self.partner_name or self.name,
            'phone_number': whatsapp_number,
            'account_id': accounts[0].id,
            'partner_id': self.partner_id.id if self.partner_id else False,
        }
        
        contact = self.env['whatsapp.contact'].create(contact_vals)
        self.whatsapp_contact_id = contact.id
        
        return contact.get_formview_action()

    def action_archive_whatsapp_conversation(self):
        """Archive WhatsApp conversation for this lead"""
        self.ensure_one()
        
        self.whatsapp_conversation_status = 'archived'
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': _('WhatsApp conversation archived'),
                'type': 'success',
            }
        }

    def action_activate_whatsapp_conversation(self):
        """Activate WhatsApp conversation for this lead"""
        self.ensure_one()
        
        self.whatsapp_conversation_status = 'active'
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': _('WhatsApp conversation activated'),
                'type': 'success',
            }
        }

    @api.model
    def create_lead_from_whatsapp_message(self, message_data):
        """Create a lead from WhatsApp message data"""
        # Extract contact information
        contact_info = message_data.get('contact', {})
        phone_number = message_data.get('from', '').replace('@c.us', '')
        
        # Check if lead already exists
        existing_lead = self.search([
            ('phone', '=', phone_number),
            ('stage_id.is_won', '=', False),
            ('active', '=', True)
        ], limit=1)
        
        if existing_lead:
            return existing_lead
        
        # Get WhatsApp source
        whatsapp_source = self.env.ref('whatsapp.utm_source_whatsapp', raise_if_not_found=False)
        
        # Create lead
        lead_vals = {
            'name': _('WhatsApp Lead from %s') % (contact_info.get('name') or phone_number),
            'phone': phone_number,
            'whatsapp_number': phone_number,
            'whatsapp_source': True,
            'whatsapp_conversation_status': 'active',
            'description': message_data.get('body', ''),
            'type': 'lead',
        }
        
        if whatsapp_source:
            lead_vals['source_id'] = whatsapp_source.id
        
        # Try to find existing partner
        partner = self.env['res.partner'].search([
            ('phone', '=', phone_number)
        ], limit=1)
        
        if not partner:
            partner = self.env['res.partner'].search([
                ('mobile', '=', phone_number)
            ], limit=1)
        
        if partner:
            lead_vals['partner_id'] = partner.id
            lead_vals['email_from'] = partner.email
        else:
            # Set contact name if available
            if contact_info.get('name'):
                lead_vals['contact_name'] = contact_info['name']
        
        lead = self.create(lead_vals)
        return lead

    def _get_whatsapp_number_for_sending(self):
        """Get the WhatsApp number to use for sending messages"""
        self.ensure_one()
        
        # Priority: whatsapp_number > phone > mobile
        return self.whatsapp_number or self.phone or self.mobile

    def _format_whatsapp_number(self, number):
        """Format phone number for WhatsApp"""
        if not number:
            return False
        
        # Remove all non-digit characters except +
        import re
        formatted = re.sub(r'[^\d+]', '', number)
        
        # Add + if not present
        if not formatted.startswith('+'):
            formatted = '+' + formatted
        
        return formatted