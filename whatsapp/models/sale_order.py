# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # WhatsApp integration fields
    whatsapp_number = fields.Char(
        'WhatsApp Number',
        compute='_compute_whatsapp_number',
        store=True,
        help='WhatsApp phone number for this order'
    )
    whatsapp_message_count = fields.Integer(
        'WhatsApp Messages',
        compute='_compute_whatsapp_message_count',
        help='Number of WhatsApp messages related to this order'
    )
    whatsapp_last_message_date = fields.Datetime(
        'Last WhatsApp Message',
        compute='_compute_whatsapp_last_message_date',
        help='Date of the last WhatsApp message for this order'
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
        'sale_order_id',
        'WhatsApp Messages',
        help='WhatsApp messages related to this order'
    )
    
    # Notifications settings
    whatsapp_notify_order_confirm = fields.Boolean(
        'Notify Order Confirmation',
        default=True,
        help='Send WhatsApp notification when order is confirmed'
    )
    whatsapp_notify_delivery = fields.Boolean(
        'Notify Delivery',
        default=True,
        help='Send WhatsApp notification when order is delivered'
    )
    whatsapp_notify_invoice = fields.Boolean(
        'Notify Invoice',
        default=True,
        help='Send WhatsApp notification when invoice is sent'
    )

    @api.depends('partner_id.whatsapp_number', 'partner_id.phone', 'partner_id.mobile')
    def _compute_whatsapp_number(self):
        """Compute WhatsApp number from partner"""
        for order in self:
            if order.partner_id:
                order.whatsapp_number = (
                    order.partner_id.whatsapp_number or
                    order.partner_id.phone or
                    order.partner_id.mobile
                )
            else:
                order.whatsapp_number = False

    @api.depends('whatsapp_message_ids')
    def _compute_whatsapp_message_count(self):
        """Compute the number of WhatsApp messages for this order"""
        for order in self:
            order.whatsapp_message_count = len(order.whatsapp_message_ids)

    @api.depends('whatsapp_message_ids.timestamp')
    def _compute_whatsapp_last_message_date(self):
        """Compute the date of the last WhatsApp message"""
        for order in self:
            if order.whatsapp_message_ids:
                order.whatsapp_last_message_date = max(
                    order.whatsapp_message_ids.mapped('timestamp')
                )
            else:
                order.whatsapp_last_message_date = False

    def action_send_whatsapp_message(self):
        """Send WhatsApp message to order customer"""
        self.ensure_one()
        
        # Get WhatsApp number
        whatsapp_number = self.whatsapp_number
        if not whatsapp_number:
            raise UserError(_('No WhatsApp number found for this order customer.'))
        
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
                'default_sale_order_id': self.id,
                'default_partner_id': self.partner_id.id,
            }
        }

    def action_view_whatsapp_messages(self):
        """View WhatsApp messages for this order"""
        self.ensure_one()
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('WhatsApp Messages for %s') % self.name,
            'res_model': 'whatsapp.message',
            'view_mode': 'tree,form',
            'domain': [('sale_order_id', '=', self.id)],
            'context': {
                'default_sale_order_id': self.id,
                'search_default_group_by_direction': 1,
            }
        }

    def action_send_order_confirmation(self):
        """Send order confirmation via WhatsApp"""
        self.ensure_one()
        
        if not self.whatsapp_number:
            raise UserError(_('No WhatsApp number found for this order customer.'))
        
        # Get available WhatsApp accounts
        accounts = self.env['whatsapp.account'].search([
            ('status', '=', 'ready'),
            ('active', '=', True)
        ])
        
        if not accounts:
            raise UserError(_('No active WhatsApp accounts found.'))
        
        # Get order confirmation template
        template = self.env.ref('whatsapp.whatsapp_template_order_confirmation', raise_if_not_found=False)
        
        # Prepare message content
        message_content = _(
            "Dear %s,\n\n"
            "Your order %s has been confirmed!\n\n"
            "Order Details:\n"
            "- Total Amount: %s\n"
            "- Order Date: %s\n\n"
            "Thank you for your business!"
        ) % (
            self.partner_id.name,
            self.name,
            self.amount_total,
            self.date_order.strftime('%Y-%m-%d') if self.date_order else ''
        )
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Send Order Confirmation'),
            'res_model': 'whatsapp.send.message',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_to_number': self.whatsapp_number,
                'default_account_id': accounts[0].id,
                'default_sale_order_id': self.id,
                'default_partner_id': self.partner_id.id,
                'default_message': message_content,
                'default_template_id': template.id if template else False,
            }
        }

    def action_send_delivery_notification(self):
        """Send delivery notification via WhatsApp"""
        self.ensure_one()
        
        if not self.whatsapp_number:
            raise UserError(_('No WhatsApp number found for this order customer.'))
        
        # Get available WhatsApp accounts
        accounts = self.env['whatsapp.account'].search([
            ('status', '=', 'ready'),
            ('active', '=', True)
        ])
        
        if not accounts:
            raise UserError(_('No active WhatsApp accounts found.'))
        
        # Get delivery notification template
        template = self.env.ref('whatsapp.whatsapp_template_delivery_notification', raise_if_not_found=False)
        
        # Prepare message content
        message_content = _(
            "Dear %s,\n\n"
            "Your order %s has been delivered!\n\n"
            "We hope you enjoy your purchase. "
            "If you have any questions or concerns, please feel free to contact us.\n\n"
            "Thank you for choosing us!"
        ) % (
            self.partner_id.name,
            self.name
        )
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Send Delivery Notification'),
            'res_model': 'whatsapp.send.message',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_to_number': self.whatsapp_number,
                'default_account_id': accounts[0].id,
                'default_sale_order_id': self.id,
                'default_partner_id': self.partner_id.id,
                'default_message': message_content,
                'default_template_id': template.id if template else False,
            }
        }

    def action_send_payment_reminder(self):
        """Send payment reminder via WhatsApp"""
        self.ensure_one()
        
        if not self.whatsapp_number:
            raise UserError(_('No WhatsApp number found for this order customer.'))
        
        # Get available WhatsApp accounts
        accounts = self.env['whatsapp.account'].search([
            ('status', '=', 'ready'),
            ('active', '=', True)
        ])
        
        if not accounts:
            raise UserError(_('No active WhatsApp accounts found.'))
        
        # Get payment reminder template
        template = self.env.ref('whatsapp.whatsapp_template_payment_reminder', raise_if_not_found=False)
        
        # Prepare message content
        message_content = _(
            "Dear %s,\n\n"
            "This is a friendly reminder about your order %s.\n\n"
            "Order Details:\n"
            "- Total Amount: %s\n"
            "- Order Date: %s\n\n"
            "Please complete your payment at your earliest convenience.\n\n"
            "Thank you!"
        ) % (
            self.partner_id.name,
            self.name,
            self.amount_total,
            self.date_order.strftime('%Y-%m-%d') if self.date_order else ''
        )
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Send Payment Reminder'),
            'res_model': 'whatsapp.send.message',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_to_number': self.whatsapp_number,
                'default_account_id': accounts[0].id,
                'default_sale_order_id': self.id,
                'default_partner_id': self.partner_id.id,
                'default_message': message_content,
                'default_template_id': template.id if template else False,
            }
        }

    def action_confirm(self):
        """Override confirm to send WhatsApp notification"""
        result = super(SaleOrder, self).action_confirm()
        
        # Send WhatsApp notification if enabled
        for order in self:
            if order.whatsapp_notify_order_confirm and order.whatsapp_number:
                try:
                    order._send_whatsapp_order_confirmation()
                except Exception as e:
                    _logger.warning(f'Failed to send WhatsApp order confirmation: {e}')
        
        return result

    def _send_whatsapp_order_confirmation(self):
        """Send automatic WhatsApp order confirmation"""
        self.ensure_one()
        
        # Get available WhatsApp accounts
        accounts = self.env['whatsapp.account'].search([
            ('status', '=', 'ready'),
            ('active', '=', True)
        ])
        
        if not accounts:
            return
        
        # Get order confirmation template
        template = self.env.ref('whatsapp.whatsapp_template_order_confirmation', raise_if_not_found=False)
        
        # Prepare message content
        message_content = _(
            "Dear %s,\n\n"
            "Your order %s has been confirmed!\n\n"
            "Order Details:\n"
            "- Total Amount: %s\n"
            "- Order Date: %s\n\n"
            "Thank you for your business!"
        ) % (
            self.partner_id.name,
            self.name,
            self.amount_total,
            self.date_order.strftime('%Y-%m-%d') if self.date_order else ''
        )
        
        try:
            # Send message
            accounts[0].send_message(
                to=self.whatsapp_number,
                message=message_content,
                message_type='text'
            )
        except Exception as e:
            _logger.error(f'Error sending WhatsApp order confirmation: {e}')

    def _link_whatsapp_contact(self):
        """Link order with existing WhatsApp contact"""
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

    @api.model
    def create(self, vals):
        """Override create to link WhatsApp contact"""
        order = super(SaleOrder, self).create(vals)
        
        # Link with WhatsApp contact if exists
        if order.whatsapp_number:
            order._link_whatsapp_contact()
        
        return order

    def write(self, vals):
        """Override write to handle WhatsApp-specific logic"""
        result = super(SaleOrder, self).write(vals)
        
        # Re-link WhatsApp contact if partner changed
        if 'partner_id' in vals:
            for order in self:
                if order.whatsapp_number:
                    order._link_whatsapp_contact()
        
        return result

    def _get_whatsapp_number_for_sending(self):
        """Get the WhatsApp number to use for sending messages"""
        self.ensure_one()
        
        # Priority: partner whatsapp_number > phone > mobile
        return self.whatsapp_number

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