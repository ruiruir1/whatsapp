# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import json
import logging

_logger = logging.getLogger(__name__)


class WhatsAppTemplate(models.Model):
    _name = 'whatsapp.template'
    _description = 'WhatsApp Message Template'
    _order = 'name'
    _rec_name = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char('Template Name', required=True, tracking=True)
    code = fields.Char('Template Code', help='Unique code for API access')
    description = fields.Text('Description')
    
    # Template content
    template_type = fields.Selection([
        ('text', 'Text'),
        ('media', 'Media'),
        ('document', 'Document'),
        ('location', 'Location'),
        ('contact', 'Contact'),
        ('list', 'List'),
        ('button', 'Button'),
    ], string='Template Type', default='text', required=True, tracking=True)
    
    content = fields.Text('Template Content', required=True, help='Template content with placeholders')
    variables = fields.Text('Variables', help='JSON array of variable definitions')
    
    # Media template fields
    media_url = fields.Char('Media URL')
    media_type = fields.Selection([
        ('image', 'Image'),
        ('video', 'Video'),
        ('audio', 'Audio'),
        ('document', 'Document'),
    ], string='Media Type')
    
    # Language and localization
    language = fields.Selection([
        ('en', 'English'),
        ('es', 'Spanish'),
        ('fr', 'French'),
        ('de', 'German'),
        ('it', 'Italian'),
        ('pt', 'Portuguese'),
        ('ru', 'Russian'),
        ('zh', 'Chinese'),
        ('ja', 'Japanese'),
        ('ko', 'Korean'),
        ('ar', 'Arabic'),
        ('hi', 'Hindi'),
    ], string='Language', default='en', required=True)
    
    # Template settings
    active = fields.Boolean('Active', default=True, tracking=True)
    is_public = fields.Boolean('Public Template', default=False, help='Available to all users')
    
    # Usage tracking
    usage_count = fields.Integer('Usage Count', default=0, readonly=True)
    last_used = fields.Datetime('Last Used', readonly=True)
    
    # Relations
    account_id = fields.Many2one('whatsapp.account', 'WhatsApp Account', ondelete='cascade')
    user_id = fields.Many2one('res.users', 'Created By', default=lambda self: self.env.user, tracking=True)
    company_id = fields.Many2one('res.company', 'Company', default=lambda self: self.env.company)
    
    # Categories and tags
    category_id = fields.Many2one('whatsapp.template.category', 'Category', ondelete='set null')
    tag_ids = fields.Many2many('whatsapp.template.tag', string='Tags')
    
    _sql_constraints = [
        ('unique_code', 'unique(code)', 'Template code must be unique!'),
    ]

    @api.model
    def create(self, vals):
        # Auto-generate code if not provided
        if not vals.get('code'):
            vals['code'] = self.env['ir.sequence'].next_by_code('whatsapp.template') or self._generate_code(vals.get('name', ''))
        
        return super(WhatsAppTemplate, self).create(vals)

    def _generate_code(self, name):
        """Generate unique code from name"""
        import re
        code = re.sub(r'[^a-zA-Z0-9]', '_', name.lower())
        code = re.sub(r'_+', '_', code).strip('_')
        return code[:50]  # Limit length

    def get_variables(self):
        """Get template variables as list"""
        self.ensure_one()
        if self.variables:
            try:
                return json.loads(self.variables)
            except json.JSONDecodeError:
                return []
        return []

    def set_variables(self, variables):
        """Set template variables from list"""
        self.ensure_one()
        self.variables = json.dumps(variables)

    def render_template(self, variables=None):
        """Render template with variables"""
        self.ensure_one()
        
        content = self.content
        if variables:
            for var_name, var_value in variables.items():
                placeholder = f'{{{{{var_name}}}}}'
                content = content.replace(placeholder, str(var_value))
        
        return content

    def validate_template(self):
        """Validate template content"""
        self.ensure_one()
        
        # Check for valid variables
        import re
        variables = re.findall(r'\{\{(\w+)\}\}', self.content)
        template_vars = [var.get('name') for var in self.get_variables()]
        
        for var in variables:
            if var not in template_vars:
                raise ValidationError(_('Variable "%s" is not defined in template variables.') % var)
        
        return True

    def action_preview(self):
        """Preview template with sample data"""
        self.ensure_one()
        
        # Create sample variables
        sample_vars = {}
        for var in self.get_variables():
            var_name = var.get('name', '')
            var_type = var.get('type', 'text')
            
            if var_type == 'text':
                sample_vars[var_name] = 'Sample Text'
            elif var_type == 'number':
                sample_vars[var_name] = '123'
            elif var_type == 'date':
                sample_vars[var_name] = fields.Date.today().strftime('%Y-%m-%d')
            elif var_type == 'datetime':
                sample_vars[var_name] = fields.Datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            else:
                sample_vars[var_name] = 'Sample Value'
        
        preview_content = self.render_template(sample_vars)
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Template Preview',
            'res_model': 'whatsapp.template.preview',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_template_id': self.id,
                'default_content': preview_content,
                'default_variables': json.dumps(sample_vars),
            }
        }

    def action_use_template(self):
        """Use template in message composer"""
        self.ensure_one()
        
        # Update usage statistics
        self.usage_count += 1
        self.last_used = fields.Datetime.now()
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Send Message',
            'res_model': 'whatsapp.send.message',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_template_id': self.id,
                'default_message': self.content,
                'default_message_type': self.template_type,
            }
        }

    def action_duplicate(self):
        """Duplicate template"""
        self.ensure_one()
        
        copy_vals = {
            'name': _('%s (Copy)') % self.name,
            'code': None,  # Will be auto-generated
        }
        
        new_template = self.copy(copy_vals)
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Template',
            'res_model': 'whatsapp.template',
            'res_id': new_template.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model
    def get_public_templates(self):
        """Get public templates"""
        return self.search([('is_public', '=', True), ('active', '=', True)])

    @api.model
    def get_user_templates(self, user_id=None):
        """Get user templates"""
        if not user_id:
            user_id = self.env.user.id
        
        return self.search([
            ('user_id', '=', user_id),
            ('active', '=', True)
        ])

    @api.model
    def search_templates(self, query, category_id=None, tag_ids=None):
        """Search templates"""
        domain = [
            ('active', '=', True),
            '|',
            ('name', 'ilike', query),
            ('description', 'ilike', query)
        ]
        
        if category_id:
            domain.append(('category_id', '=', category_id))
        
        if tag_ids:
            domain.append(('tag_ids', 'in', tag_ids))
        
        return self.search(domain)


