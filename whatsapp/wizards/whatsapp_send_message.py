# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import base64
import logging

_logger = logging.getLogger(__name__)


class WhatsAppSendMessage(models.TransientModel):
    _name = 'whatsapp.send.message'
    _description = 'Send WhatsApp Message'

    # Account and recipient
    account_id = fields.Many2one('whatsapp.account', 'WhatsApp Account', required=True)
    to_number = fields.Char('To Number', required=True, help='WhatsApp number to send message to')
    
    # Message content
    message = fields.Text('Message', required=True)
    message_type = fields.Selection([
        ('text', 'Text'),
        ('image', 'Image'),
        ('video', 'Video'),
        ('audio', 'Audio'),
        ('document', 'Document'),
        ('location', 'Location'),
        ('contact', 'Contact'),
    ], string='Message Type', default='text', required=True)
    
    # Template
    template_id = fields.Many2one('whatsapp.template', 'Template')
    template_variables = fields.Text('Template Variables', help='JSON variables for template')
    
    # Media attachment
    attachment_id = fields.Many2one('ir.attachment', 'Attachment')
    media_file = fields.Binary('Media File')
    media_filename = fields.Char('Media Filename')
    
    # Location data
    latitude = fields.Float('Latitude')
    longitude = fields.Float('Longitude')
    location_name = fields.Char('Location Name')
    location_address = fields.Text('Location Address')
    
    # Contact data
    contact_name = fields.Char('Contact Name')
    contact_phone = fields.Char('Contact Phone')
    contact_vcard = fields.Text('Contact VCard')
    
    # Relations
    partner_id = fields.Many2one('res.partner', 'Partner')
    contact_id = fields.Many2one('whatsapp.contact', 'WhatsApp Contact')
    group_id = fields.Many2one('whatsapp.group', 'WhatsApp Group')
    lead_id = fields.Many2one('crm.lead', 'Lead')
    sale_order_id = fields.Many2one('sale.order', 'Sale Order')
    
    # Reply context
    reply_to_message_id = fields.Many2one('whatsapp.message', 'Reply To Message')
    forward_from_message_id = fields.Many2one('whatsapp.message', 'Forward From Message')
    
    # Scheduling
    schedule_send = fields.Boolean('Schedule Send', default=False)
    schedule_date = fields.Datetime('Schedule Date')
    
    # Options
    preview_message = fields.Boolean('Preview Message', default=True)
    send_immediately = fields.Boolean('Send Immediately', default=True)

    @api.model
    def default_get(self, fields):
        res = super(WhatsAppSendMessage, self).default_get(fields)
        
        # Set default account
        if not res.get('account_id'):
            default_account = self.env['whatsapp.account'].search([
                ('status', '=', 'ready'),
                ('active', '=', True)
            ], limit=1)
            if default_account:
                res['account_id'] = default_account.id
        
        # Set recipient from context
        if self.env.context.get('default_partner_id'):
            partner = self.env['res.partner'].browse(self.env.context['default_partner_id'])
            if partner.whatsapp_number:
                res['to_number'] = partner.whatsapp_number
        
        return res

    @api.onchange('template_id')
    def _onchange_template_id(self):
        if self.template_id:
            self.message = self.template_id.content
            self.message_type = self.template_id.template_type
            
            # Set default variables
            variables = {}
            for var in self.template_id.get_variables():
                var_name = var.get('name', '')
                var_default = var.get('default', '')
                variables[var_name] = var_default
            
            if variables:
                import json
                self.template_variables = json.dumps(variables)

    @api.onchange('message_type')
    def _onchange_message_type(self):
        if self.message_type != 'text':
            self.template_id = False

    @api.onchange('media_file')
    def _onchange_media_file(self):
        if self.media_file and self.media_filename:
            # Create attachment
            attachment_vals = {
                'name': self.media_filename,
                'datas': self.media_file,
                'res_model': 'whatsapp.send.message',
                'res_id': self.id,
            }
            
            # Delete existing attachment
            if self.attachment_id:
                self.attachment_id.unlink()
            
            # Create new attachment
            attachment = self.env['ir.attachment'].create(attachment_vals)
            self.attachment_id = attachment.id

    def action_preview(self):
        """Preview message before sending"""
        self.ensure_one()
        
        # Render template if using template
        if self.template_id:
            variables = {}
            if self.template_variables:
                try:
                    import json
                    variables = json.loads(self.template_variables)
                except json.JSONDecodeError:
                    pass
            
            preview_message = self.template_id.render_template(variables)
        else:
            preview_message = self.message
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Message Preview',
            'res_model': 'whatsapp.message.preview',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_message': preview_message,
                'default_message_type': self.message_type,
                'default_to_number': self.to_number,
                'default_account_id': self.account_id.id,
            }
        }

    def action_send(self):
        """Send WhatsApp message"""
        self.ensure_one()
        
        # Validate account
        if self.account_id.status != 'ready':
            raise UserError(_('WhatsApp account is not ready to send messages.'))
        
        # Validate recipient
        if not self.to_number:
            raise UserError(_('Recipient number is required.'))
        
        # Validate message content
        if not self.message and self.message_type == 'text':
            raise UserError(_('Message content is required.'))
        
        # Prepare message content
        message_content = self.message
        
        # Render template if using template
        if self.template_id:
            variables = {}
            if self.template_variables:
                try:
                    import json
                    variables = json.loads(self.template_variables)
                except json.JSONDecodeError:
                    pass
            
            message_content = self.template_id.render_template(variables)
        
        try:
            # Send message
            if self.schedule_send and self.schedule_date:
                # Schedule message
                self._schedule_message(message_content)
            else:
                # Send immediately
                result = self._send_message_now(message_content)
                
                # Show success notification
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'message': _('Message sent successfully'),
                        'type': 'success',
                    }
                }
        
        except Exception as e:
            _logger.error(f'Error sending WhatsApp message: {e}')
            raise UserError(_('Error sending message: %s') % str(e))

    def _send_message_now(self, message_content):
        """Send message immediately"""
        self.ensure_one()
        
        # Prepare attachment
        attachment = None
        if self.attachment_id and self.message_type in ['image', 'video', 'audio', 'document']:
            attachment = self.attachment_id
        
        # Send message via account
        result = self.account_id.send_message(
            to=self.to_number,
            message=message_content,
            message_type=self.message_type,
            attachment=attachment
        )
        
        # Update relations
        if result:
            update_vals = {}
            if self.partner_id:
                update_vals['partner_id'] = self.partner_id.id
            if self.contact_id:
                update_vals['contact_id'] = self.contact_id.id
            if self.group_id:
                update_vals['group_id'] = self.group_id.id
            if self.lead_id:
                update_vals['lead_id'] = self.lead_id.id
            if self.sale_order_id:
                update_vals['sale_order_id'] = self.sale_order_id.id
            if self.reply_to_message_id:
                update_vals['reply_to_message_id'] = self.reply_to_message_id.id
            if self.forward_from_message_id:
                update_vals['forward_from_message_id'] = self.forward_from_message_id.id
            
            if update_vals:
                result.write(update_vals)
        
        return result

    def _schedule_message(self, message_content):
        """Schedule message for later sending"""
        self.ensure_one()
        
        # Create scheduled message
        scheduled_vals = {
            'account_id': self.account_id.id,
            'to_number': self.to_number,
            'message': message_content,
            'message_type': self.message_type,
            'schedule_date': self.schedule_date,
            'status': 'scheduled',
            'partner_id': self.partner_id.id if self.partner_id else False,
            'contact_id': self.contact_id.id if self.contact_id else False,
            'group_id': self.group_id.id if self.group_id else False,
            'lead_id': self.lead_id.id if self.lead_id else False,
            'sale_order_id': self.sale_order_id.id if self.sale_order_id else False,
            'template_id': self.template_id.id if self.template_id else False,
            'attachment_id': self.attachment_id.id if self.attachment_id else False,
        }
        
        scheduled_message = self.env['whatsapp.scheduled.message'].create(scheduled_vals)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': _('Message scheduled successfully'),
                'type': 'success',
            }
        }

    def action_send_and_close(self):
        """Send message and close wizard"""
        self.action_send()
        return {'type': 'ir.actions.act_window_close'}

    def action_save_as_template(self):
        """Save message as template"""
        self.ensure_one()
        
        if not self.message:
            raise UserError(_('Message content is required to save as template.'))
        
        template_vals = {
            'name': f'Template - {self.to_number}',
            'content': self.message,
            'template_type': self.message_type,
            'account_id': self.account_id.id,
        }
        
        template = self.env['whatsapp.template'].create(template_vals)
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Message Template',
            'res_model': 'whatsapp.template',
            'res_id': template.id,
            'view_mode': 'form',
            'target': 'new',
        }


