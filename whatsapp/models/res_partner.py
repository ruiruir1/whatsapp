# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import logging
import requests
import base64
from datetime import timedelta

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # WhatsApp fields
    whatsapp_number = fields.Char('WhatsApp Number', help='WhatsApp phone number')
    whatsapp_name = fields.Char('WhatsApp Name', help='Name from WhatsApp')
    whatsapp_profile_pic = fields.Binary('WhatsApp Profile Picture', attachment=True)
    whatsapp_about = fields.Text('WhatsApp About', help='WhatsApp status/about')
    
    # WhatsApp contact relation
    whatsapp_contact_ids = fields.One2many('whatsapp.contact', 'partner_id', 'WhatsApp Contacts')
    whatsapp_contact_count = fields.Integer('WhatsApp Contacts', compute='_compute_whatsapp_contact_count')
    
    # WhatsApp messages
    whatsapp_message_ids = fields.One2many('whatsapp.message', 'partner_id', 'WhatsApp Messages')
    whatsapp_message_count = fields.Integer('WhatsApp Messages', compute='_compute_whatsapp_message_count')
    
    # WhatsApp status
    whatsapp_last_seen = fields.Datetime('WhatsApp Last Seen')
    whatsapp_is_business = fields.Boolean('WhatsApp Business')
    whatsapp_is_blocked = fields.Boolean('WhatsApp Blocked')

    @api.depends('whatsapp_contact_ids')
    def _compute_whatsapp_contact_count(self):
        for partner in self:
            partner.whatsapp_contact_count = len(partner.whatsapp_contact_ids)

    @api.depends('whatsapp_message_ids')
    def _compute_whatsapp_message_count(self):
        for partner in self:
            partner.whatsapp_message_count = len(partner.whatsapp_message_ids)

    def action_send_whatsapp_message(self):
        """Send WhatsApp message to partner"""
        self.ensure_one()
        
        # Get WhatsApp number
        whatsapp_number = self.whatsapp_number or self.phone or self.mobile
        if not whatsapp_number:
            raise UserError(_('No WhatsApp number found for this partner.'))
        
        # Get available WhatsApp accounts
        accounts = self.env['whatsapp.account'].search([
            ('status', '=', 'ready'),
            ('active', '=', True)
        ])
        
        if not accounts:
            raise UserError(_('No active WhatsApp accounts found.'))
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Send WhatsApp Message',
            'res_model': 'whatsapp.send.message',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_partner_id': self.id,
                'default_to_number': whatsapp_number,
                'default_account_id': accounts[0].id,
            }
        }

    def action_view_whatsapp_messages(self):
        """View WhatsApp messages with partner"""
        self.ensure_one()
        
        return {
            'type': 'ir.actions.act_window',
            'name': f'WhatsApp Messages with {self.name}',
            'res_model': 'whatsapp.message',
            'view_mode': 'tree,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {
                'default_partner_id': self.id,
            }
        }

    def action_view_whatsapp_contacts(self):
        """View WhatsApp contacts for partner"""
        self.ensure_one()
        
        return {
            'type': 'ir.actions.act_window',
            'name': f'WhatsApp Contacts for {self.name}',
            'res_model': 'whatsapp.contact',
            'view_mode': 'tree,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {
                'default_partner_id': self.id,
            }
        }

    def action_sync_whatsapp_info(self):
        """Sync WhatsApp information"""
        self.ensure_one()
        
        if not self.whatsapp_number:
            raise UserError(_('No WhatsApp number found for this partner.'))
        
        try:
            # Find WhatsApp contact
            whatsapp_contact = self.env['whatsapp.contact'].search([
                ('phone_number', '=', self.whatsapp_number),
                ('partner_id', '=', False)
            ], limit=1)
            
            if whatsapp_contact:
                # Link contact to partner
                whatsapp_contact.partner_id = self.id
                
                # Update partner info from WhatsApp
                self.write({
                    'whatsapp_name': whatsapp_contact.name,
                    'whatsapp_about': whatsapp_contact.about,
                    'whatsapp_last_seen': whatsapp_contact.last_seen,
                    'whatsapp_is_business': whatsapp_contact.is_business,
                    'whatsapp_is_blocked': whatsapp_contact.is_blocked,
                })
                
                # Sync profile picture
                if whatsapp_contact.profile_pic_url:
                    try:
                        response = requests.get(whatsapp_contact.profile_pic_url, timeout=10)
                        if response.status_code == 200:
                            self.whatsapp_profile_pic = base64.b64encode(response.content)
                    except (requests.RequestException, Exception) as e:
                        _logger.warning(f'Failed to download profile picture: {e}')
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'message': _('WhatsApp information synced successfully'),
                        'type': 'success',
                    }
                }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'message': _('No WhatsApp contact found with this number'),
                        'type': 'warning',
                    }
                }
        
        except Exception as e:
            _logger.error(f'Error syncing WhatsApp info: {e}')
            raise UserError(_('Error syncing WhatsApp info: %s') % str(e))

    def action_create_whatsapp_contact(self):
        """Create WhatsApp contact for partner"""
        self.ensure_one()
        
        if not self.whatsapp_number:
            raise UserError(_('No WhatsApp number found for this partner.'))
        
        # Get available WhatsApp accounts
        accounts = self.env['whatsapp.account'].search([
            ('status', '=', 'ready'),
            ('active', '=', True)
        ])
        
        if not accounts:
            raise UserError(_('No active WhatsApp accounts found.'))
        
        # Create WhatsApp contact
        contact_vals = {
            'name': self.name,
            'phone_number': self.whatsapp_number,
            'partner_id': self.id,
            'account_id': accounts[0].id,
        }
        
        contact = self.env['whatsapp.contact'].create(contact_vals)
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'WhatsApp Contact',
            'res_model': 'whatsapp.contact',
            'res_id': contact.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model
    def create_partner_from_whatsapp(self, whatsapp_contact):
        """Create partner from WhatsApp contact"""
        partner_vals = {
            'name': whatsapp_contact.name,
            'phone': whatsapp_contact.phone_number,
            'whatsapp_number': whatsapp_contact.phone_number,
            'whatsapp_name': whatsapp_contact.name,
            'whatsapp_about': whatsapp_contact.about,
            'whatsapp_last_seen': whatsapp_contact.last_seen,
            'whatsapp_is_business': whatsapp_contact.is_business,
            'is_company': whatsapp_contact.is_business,
        }
        
        # Only set customer_rank and supplier_rank if account module is installed
        if self.env['ir.module.module'].search([('name', '=', 'account'), ('state', '=', 'installed')]):
            partner_vals.update({
                'customer_rank': 1,
                'supplier_rank': 0,
            })
        
        partner = self.create(partner_vals)
        
        # Link WhatsApp contact to partner
        whatsapp_contact.partner_id = partner.id
        
        return partner