class WhatsAppTemplateCategory(models.Model):
    _name = 'whatsapp.template.category'
    _description = 'WhatsApp Template Category'
    _order = 'name'

    name = fields.Char('Category Name', required=True)
    description = fields.Text('Description')
    color = fields.Integer('Color Index', default=0)
    active = fields.Boolean('Active', default=True)
    
    template_ids = fields.One2many('whatsapp.template', 'category_id', 'Templates')
    template_count = fields.Integer('Template Count', compute='_compute_template_count')
    
    _sql_constraints = [
        ('unique_name', 'unique(name)', 'Category name must be unique!'),
    ]

    @api.depends('template_ids')
    def _compute_template_count(self):
        for category in self:
            category.template_count = len(category.template_ids)


class WhatsAppTemplateTag(models.Model):
    _name = 'whatsapp.template.tag'
    _description = 'WhatsApp Template Tag'
    _order = 'name'

    name = fields.Char('Tag Name', required=True)
    color = fields.Integer('Color Index', default=0)
    active = fields.Boolean('Active', default=True)
    
    template_ids = fields.Many2many('whatsapp.template', string='Templates')
    
    _sql_constraints = [
        ('unique_name', 'unique(name)', 'Tag name must be unique!'),
    ]


class WhatsAppWebhook(models.Model):
    _name = 'whatsapp.webhook'
    _description = 'WhatsApp Webhook'
    _order = 'name'
    _rec_name = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char('Webhook Name', required=True, tracking=True)
    url = fields.Char('Webhook URL', required=True, tracking=True)
    secret = fields.Char('Webhook Secret', help='Secret key for signature verification')
    
    # Account relation
    account_id = fields.Many2one('whatsapp.account', 'WhatsApp Account', required=True, ondelete='cascade')
    
    # Configuration
    active = fields.Boolean('Active', default=True, tracking=True)
    events = fields.Char('Events', default='message,status,qr', help='Comma-separated list of events')
    
    # Security
    verify_signature = fields.Boolean('Verify Signature', default=True)
    timeout = fields.Integer('Timeout (seconds)', default=30)
    retry_count = fields.Integer('Retry Count', default=3)
    
    # Statistics
    total_calls = fields.Integer('Total Calls', default=0, readonly=True)
    successful_calls = fields.Integer('Successful Calls', default=0, readonly=True)
    failed_calls = fields.Integer('Failed Calls', default=0, readonly=True)
    last_call_date = fields.Datetime('Last Call Date', readonly=True)
    last_error = fields.Text('Last Error', readonly=True)
    
    # Company
    company_id = fields.Many2one('res.company', 'Company', related='account_id.company_id', store=True)
    
    def test_webhook(self):
        """Test webhook connection"""
        self.ensure_one()
        
        try:
            import requests
            
            test_data = {
                'event': 'test',
                'timestamp': fields.Datetime.now().isoformat(),
                'data': {
                    'message': 'Test webhook from Odoo WhatsApp module'
                }
            }
            
            headers = {'Content-Type': 'application/json'}
            if self.secret:
                import hmac
                import hashlib
                import json
                
                payload = json.dumps(test_data).encode('utf-8')
                signature = hmac.new(
                    self.secret.encode('utf-8'),
                    payload,
                    hashlib.sha256
                ).hexdigest()
                headers['X-Hub-Signature-256'] = f'sha256={signature}'
            
            response = requests.post(
                self.url,
                json=test_data,
                headers=headers,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                self.message_post(body=_('Webhook test successful'))
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'message': _('Webhook test successful'),
                        'type': 'success',
                    }
                }
            else:
                error_msg = f'HTTP {response.status_code}: {response.text}'
                self.last_error = error_msg
                raise UserError(_('Webhook test failed: %s') % error_msg)
        
        except Exception as e:
            error_msg = str(e)
            self.last_error = error_msg
            _logger.error(f'Webhook test failed: {error_msg}')
            raise UserError(_('Webhook test failed: %s') % error_msg)

    def call_webhook(self, event, data):
        """Call webhook with event data"""
        self.ensure_one()
        
        if not self.active:
            return
        
        try:
            import requests
            import json
            
            payload = {
                'event': event,
                'timestamp': fields.Datetime.now().isoformat(),
                'account_id': self.account_id.id,
                'data': data
            }
            
            headers = {'Content-Type': 'application/json'}
            if self.secret and self.verify_signature:
                import hmac
                import hashlib
                
                payload_str = json.dumps(payload).encode('utf-8')
                signature = hmac.new(
                    self.secret.encode('utf-8'),
                    payload_str,
                    hashlib.sha256
                ).hexdigest()
                headers['X-Hub-Signature-256'] = f'sha256={signature}'
            
            response = requests.post(
                self.url,
                json=payload,
                headers=headers,
                timeout=self.timeout
            )
            
            # Update statistics
            self.total_calls += 1
            self.last_call_date = fields.Datetime.now()
            
            if response.status_code == 200:
                self.successful_calls += 1
                self.last_error = False
                _logger.info(f'Webhook call successful: {self.url}')
            else:
                self.failed_calls += 1
                error_msg = f'HTTP {response.status_code}: {response.text}'
                self.last_error = error_msg
                _logger.error(f'Webhook call failed: {error_msg}')
        
        except Exception as e:
            self.failed_calls += 1
            error_msg = str(e)
            self.last_error = error_msg
            _logger.error(f'Webhook call failed: {error_msg}')

    def get_events_list(self):
        """Get events as list"""
        self.ensure_one()
        if self.events:
            return [event.strip() for event in self.events.split(',')]
        return []

    def set_events_list(self, events):
        """Set events from list"""
        self.ensure_one()
        self.events = ','.join(events)


class WhatsAppAttachment(models.Model):
    _name = 'whatsapp.attachment'
    _description = 'WhatsApp Attachment'
    _order = 'create_date desc'
    _rec_name = 'name'

    name = fields.Char('Attachment Name', required=True)
    file_name = fields.Char('File Name')
    file_size = fields.Integer('File Size (bytes)')
    mime_type = fields.Char('MIME Type')
    
    # File data
    attachment_id = fields.Many2one('ir.attachment', 'Attachment', required=True, ondelete='cascade')
    file_data = fields.Binary('File Data', related='attachment_id.datas', readonly=True)
    
    # WhatsApp specific
    wa_media_id = fields.Char('WhatsApp Media ID')
    media_type = fields.Selection([
        ('image', 'Image'),
        ('video', 'Video'),
        ('audio', 'Audio'),
        ('voice', 'Voice Note'),
        ('document', 'Document'),
        ('sticker', 'Sticker'),
    ], string='Media Type', required=True)
    
    # Relations
    message_id = fields.Many2one('whatsapp.message', 'Message', ondelete='cascade')
    account_id = fields.Many2one('whatsapp.account', 'Account', related='message_id.account_id', store=True)
    
    # Metadata
    width = fields.Integer('Width (px)')
    height = fields.Integer('Height (px)')
    duration = fields.Integer('Duration (seconds)')
    
    # Status
    status = fields.Selection([
        ('uploading', 'Uploading'),
        ('uploaded', 'Uploaded'),
        ('failed', 'Failed'),
    ], string='Status', default='uploading')
    
    # Company
    company_id = fields.Many2one('res.company', 'Company', related='account_id.company_id', store=True)

    @api.model
    def create(self, vals):
        attachment = super(WhatsAppAttachment, self).create(vals)
        
        # Auto-detect media type from MIME type
        if not vals.get('media_type') and attachment.mime_type:
            attachment.media_type = attachment._detect_media_type(attachment.mime_type)
        
        return attachment

    def _detect_media_type(self, mime_type):
        """Detect media type from MIME type"""
        if mime_type.startswith('image/'):
            return 'image'
        elif mime_type.startswith('video/'):
            return 'video'
        elif mime_type.startswith('audio/'):
            return 'audio'
        else:
            return 'document'

    def action_download(self):
        """Download attachment"""
        self.ensure_one()
        
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{self.attachment_id.id}?download=true',
            'target': 'new',
        }

    def action_preview(self):
        """Preview attachment"""
        self.ensure_one()
        
        if self.media_type == 'image':
            return {
                'type': 'ir.actions.act_window',
                'name': 'Image Preview',
                'res_model': 'whatsapp.attachment.preview',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_attachment_id': self.id,
                }
            }
        else:
            return self.action_download()

    def get_file_url(self):
        """Get file URL"""
        self.ensure_one()
        return f'/web/content/{self.attachment_id.id}'

    def get_thumbnail_url(self):
        """Get thumbnail URL"""
        self.ensure_one()
        if self.media_type == 'image':
            return f'/web/image/{self.attachment_id.id}/100x100'
        return None