class WhatsAppBulkMessage(models.TransientModel):
    _name = 'whatsapp.bulk.message'
    _description = 'Send Bulk WhatsApp Messages'

    # Account
    account_id = fields.Many2one('whatsapp.account', 'WhatsApp Account', required=True)
    
    # Recipients
    recipient_type = fields.Selection([
        ('partners', 'Partners'),
        ('contacts', 'WhatsApp Contacts'),
        ('leads', 'CRM Leads'),
        ('manual', 'Manual Numbers'),
    ], string='Recipient Type', default='partners', required=True)
    
    partner_ids = fields.Many2many('res.partner', string='Partners')
    contact_ids = fields.Many2many('whatsapp.contact', string='WhatsApp Contacts')
    lead_ids = fields.Many2many('crm.lead', string='CRM Leads')
    manual_numbers = fields.Text('Manual Numbers', help='One number per line')
    
    # Message content
    message = fields.Text('Message', required=True)
    message_type = fields.Selection([
        ('text', 'Text'),
        ('image', 'Image'),
        ('document', 'Document'),
    ], string='Message Type', default='text', required=True)
    
    # Template
    template_id = fields.Many2one('whatsapp.template', 'Template')
    
    # Media attachment
    attachment_id = fields.Many2one('ir.attachment', 'Attachment')
    media_file = fields.Binary('Media File')
    media_filename = fields.Char('Media Filename')
    
    # Options
    personalize_message = fields.Boolean('Personalize Message', default=True,
                                        help='Replace placeholders with recipient data')
    delay_between_messages = fields.Integer('Delay Between Messages (seconds)', default=2)
    
    # Scheduling
    schedule_send = fields.Boolean('Schedule Send', default=False)
    schedule_date = fields.Datetime('Schedule Date')
    
    # Statistics
    total_recipients = fields.Integer('Total Recipients', compute='_compute_total_recipients')
    estimated_cost = fields.Float('Estimated Cost', compute='_compute_estimated_cost')

    @api.depends('recipient_type', 'partner_ids', 'contact_ids', 'lead_ids', 'manual_numbers')
    def _compute_total_recipients(self):
        for record in self:
            count = 0
            if record.recipient_type == 'partners':
                count = len(record.partner_ids)
            elif record.recipient_type == 'contacts':
                count = len(record.contact_ids)
            elif record.recipient_type == 'leads':
                count = len(record.lead_ids)
            elif record.recipient_type == 'manual':
                if record.manual_numbers:
                    count = len([n.strip() for n in record.manual_numbers.split('\n') if n.strip()])
            
            record.total_recipients = count

    @api.depends('total_recipients', 'message_type')
    def _compute_estimated_cost(self):
        for record in self:
            # Estimate cost based on message type and count
            base_cost = 0.05  # Base cost per message
            if record.message_type == 'image':
                base_cost = 0.08
            elif record.message_type == 'document':
                base_cost = 0.06
            
            record.estimated_cost = record.total_recipients * base_cost

    @api.onchange('template_id')
    def _onchange_template_id(self):
        if self.template_id:
            self.message = self.template_id.content
            self.message_type = self.template_id.template_type

    def action_preview(self):
        """Preview bulk message"""
        self.ensure_one()
        
        # Get sample recipients
        sample_recipients = self._get_sample_recipients()
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Bulk Message Preview',
            'res_model': 'whatsapp.bulk.message.preview',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_message': self.message,
                'default_message_type': self.message_type,
                'default_recipients': sample_recipients,
                'default_total_recipients': self.total_recipients,
            }
        }

    def action_send(self):
        """Send bulk messages"""
        self.ensure_one()
        
        # Validate account
        if self.account_id.status != 'ready':
            raise UserError(_('WhatsApp account is not ready to send messages.'))
        
        # Validate recipients
        if self.total_recipients == 0:
            raise UserError(_('No recipients selected.'))
        
        # Validate message
        if not self.message:
            raise UserError(_('Message content is required.'))
        
        try:
            if self.schedule_send and self.schedule_date:
                # Schedule bulk message
                self._schedule_bulk_message()
            else:
                # Send immediately
                self._send_bulk_message_now()
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': _('Bulk messages sent successfully'),
                    'type': 'success',
                }
            }
        
        except Exception as e:
            _logger.error(f'Error sending bulk messages: {e}')
            raise UserError(_('Error sending bulk messages: %s') % str(e))

    def _get_recipients(self):
        """Get list of recipients"""
        self.ensure_one()
        
        recipients = []
        
        if self.recipient_type == 'partners':
            for partner in self.partner_ids:
                number = partner.whatsapp_number or partner.phone or partner.mobile
                if number:
                    recipients.append({
                        'number': number,
                        'name': partner.name,
                        'record_id': partner.id,
                        'model': 'res.partner',
                    })
        
        elif self.recipient_type == 'contacts':
            for contact in self.contact_ids:
                recipients.append({
                    'number': contact.phone_number,
                    'name': contact.name,
                    'record_id': contact.id,
                    'model': 'whatsapp.contact',
                })
        
        elif self.recipient_type == 'leads':
            for lead in self.lead_ids:
                number = lead.whatsapp_number or lead.phone or lead.mobile
                if number:
                    recipients.append({
                        'number': number,
                        'name': lead.name,
                        'record_id': lead.id,
                        'model': 'crm.lead',
                    })
        
        elif self.recipient_type == 'manual':
            if self.manual_numbers:
                for line in self.manual_numbers.split('\n'):
                    number = line.strip()
                    if number:
                        recipients.append({
                            'number': number,
                            'name': number,
                            'record_id': None,
                            'model': None,
                        })
        
        return recipients

    def _get_sample_recipients(self):
        """Get sample recipients for preview"""
        recipients = self._get_recipients()
        return recipients[:5]  # Return first 5 recipients

    def _send_bulk_message_now(self):
        """Send bulk messages immediately"""
        self.ensure_one()
        
        recipients = self._get_recipients()
        
        # Create bulk message job
        bulk_job = self.env['whatsapp.bulk.message.job'].create({
            'account_id': self.account_id.id,
            'message': self.message,
            'message_type': self.message_type,
            'template_id': self.template_id.id if self.template_id else False,
            'attachment_id': self.attachment_id.id if self.attachment_id else False,
            'total_recipients': len(recipients),
            'delay_between_messages': self.delay_between_messages,
            'personalize_message': self.personalize_message,
            'status': 'running',
        })
        
        # Send messages
        success_count = 0
        error_count = 0
        
        for recipient in recipients:
            try:
                # Personalize message if enabled
                message_content = self.message
                if self.personalize_message:
                    message_content = self._personalize_message(message_content, recipient)
                
                # Send message
                result = self.account_id.send_message(
                    to=recipient['number'],
                    message=message_content,
                    message_type=self.message_type,
                    attachment=self.attachment_id if self.attachment_id else None
                )
                
                if result:
                    success_count += 1
                else:
                    error_count += 1
                
                # Add delay between messages
                if self.delay_between_messages > 0:
                    import time
                    time.sleep(self.delay_between_messages)
            
            except Exception as e:
                _logger.error(f'Error sending message to {recipient["number"]}: {e}')
                error_count += 1
        
        # Update bulk job
        bulk_job.write({
            'status': 'completed',
            'success_count': success_count,
            'error_count': error_count,
            'completed_date': fields.Datetime.now(),
        })
        
        return bulk_job

    def _personalize_message(self, message, recipient):
        """Personalize message for recipient"""
        # Replace placeholders
        message = message.replace('{{name}}', recipient['name'])
        message = message.replace('{{number}}', recipient['number'])
        
        # Add more personalization based on model
        if recipient['model'] == 'res.partner' and recipient['record_id']:
            partner = self.env['res.partner'].browse(recipient['record_id'])
            message = message.replace('{{email}}', partner.email or '')
            message = message.replace('{{company}}', partner.company_name or '')
        
        return message

    def _schedule_bulk_message(self):
        """Schedule bulk message for later sending"""
        self.ensure_one()
        
        # Create scheduled bulk message
        scheduled_vals = {
            'account_id': self.account_id.id,
            'message': self.message,
            'message_type': self.message_type,
            'template_id': self.template_id.id if self.template_id else False,
            'attachment_id': self.attachment_id.id if self.attachment_id else False,
            'recipient_type': self.recipient_type,
            'recipient_data': self._serialize_recipients(),
            'schedule_date': self.schedule_date,
            'delay_between_messages': self.delay_between_messages,
            'personalize_message': self.personalize_message,
            'status': 'scheduled',
        }
        
        scheduled_bulk = self.env['whatsapp.scheduled.bulk.message'].create(scheduled_vals)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': _('Bulk messages scheduled successfully'),
                'type': 'success',
            }
        }

    def _serialize_recipients(self):
        """Serialize recipients for storage"""
        recipients = self._get_recipients()
        import json
        return json.dumps(recipients)


class WhatsAppAccountSetup(models.TransientModel):
    _name = 'whatsapp.account.setup'
    _description = 'WhatsApp Account Setup Wizard'

    # Step 1: Basic Information
    name = fields.Char('Account Name', required=True)
    phone_number = fields.Char('Phone Number', required=True)
    country_code = fields.Char('Country Code', default='+1')
    display_name = fields.Char('Display Name')
    
    # Step 2: Configuration
    auto_reply = fields.Boolean('Enable Auto Reply', default=False)
    auto_reply_message = fields.Text('Auto Reply Message')
    
    # Step 3: Integration
    create_lead_from_message = fields.Boolean('Create Leads from Messages', default=True)
    sync_contacts = fields.Boolean('Sync Contacts', default=True)
    
    # Step 4: Advanced Settings
    api_endpoint = fields.Char('API Endpoint', default='http://localhost:3000')
    webhook_url = fields.Char('Webhook URL')
    
    # Current step
    current_step = fields.Integer('Current Step', default=1)

    def action_next_step(self):
        """Go to next step"""
        self.ensure_one()
        
        if self.current_step < 4:
            self.current_step += 1
            return self._reopen_wizard()
        else:
            return self.action_create_account()

    def action_prev_step(self):
        """Go to previous step"""
        self.ensure_one()
        
        if self.current_step > 1:
            self.current_step -= 1
            return self._reopen_wizard()

    def action_create_account(self):
        """Create WhatsApp account"""
        self.ensure_one()
        
        # Validate required fields
        if not self.name or not self.phone_number:
            raise UserError(_('Name and phone number are required.'))
        
        # Create account
        account_vals = {
            'name': self.name,
            'phone_number': self.phone_number,
            'country_code': self.country_code,
            'display_name': self.display_name,
            'auto_reply': self.auto_reply,
            'auto_reply_message': self.auto_reply_message,
            'api_endpoint': self.api_endpoint,
            'webhook_url': self.webhook_url,
            'user_id': self.env.user.id,
        }
        
        account = self.env['whatsapp.account'].create(account_vals)
        
        # Start connection
        try:
            account.action_connect()
        except Exception as e:
            _logger.warning(f'Failed to start account connection: {e}')
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'WhatsApp Account',
            'res_model': 'whatsapp.account',
            'res_id': account.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _reopen_wizard(self):
        """Reopen wizard"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'WhatsApp Account Setup',
            'res_model': 'whatsapp.account.setup',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }