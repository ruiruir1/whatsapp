# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import logging

_logger = logging.getLogger(__name__)


class WhatsAppGroupAddMember(models.TransientModel):
    _name = 'whatsapp.group.add.member'
    _description = 'Add Member to WhatsApp Group'
    
    # Group Information
    group_id = fields.Many2one('whatsapp.group', 'Group', required=True)
    group_name = fields.Char(related='group_id.name', readonly=True)
    group_member_count = fields.Integer(related='group_id.member_count', readonly=True)
    
    # Member Selection
    add_method = fields.Selection([
        ('contacts', 'From Contacts'),
        ('numbers', 'Phone Numbers'),
        ('partners', 'From Partners'),
    ], string='Add Method', default='contacts', required=True)
    
    # Contact Selection
    contact_ids = fields.Many2many(
        'whatsapp.contact',
        'whatsapp_group_add_member_contact_rel',
        'wizard_id',
        'contact_id',
        string='Contacts',
        domain="[('account_id', '=', account_id), ('status', '=', 'active')]"
    )
    
    # Phone Numbers
    phone_numbers = fields.Text(
        string='Phone Numbers',
        placeholder='Enter phone numbers (one per line):\n+1234567890\n+0987654321'
    )
    
    # Partner Selection
    partner_ids = fields.Many2many(
        'res.partner',
        'whatsapp_group_add_member_partner_rel',
        'wizard_id',
        'partner_id',
        string='Partners',
        domain="[('whatsapp_number', '!=', False)]"
    )
    
    # Options
    make_admin = fields.Boolean(
        string='Make Admin',
        default=False,
        help='Grant admin privileges to added members'
    )
    
    send_welcome_message = fields.Boolean(
        string='Send Welcome Message',
        default=True,
        help='Send a welcome message to new members'
    )
    
    welcome_message = fields.Text(
        string='Welcome Message',
        default='Welcome to the group! We\'re glad to have you here.'
    )
    
    # Related Fields
    account_id = fields.Many2one(related='group_id.account_id', readonly=True)
    
    # Results
    result_message = fields.Text('Result', readonly=True)
    success_count = fields.Integer('Success Count', readonly=True)
    error_count = fields.Integer('Error Count', readonly=True)
    
    @api.depends('add_method')
    def _compute_domain(self):
        for record in self:
            if record.add_method == 'contacts':
                record.contact_ids = [(5, 0, 0)]  # Clear selection
            elif record.add_method == 'partners':
                record.partner_ids = [(5, 0, 0)]  # Clear selection
    
    def action_add_members(self):
        """Add members to the group"""
        self.ensure_one()
        
        if not self.group_id.is_member:
            raise UserError(_('You must be a member of the group to add new members.'))
        
        members_to_add = self._get_members_to_add()
        
        if not members_to_add:
            raise UserError(_('No members selected to add.'))
        
        success_count = 0
        error_count = 0
        results = []
        
        for member_data in members_to_add:
            try:
                # Add member to group
                result = self._add_member_to_group(member_data)
                if result:
                    success_count += 1
                    results.append(f"✓ {member_data['name']} ({member_data['phone']}) added successfully")
                else:
                    error_count += 1
                    results.append(f"✗ Failed to add {member_data['name']} ({member_data['phone']})")
            except Exception as e:
                error_count += 1
                results.append(f"✗ Error adding {member_data['name']}: {str(e)}")
                _logger.error(f"Error adding member {member_data['name']} to group {self.group_id.name}: {e}")
        
        # Update results
        self.success_count = success_count
        self.error_count = error_count
        self.result_message = '\n'.join(results)
        
        # Send welcome messages if requested
        if self.send_welcome_message and self.welcome_message:
            self._send_welcome_messages(members_to_add)
        
        # Refresh group member count
        self.group_id.action_sync_members()
        
        return self._show_results()
    
    def _get_members_to_add(self):
        """Get list of members to add based on selection method"""
        members = []
        
        if self.add_method == 'contacts':
            for contact in self.contact_ids:
                members.append({
                    'name': contact.name,
                    'phone': contact.phone_number,
                    'contact_id': contact.id,
                    'partner_id': contact.partner_id.id if contact.partner_id else False,
                })
        
        elif self.add_method == 'numbers':
            if self.phone_numbers:
                lines = self.phone_numbers.strip().split('\n')
                for line in lines:
                    phone = line.strip()
                    if phone:
                        # Try to find existing contact
                        contact = self.env['whatsapp.contact'].search([
                            ('phone_number', '=', phone),
                            ('account_id', '=', self.account_id.id)
                        ], limit=1)
                        
                        name = contact.name if contact else phone
                        members.append({
                            'name': name,
                            'phone': phone,
                            'contact_id': contact.id if contact else False,
                            'partner_id': contact.partner_id.id if contact and contact.partner_id else False,
                        })
        
        elif self.add_method == 'partners':
            for partner in self.partner_ids:
                members.append({
                    'name': partner.name,
                    'phone': partner.whatsapp_number,
                    'contact_id': False,
                    'partner_id': partner.id,
                })
        
        return members
    
    def _add_member_to_group(self, member_data):
        """Add a single member to the group"""
        try:
            # Check if member already exists
            existing_member = self.env['whatsapp.group.member'].search([
                ('group_id', '=', self.group_id.id),
                ('phone_number', '=', member_data['phone'])
            ], limit=1)
            
            if existing_member:
                if existing_member.status == 'active':
                    return False  # Already a member
                else:
                    # Reactivate member
                    existing_member.write({
                        'status': 'active',
                        'is_admin': self.make_admin,
                        'joined_at': fields.Datetime.now(),
                    })
                    return True
            
            # Create new member
            member_vals = {
                'group_id': self.group_id.id,
                'name': member_data['name'],
                'phone_number': member_data['phone'],
                'contact_id': member_data['contact_id'],
                'is_admin': self.make_admin,
                'status': 'active',
                'joined_at': fields.Datetime.now(),
            }
            
            member = self.env['whatsapp.group.member'].create(member_vals)
            
            # Add member via WhatsApp API
            self._add_member_via_api(member_data)
            
            return True
            
        except Exception as e:
            _logger.error(f"Error adding member {member_data['name']} to group: {e}")
            raise
    
    def _add_member_via_api(self, member_data):
        """Add member via WhatsApp API"""
        try:
            # Call WhatsApp API to add member
            account = self.group_id.account_id
            
            # This would call the actual WhatsApp API
            # For now, we'll just log the action
            _logger.info(f"Adding member {member_data['name']} ({member_data['phone']}) to group {self.group_id.name}")
            
            # TODO: Implement actual WhatsApp API call
            # Example:
            # response = account.call_whatsapp_api('addMember', {
            #     'groupId': self.group_id.wa_group_id,
            #     'participantId': member_data['phone'] + '@c.us'
            # })
            
            return True
            
        except Exception as e:
            _logger.error(f"Error calling WhatsApp API to add member: {e}")
            raise
    
    def _send_welcome_messages(self, members):
        """Send welcome messages to new members"""
        if not self.welcome_message:
            return
        
        for member_data in members:
            try:
                # Send welcome message
                message_vals = {
                    'account_id': self.account_id.id,
                    'group_id': self.group_id.id,
                    'message': self.welcome_message,
                    'message_type': 'text',
                    'direction': 'outgoing',
                    'to_number': member_data['phone'],
                    'to_name': member_data['name'],
                    'status': 'pending',
                }
                
                # Create message record
                message = self.env['whatsapp.message'].create(message_vals)
                
                # Send message via API
                # TODO: Implement actual message sending
                _logger.info(f"Sending welcome message to {member_data['name']}")
                
            except Exception as e:
                _logger.error(f"Error sending welcome message to {member_data['name']}: {e}")
    
    def _show_results(self):
        """Show results of the operation"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Add Members - Results',
            'res_model': 'whatsapp.group.add.member',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
    
    def action_done(self):
        """Close the wizard"""
        return {'type': 'ir.actions.act_window_close'}


class WhatsAppGroupCreateGroup(models.TransientModel):
    _name = 'whatsapp.group.create'
    _description = 'Create WhatsApp Group'
    
    # Group Information
    name = fields.Char('Group Name', required=True)
    description = fields.Text('Description')
    account_id = fields.Many2one('whatsapp.account', 'WhatsApp Account', required=True)
    
    # Members
    member_ids = fields.Many2many(
        'whatsapp.contact',
        'whatsapp_group_create_member_rel',
        'wizard_id',
        'contact_id',
        string='Initial Members',
        domain="[('account_id', '=', account_id), ('status', '=', 'active')]"
    )
    
    # Options
    make_members_admin = fields.Boolean(
        string='Make Members Admin',
        default=False,
        help='Grant admin privileges to initial members'
    )
    
    # Results
    group_id = fields.Many2one('whatsapp.group', 'Created Group', readonly=True)
    result_message = fields.Text('Result', readonly=True)
    
    @api.constrains('name')
    def _check_name(self):
        for record in self:
            if len(record.name) < 3:
                raise ValidationError(_('Group name must be at least 3 characters long.'))
            if len(record.name) > 100:
                raise ValidationError(_('Group name cannot exceed 100 characters.'))
    
    def action_create_group(self):
        """Create the WhatsApp group"""
        self.ensure_one()
        
        if not self.account_id.status == 'ready':
            raise UserError(_('WhatsApp account must be ready to create groups.'))
        
        try:
            # Create group via WhatsApp API
            wa_group_id = self._create_group_via_api()
            
            # Create group record
            group_vals = {
                'name': self.name,
                'description': self.description,
                'account_id': self.account_id.id,
                'wa_group_id': wa_group_id,
                'group_id': wa_group_id,
                'is_member': True,
                'is_admin': True,
                'is_owner': True,
                'status': 'active',
                'created_at': fields.Datetime.now(),
            }
            
            group = self.env['whatsapp.group'].create(group_vals)
            self.group_id = group.id
            
            # Add initial members
            if self.member_ids:
                self._add_initial_members(group)
            
            self.result_message = f"Group '{self.name}' created successfully with {len(self.member_ids)} members."
            
            return self._show_results()
            
        except Exception as e:
            _logger.error(f"Error creating group {self.name}: {e}")
            raise UserError(_('Failed to create group: %s') % str(e))
    
    def _create_group_via_api(self):
        """Create group via WhatsApp API"""
        try:
            # Call WhatsApp API to create group
            account = self.account_id
            
            # This would call the actual WhatsApp API
            # For now, we'll generate a mock group ID
            import uuid
            wa_group_id = f"group_{uuid.uuid4().hex[:8]}@g.us"
            
            _logger.info(f"Creating group {self.name} via WhatsApp API")
            
            # TODO: Implement actual WhatsApp API call
            # Example:
            # response = account.call_whatsapp_api('createGroup', {
            #     'name': self.name,
            #     'participants': [member.phone_number + '@c.us' for member in self.member_ids]
            # })
            # wa_group_id = response.get('groupId')
            
            return wa_group_id
            
        except Exception as e:
            _logger.error(f"Error calling WhatsApp API to create group: {e}")
            raise
    
    def _add_initial_members(self, group):
        """Add initial members to the group"""
        for contact in self.member_ids:
            try:
                member_vals = {
                    'group_id': group.id,
                    'name': contact.name,
                    'phone_number': contact.phone_number,
                    'contact_id': contact.id,
                    'is_admin': self.make_members_admin,
                    'status': 'active',
                    'joined_at': fields.Datetime.now(),
                }
                
                self.env['whatsapp.group.member'].create(member_vals)
                
            except Exception as e:
                _logger.error(f"Error adding initial member {contact.name} to group: {e}")
    
    def _show_results(self):
        """Show results of the operation"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Create Group - Results',
            'res_model': 'whatsapp.group.create',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
    
    def action_view_group(self):
        """View the created group"""
        self.ensure_one()
        if not self.group_id:
            raise UserError(_('No group was created.'))
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'WhatsApp Group',
            'res_model': 'whatsapp.group',
            'res_id': self.group_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
    
    def action_done(self):
        """Close the wizard"""
        return {'type': 'ir.actions.act_window_close'}
