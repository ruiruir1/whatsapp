# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import csv
import io
import base64
import logging

_logger = logging.getLogger(__name__)


class WhatsAppImportContacts(models.TransientModel):
    _name = 'whatsapp.import.contacts'
    _description = 'Import WhatsApp Contacts'

    # Account
    account_id = fields.Many2one('whatsapp.account', 'WhatsApp Account', required=True)
    
    # Import method
    import_method = fields.Selection([
        ('sync', 'Sync from WhatsApp'),
        ('csv', 'Import from CSV'),
        ('manual', 'Manual Entry'),
    ], string='Import Method', default='sync', required=True)
    
    # CSV import
    csv_file = fields.Binary('CSV File')
    csv_filename = fields.Char('CSV Filename')
    csv_delimiter = fields.Selection([
        (',', 'Comma (,)'),
        (';', 'Semicolon (;)'),
        ('\t', 'Tab'),
        ('|', 'Pipe (|)'),
    ], string='CSV Delimiter', default=',')
    
    # Manual entry
    manual_contacts = fields.Text('Manual Contacts', help='One contact per line: Name, Phone Number')
    
    # Options
    create_partners = fields.Boolean('Create Partners', default=True, 
                                    help='Create Odoo partners for imported contacts')
    update_existing = fields.Boolean('Update Existing', default=True,
                                    help='Update existing contacts with new data')
    skip_duplicates = fields.Boolean('Skip Duplicates', default=True,
                                    help='Skip contacts that already exist')
    
    # Results
    imported_count = fields.Integer('Imported Count', readonly=True)
    updated_count = fields.Integer('Updated Count', readonly=True)
    skipped_count = fields.Integer('Skipped Count', readonly=True)
    error_count = fields.Integer('Error Count', readonly=True)
    import_log = fields.Text('Import Log', readonly=True)

    def action_import_contacts(self):
        """Import contacts based on selected method"""
        self.ensure_one()
        
        try:
            if self.import_method == 'sync':
                return self._sync_from_whatsapp()
            elif self.import_method == 'csv':
                return self._import_from_csv()
            elif self.import_method == 'manual':
                return self._import_manual()
        
        except Exception as e:
            _logger.error(f'Error importing contacts: {e}')
            raise UserError(_('Error importing contacts: %s') % str(e))

    def _sync_from_whatsapp(self):
        """Sync contacts from WhatsApp"""
        self.ensure_one()
        
        if self.account_id.status != 'ready':
            raise UserError(_('WhatsApp account is not ready.'))
        
        try:
            # Sync contacts via account
            self.account_id.sync_contacts()
            
            # Count results
            total_contacts = len(self.account_id.contact_ids)
            
            self.write({
                'imported_count': total_contacts,
                'import_log': _('Successfully synced %s contacts from WhatsApp') % total_contacts
            })
            
            return self._show_results()
        
        except Exception as e:
            _logger.error(f'Error syncing contacts: {e}')
            raise UserError(_('Error syncing contacts: %s') % str(e))

    def _import_from_csv(self):
        """Import contacts from CSV file"""
        self.ensure_one()
        
        if not self.csv_file:
            raise UserError(_('Please select a CSV file.'))
        
        try:
            # Decode CSV file
            csv_data = base64.b64decode(self.csv_file).decode('utf-8')
            csv_reader = csv.DictReader(io.StringIO(csv_data), delimiter=self.csv_delimiter)
            
            imported_count = 0
            updated_count = 0
            skipped_count = 0
            error_count = 0
            log_lines = []
            
            for row_num, row in enumerate(csv_reader, 1):
                try:
                    # Get contact data
                    name = row.get('Name', '').strip()
                    phone = row.get('Phone', '').strip()
                    
                    if not name or not phone:
                        log_lines.append(f'Row {row_num}: Missing name or phone')
                        error_count += 1
                        continue
                    
                    # Check if contact exists
                    existing_contact = self.env['whatsapp.contact'].search([
                        ('account_id', '=', self.account_id.id),
                        ('phone_number', '=', phone)
                    ], limit=1)
                    
                    if existing_contact:
                        if self.skip_duplicates:
                            log_lines.append(f'Row {row_num}: Skipped duplicate contact {name}')
                            skipped_count += 1
                            continue
                        elif self.update_existing:
                            existing_contact.write({
                                'name': name,
                                'about': row.get('About', ''),
                                'is_business': row.get('Is Business', '').lower() == 'true',
                            })
                            log_lines.append(f'Row {row_num}: Updated contact {name}')
                            updated_count += 1
                            continue
                    
                    # Create new contact
                    contact_vals = {
                        'account_id': self.account_id.id,
                        'name': name,
                        'phone_number': phone,
                        'about': row.get('About', ''),
                        'is_business': row.get('Is Business', '').lower() == 'true',
                    }
                    
                    contact = self.env['whatsapp.contact'].create(contact_vals)
                    
                    # Create partner if requested
                    if self.create_partners:
                        self._create_partner_for_contact(contact)
                    
                    log_lines.append(f'Row {row_num}: Imported contact {name}')
                    imported_count += 1
                
                except Exception as e:
                    log_lines.append(f'Row {row_num}: Error - {str(e)}')
                    error_count += 1
            
            # Update results
            self.write({
                'imported_count': imported_count,
                'updated_count': updated_count,
                'skipped_count': skipped_count,
                'error_count': error_count,
                'import_log': '\n'.join(log_lines)
            })
            
            return self._show_results()
        
        except Exception as e:
            _logger.error(f'Error importing from CSV: {e}')
            raise UserError(_('Error importing from CSV: %s') % str(e))

    def _import_manual(self):
        """Import contacts from manual entry"""
        self.ensure_one()
        
        if not self.manual_contacts:
            raise UserError(_('Please enter contact information.'))
        
        try:
            imported_count = 0
            updated_count = 0
            skipped_count = 0
            error_count = 0
            log_lines = []
            
            for line_num, line in enumerate(self.manual_contacts.split('\n'), 1):
                line = line.strip()
                if not line:
                    continue
                
                try:
                    # Parse line (Name, Phone)
                    parts = [p.strip() for p in line.split(',')]
                    if len(parts) < 2:
                        log_lines.append(f'Line {line_num}: Invalid format. Expected: Name, Phone')
                        error_count += 1
                        continue
                    
                    name = parts[0]
                    phone = parts[1]
                    
                    # Check if contact exists
                    existing_contact = self.env['whatsapp.contact'].search([
                        ('account_id', '=', self.account_id.id),
                        ('phone_number', '=', phone)
                    ], limit=1)
                    
                    if existing_contact:
                        if self.skip_duplicates:
                            log_lines.append(f'Line {line_num}: Skipped duplicate contact {name}')
                            skipped_count += 1
                            continue
                        elif self.update_existing:
                            existing_contact.write({'name': name})
                            log_lines.append(f'Line {line_num}: Updated contact {name}')
                            updated_count += 1
                            continue
                    
                    # Create new contact
                    contact_vals = {
                        'account_id': self.account_id.id,
                        'name': name,
                        'phone_number': phone,
                    }
                    
                    contact = self.env['whatsapp.contact'].create(contact_vals)
                    
                    # Create partner if requested
                    if self.create_partners:
                        self._create_partner_for_contact(contact)
                    
                    log_lines.append(f'Line {line_num}: Imported contact {name}')
                    imported_count += 1
                
                except Exception as e:
                    log_lines.append(f'Line {line_num}: Error - {str(e)}')
                    error_count += 1
            
            # Update results
            self.write({
                'imported_count': imported_count,
                'updated_count': updated_count,
                'skipped_count': skipped_count,
                'error_count': error_count,
                'import_log': '\n'.join(log_lines)
            })
            
            return self._show_results()
        
        except Exception as e:
            _logger.error(f'Error importing manual contacts: {e}')
            raise UserError(_('Error importing manual contacts: %s') % str(e))

    def _create_partner_for_contact(self, contact):
        """Create partner for contact"""
        try:
            # Check if partner already exists
            existing_partner = self.env['res.partner'].search([
                ('phone', '=', contact.phone_number)
            ], limit=1)
            
            if existing_partner:
                contact.partner_id = existing_partner.id
            else:
                partner_vals = {
                    'name': contact.name,
                    'phone': contact.phone_number,
                    'whatsapp_number': contact.phone_number,
                    'is_company': contact.is_business,
                    'customer_rank': 1,
                    'supplier_rank': 0,
                }
                
                partner = self.env['res.partner'].create(partner_vals)
                contact.partner_id = partner.id
        
        except Exception as e:
            _logger.warning(f'Error creating partner for contact {contact.name}: {e}')

    def _show_results(self):
        """Show import results"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Import Results',
            'res_model': 'whatsapp.import.contacts',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_download_template(self):
        """Download CSV template"""
        template_data = [
            ['Name', 'Phone', 'About', 'Is Business'],
            ['John Doe', '+1234567890', 'Sample contact', 'false'],
            ['ABC Company', '+1234567891', 'Business contact', 'true'],
        ]
        
        # Convert to CSV
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerows(template_data)
        csv_content = output.getvalue().encode('utf-8')
        
        # Create attachment
        attachment = self.env['ir.attachment'].create({
            'name': 'whatsapp_contacts_template.csv',
            'type': 'binary',
            'datas': base64.b64encode(csv_content),
            'mimetype': 'text/csv',
        })
        
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }


class WhatsAppExportMessages(models.TransientModel):
    _name = 'whatsapp.export.messages'
    _description = 'Export WhatsApp Messages'

    # Account and filters
    account_id = fields.Many2one('whatsapp.account', 'WhatsApp Account', required=True)
    contact_id = fields.Many2one('whatsapp.contact', 'Contact', domain="[('account_id', '=', account_id)]")
    group_id = fields.Many2one('whatsapp.group', 'Group', domain="[('account_id', '=', account_id)]")
    
    # Date range
    date_from = fields.Datetime('From Date', required=True)
    date_to = fields.Datetime('To Date', required=True)
    
    # Message types
    message_types = fields.Selection([
        ('all', 'All Messages'),
        ('text', 'Text Only'),
        ('media', 'Media Only'),
        ('incoming', 'Incoming Only'),
        ('outgoing', 'Outgoing Only'),
    ], string='Message Types', default='all', required=True)
    
    # Export format
    export_format = fields.Selection([
        ('csv', 'CSV'),
        ('json', 'JSON'),
        ('html', 'HTML'),
        ('txt', 'Text'),
    ], string='Export Format', default='csv', required=True)
    
    # Options
    include_media = fields.Boolean('Include Media Links', default=True)
    include_metadata = fields.Boolean('Include Metadata', default=True)
    group_by_date = fields.Boolean('Group by Date', default=True)

    @api.model
    def default_get(self, fields):
        res = super(WhatsAppExportMessages, self).default_get(fields)
        
        # Set default date range (last 30 days)
        from datetime import datetime, timedelta
        res['date_to'] = datetime.now()
        res['date_from'] = datetime.now() - timedelta(days=30)
        
        return res

    def action_export_messages(self):
        """Export WhatsApp messages"""
        self.ensure_one()
        
        try:
            # Get messages
            messages = self._get_messages()
            
            if not messages:
                raise UserError(_('No messages found with the selected criteria.'))
            
            # Export based on format
            if self.export_format == 'csv':
                return self._export_csv(messages)
            elif self.export_format == 'json':
                return self._export_json(messages)
            elif self.export_format == 'html':
                return self._export_html(messages)
            elif self.export_format == 'txt':
                return self._export_txt(messages)
        
        except Exception as e:
            _logger.error(f'Error exporting messages: {e}')
            raise UserError(_('Error exporting messages: %s') % str(e))

    def _get_messages(self):
        """Get messages based on filters"""
        self.ensure_one()
        
        domain = [
            ('account_id', '=', self.account_id.id),
            ('timestamp', '>=', self.date_from),
            ('timestamp', '<=', self.date_to),
        ]
        
        # Filter by contact or group
        if self.contact_id:
            domain.append(('contact_id', '=', self.contact_id.id))
        if self.group_id:
            domain.append(('group_id', '=', self.group_id.id))
        
        # Filter by message type
        if self.message_types == 'text':
            domain.append(('message_type', '=', 'text'))
        elif self.message_types == 'media':
            domain.append(('message_type', '!=', 'text'))
        elif self.message_types == 'incoming':
            domain.append(('direction', '=', 'incoming'))
        elif self.message_types == 'outgoing':
            domain.append(('direction', '=', 'outgoing'))
        
        return self.env['whatsapp.message'].search(domain, order='timestamp asc')

    def _export_csv(self, messages):
        """Export messages as CSV"""
        self.ensure_one()
        
        # Prepare CSV data
        csv_data = []
        headers = ['Date', 'Time', 'Direction', 'From', 'To', 'Message Type', 'Message']
        
        if self.include_metadata:
            headers.extend(['Status', 'Message ID'])
        
        if self.include_media:
            headers.append('Media URL')
        
        csv_data.append(headers)
        
        for message in messages:
            row = [
                message.timestamp.strftime('%Y-%m-%d') if message.timestamp else '',
                message.timestamp.strftime('%H:%M:%S') if message.timestamp else '',
                message.direction,
                message.from_name or message.from_number,
                message.to_name or message.to_number,
                message.message_type,
                message.message or '',
            ]
            
            if self.include_metadata:
                row.extend([
                    message.status,
                    message.wa_message_id or '',
                ])
            
            if self.include_media:
                row.append(message.media_url or '')
            
            csv_data.append(row)
        
        # Convert to CSV
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerows(csv_data)
        csv_content = output.getvalue().encode('utf-8')
        
        # Create attachment
        filename = f'whatsapp_messages_{self.account_id.name}_{self.date_from.strftime("%Y%m%d")}_{self.date_to.strftime("%Y%m%d")}.csv'
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(csv_content),
            'mimetype': 'text/csv',
        })
        
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }

    def _export_json(self, messages):
        """Export messages as JSON"""
        self.ensure_one()
        
        # Prepare JSON data
        json_data = {
            'account': self.account_id.name,
            'export_date': fields.Datetime.now().isoformat(),
            'date_from': self.date_from.isoformat(),
            'date_to': self.date_to.isoformat(),
            'total_messages': len(messages),
            'messages': []
        }
        
        for message in messages:
            msg_data = {
                'timestamp': message.timestamp.isoformat() if message.timestamp else None,
                'direction': message.direction,
                'from_number': message.from_number,
                'from_name': message.from_name,
                'to_number': message.to_number,
                'to_name': message.to_name,
                'message_type': message.message_type,
                'message': message.message,
            }
            
            if self.include_metadata:
                msg_data.update({
                    'status': message.status,
                    'wa_message_id': message.wa_message_id,
                    'message_id': message.id,
                })
            
            if self.include_media and message.media_url:
                msg_data['media_url'] = message.media_url
            
            json_data['messages'].append(msg_data)
        
        # Convert to JSON
        import json
        json_content = json.dumps(json_data, indent=2).encode('utf-8')
        
        # Create attachment
        filename = f'whatsapp_messages_{self.account_id.name}_{self.date_from.strftime("%Y%m%d")}_{self.date_to.strftime("%Y%m%d")}.json'
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(json_content),
            'mimetype': 'application/json',
        })
        
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }

    def _export_html(self, messages):
        """Export messages as HTML"""
        self.ensure_one()
        
        # Generate HTML content
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>WhatsApp Messages Export</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .header {{ background-color: #25D366; color: white; padding: 10px; text-align: center; }}
                .message {{ margin: 10px 0; padding: 10px; border-radius: 10px; }}
                .incoming {{ background-color: #f0f0f0; text-align: left; }}
                .outgoing {{ background-color: #dcf8c6; text-align: right; }}
                .timestamp {{ font-size: 12px; color: #666; }}
                .media {{ font-style: italic; color: #666; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>WhatsApp Messages - {self.account_id.name}</h1>
                <p>Export Date: {fields.Datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                <p>Period: {self.date_from.strftime('%Y-%m-%d')} to {self.date_to.strftime('%Y-%m-%d')}</p>
            </div>
        """
        
        current_date = None
        for message in messages:
            msg_date = message.timestamp.strftime('%Y-%m-%d') if message.timestamp else 'Unknown'
            
            # Add date separator if date changed
            if current_date != msg_date:
                html_content += f'<div style="text-align: center; margin: 20px 0; font-weight: bold;">{msg_date}</div>'
                current_date = msg_date
            
            # Add message
            direction_class = 'incoming' if message.direction == 'incoming' else 'outgoing'
            sender = message.from_name or message.from_number
            
            html_content += f"""
            <div class="message {direction_class}">
                <div><strong>{sender}</strong></div>
                <div>{message.message or '<i>Media message</i>'}</div>
                <div class="timestamp">{message.timestamp.strftime('%H:%M:%S') if message.timestamp else 'Unknown time'}</div>
            </div>
            """
        
        html_content += """
        </body>
        </html>
        """
        
        # Create attachment
        filename = f'whatsapp_messages_{self.account_id.name}_{self.date_from.strftime("%Y%m%d")}_{self.date_to.strftime("%Y%m%d")}.html'
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(html_content.encode('utf-8')),
            'mimetype': 'text/html',
        })
        
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }

    def _export_txt(self, messages):
        """Export messages as plain text"""
        self.ensure_one()
        
        # Generate text content
        txt_content = f"""WhatsApp Messages Export
Account: {self.account_id.name}
Export Date: {fields.Datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Period: {self.date_from.strftime('%Y-%m-%d')} to {self.date_to.strftime('%Y-%m-%d')}
Total Messages: {len(messages)}

{'='*50}

"""
        
        current_date = None
        for message in messages:
            msg_date = message.timestamp.strftime('%Y-%m-%d') if message.timestamp else 'Unknown'
            
            # Add date separator if date changed
            if current_date != msg_date:
                txt_content += f'\n--- {msg_date} ---\n\n'
                current_date = msg_date
            
            # Add message
            sender = message.from_name or message.from_number
            time_str = message.timestamp.strftime('%H:%M:%S') if message.timestamp else 'Unknown time'
            direction_arrow = '<-' if message.direction == 'incoming' else '->'
            
            txt_content += f'[{time_str}] {sender} {direction_arrow} {message.message or "[Media message]"}\n'
        
        # Create attachment
        filename = f'whatsapp_messages_{self.account_id.name}_{self.date_from.strftime("%Y%m%d")}_{self.date_to.strftime("%Y%m%d")}.txt'
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(txt_content.encode('utf-8')),
            'mimetype': 'text/plain',
        })
        
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }