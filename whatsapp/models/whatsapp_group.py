# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import logging

_logger = logging.getLogger(__name__)


class WhatsAppGroup(models.Model):
    _name = 'whatsapp.group'
    _description = 'WhatsApp Group'
    _order = 'name'
    _rec_name = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # Basic info
    name = fields.Char('Group Name', required=True, tracking=True)
    description = fields.Text('Description', tracking=True)
    group_id = fields.Char('Group ID', required=True, index=True, help='WhatsApp group ID')
    wa_group_id = fields.Char('WhatsApp Group ID', help='Full WhatsApp group ID (id@g.us)')
    
    # Account relation
    account_id = fields.Many2one('whatsapp.account', 'WhatsApp Account', required=True, ondelete='cascade')
    
    # Group settings
    is_member = fields.Boolean('Is Member', default=True, tracking=True)
    is_admin = fields.Boolean('Is Admin', default=False, tracking=True)
    is_owner = fields.Boolean('Is Owner', default=False, tracking=True)
    
    # Group configuration
    only_admins_can_send = fields.Boolean('Only Admins Can Send', default=False, tracking=True)
    only_admins_can_edit = fields.Boolean('Only Admins Can Edit Info', default=False, tracking=True)
    disappearing_messages = fields.Boolean('Disappearing Messages', default=False, tracking=True)
    
    # Status
    status = fields.Selection([
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('left', 'Left'),
        ('removed', 'Removed'),
    ], string='Status', default='active', tracking=True)
    
    # Statistics
    member_count = fields.Integer('Member Count', default=0, tracking=True)
    admin_count = fields.Integer('Admin Count', default=0)
    message_count = fields.Integer('Message Count', compute='_compute_message_count', store=True)
    
    # Timestamps
    created_date = fields.Datetime('Created Date', default=fields.Datetime.now)
    joined_date = fields.Datetime('Joined Date', default=fields.Datetime.now)
    left_date = fields.Datetime('Left Date')
    last_activity = fields.Datetime('Last Activity', tracking=True)
    
    # Group avatar
    avatar_url = fields.Char('Avatar URL')
    avatar_image = fields.Binary('Avatar Image', attachment=True)
    
    # Relations
    message_ids = fields.One2many('whatsapp.message', 'group_id', 'Messages')
    member_ids = fields.One2many('whatsapp.group.member', 'group_id', 'Members')
    
    # Business integration
    partner_id = fields.Many2one('res.partner', 'Related Partner', ondelete='set null')
    project_id = fields.Many2one('project.project', 'Related Project', ondelete='set null')
    
    # Company
    company_id = fields.Many2one('res.company', 'Company', related='account_id.company_id', store=True)
    
    _sql_constraints = [
        ('unique_group_id_account', 'unique(group_id, account_id)', 'Group ID must be unique per account!'),
    ]

    @api.depends('message_ids')
    def _compute_message_count(self):
        for group in self:
            group.message_count = len(group.message_ids)

    @api.model
    def create(self, vals):
        # Generate WA group ID
        if not vals.get('wa_group_id') and vals.get('group_id'):
            vals['wa_group_id'] = f"{vals['group_id']}@g.us"
        
        group = super(WhatsAppGroup, self).create(vals)
        
        # Sync group members
        group._sync_members()
        
        return group

    def _sync_members(self):
        """Sync group members from WhatsApp"""
        self.ensure_one()
        
        try:
            # Get group info from WhatsApp API
            group_info = self.account_id._get_group_info(self.group_id)
            
            if not group_info:
                return
            
            # Update group info
            self.write({
                'name': group_info.get('name', self.name),
                'description': group_info.get('desc', ''),
                'member_count': len(group_info.get('participants', [])),
                'only_admins_can_send': group_info.get('only_admins_can_send', False),
                'only_admins_can_edit': group_info.get('only_admins_can_edit', False),
            })
            
            # Clear existing members
            self.member_ids.unlink()
            
            # Add members
            for participant in group_info.get('participants', []):
                member_vals = {
                    'group_id': self.id,
                    'phone_number': participant.get('id', '').replace('@c.us', ''),
                    'name': participant.get('name') or participant.get('pushname'),
                    'is_admin': participant.get('is_admin', False),
                    'is_owner': participant.get('is_owner', False),
                    'joined_date': fields.Datetime.now(),
                }
                
                # Find or create contact
                contact = self.env['whatsapp.contact'].search([
                    ('account_id', '=', self.account_id.id),
                    ('phone_number', '=', member_vals['phone_number'])
                ], limit=1)
                
                if not contact:
                    contact = self.env['whatsapp.contact'].create({
                        'account_id': self.account_id.id,
                        'name': member_vals['name'] or member_vals['phone_number'],
                        'phone_number': member_vals['phone_number'],
                    })
                
                member_vals['contact_id'] = contact.id
                self.env['whatsapp.group.member'].create(member_vals)
            
            # Update admin count
            self.admin_count = len(self.member_ids.filtered('is_admin'))
            
        except Exception as e:
            _logger.error(f'Error syncing group members: {e}')

    def action_send_message(self):
        """Send message to group"""
        self.ensure_one()
        
        if not self.is_member:
            raise UserError(_('You are not a member of this group.'))
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Send Message to Group',
            'res_model': 'whatsapp.send.message',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_account_id': self.account_id.id,
                'default_group_id': self.id,
                'default_to_number': self.wa_group_id,
            }
        }

    def action_leave_group(self):
        """Leave group"""
        self.ensure_one()
        
        if not self.is_member:
            raise UserError(_('You are not a member of this group.'))
        
        try:
            # Call WhatsApp API to leave group
            self.account_id._leave_group(self.group_id)
            
            self.write({
                'is_member': False,
                'is_admin': False,
                'is_owner': False,
                'status': 'left',
                'left_date': fields.Datetime.now(),
            })
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': _('Left group successfully'),
                    'type': 'success',
                }
            }
            
        except Exception as e:
            _logger.error(f'Error leaving group: {e}')
            raise UserError(_('Error leaving group: %s') % str(e))

    def action_sync_members(self):
        """Sync group members"""
        self.ensure_one()
        
        try:
            self._sync_members()
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': _('Group members synced successfully'),
                    'type': 'success',
                }
            }
            
        except Exception as e:
            _logger.error(f'Error syncing members: {e}')
            raise UserError(_('Error syncing members: %s') % str(e))

    def action_add_member(self):
        """Add member to group"""
        self.ensure_one()
        
        if not self.is_admin:
            raise UserError(_('Only admins can add members.'))
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Add Member to Group',
            'res_model': 'whatsapp.group.add.member',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_group_id': self.id,
            }
        }

    def action_remove_member(self, member_id):
        """Remove member from group"""
        self.ensure_one()
        
        if not self.is_admin:
            raise UserError(_('Only admins can remove members.'))
        
        member = self.env['whatsapp.group.member'].browse(member_id)
        if not member.exists():
            raise UserError(_('Member not found.'))
        
        try:
            # Call WhatsApp API to remove member
            self.account_id._remove_group_member(self.group_id, member.phone_number)
            
            member.unlink()
            self.member_count -= 1
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': _('Member removed successfully'),
                    'type': 'success',
                }
            }
            
        except Exception as e:
            _logger.error(f'Error removing member: {e}')
            raise UserError(_('Error removing member: %s') % str(e))

    def action_view_messages(self):
        """View group messages"""
        self.ensure_one()
        
        return {
            'type': 'ir.actions.act_window',
            'name': f'Messages in {self.name}',
            'res_model': 'whatsapp.message',
            'view_mode': 'tree,form',
            'domain': [('group_id', '=', self.id)],
            'context': {
                'default_account_id': self.account_id.id,
                'default_group_id': self.id,
            }
        }

    def action_open_chat(self):
        """Open group chat"""
        self.ensure_one()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'whatsapp_chat',
            'params': {
                'account_id': self.account_id.id,
                'group_id': self.id,
            }
        }

    def action_create_project(self):
        """Create project from group"""
        self.ensure_one()
        
        if self.project_id:
            return self.project_id.get_formview_action()
        
        project_vals = {
            'name': self.name,
            'description': self.description,
            'user_id': self.account_id.user_id.id,
        }
        
        project = self.env['project.project'].create(project_vals)
        self.project_id = project.id
        
        return project.get_formview_action()

    @api.model
    def sync_groups_from_whatsapp(self, account_id):
        """Sync groups from WhatsApp"""
        account = self.env['whatsapp.account'].browse(account_id)
        
        if not account.exists():
            return
        
        try:
            # Get groups from WhatsApp API
            groups_data = account._get_groups()
            
            for group_data in groups_data:
                group_id = group_data.get('id', '').replace('@g.us', '')
                
                # Check if group exists
                existing_group = self.search([
                    ('account_id', '=', account_id),
                    ('group_id', '=', group_id)
                ], limit=1)
                
                group_vals = {
                    'account_id': account_id,
                    'group_id': group_id,
                    'wa_group_id': group_data.get('id'),
                    'name': group_data.get('name', 'Unknown Group'),
                    'description': group_data.get('desc', ''),
                    'member_count': len(group_data.get('participants', [])),
                    'is_member': True,
                    'last_activity': fields.Datetime.now(),
                }
                
                if existing_group:
                    existing_group.write(group_vals)
                    existing_group._sync_members()
                else:
                    group = self.create(group_vals)
                    group._sync_members()
            
            return True
            
        except Exception as e:
            _logger.error(f'Error syncing groups: {e}')
            return False


class WhatsAppGroupMember(models.Model):
    _name = 'whatsapp.group.member'
    _description = 'WhatsApp Group Member'
    _order = 'name'
    _rec_name = 'name'

    # Basic info
    name = fields.Char('Name', required=True)
    phone_number = fields.Char('Phone Number', required=True, index=True)
    
    # Group and contact relations
    group_id = fields.Many2one('whatsapp.group', 'Group', required=True, ondelete='cascade')
    contact_id = fields.Many2one('whatsapp.contact', 'Contact', ondelete='cascade')
    
    # Member role
    is_admin = fields.Boolean('Is Admin', default=False)
    is_owner = fields.Boolean('Is Owner', default=False)
    
    # Status
    status = fields.Selection([
        ('active', 'Active'),
        ('removed', 'Removed'),
        ('left', 'Left'),
    ], string='Status', default='active')
    
    # Timestamps
    joined_date = fields.Datetime('Joined Date', default=fields.Datetime.now)
    removed_date = fields.Datetime('Removed Date')
    
    # Related fields
    account_id = fields.Many2one('whatsapp.account', 'Account', related='group_id.account_id', store=True)
    
    _sql_constraints = [
        ('unique_member_group', 'unique(phone_number, group_id)', 'Member must be unique per group!'),
    ]

    @api.model
    def create(self, vals):
        # Link with contact if exists
        if vals.get('phone_number') and vals.get('account_id'):
            contact = self.env['whatsapp.contact'].search([
                ('account_id', '=', vals['account_id']),
                ('phone_number', '=', vals['phone_number'])
            ], limit=1)
            
            if contact:
                vals['contact_id'] = contact.id
                if not vals.get('name'):
                    vals['name'] = contact.name
        
        return super(WhatsAppGroupMember, self).create(vals)

    def action_make_admin(self):
        """Make member admin"""
        self.ensure_one()
        
        if not self.group_id.is_admin:
            raise UserError(_('Only admins can make other members admin.'))
        
        try:
            # Call WhatsApp API to make admin
            self.group_id.account_id._make_group_admin(self.group_id.group_id, self.phone_number)
            
            self.is_admin = True
            self.group_id.admin_count += 1
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': _('Member made admin successfully'),
                    'type': 'success',
                }
            }
            
        except Exception as e:
            _logger.error(f'Error making member admin: {e}')
            raise UserError(_('Error making member admin: %s') % str(e))

    def action_remove_admin(self):
        """Remove admin privileges"""
        self.ensure_one()
        
        if not self.group_id.is_admin:
            raise UserError(_('Only admins can remove admin privileges.'))
        
        if self.is_owner:
            raise UserError(_('Cannot remove admin privileges from group owner.'))
        
        try:
            # Call WhatsApp API to remove admin
            self.group_id.account_id._remove_group_admin(self.group_id.group_id, self.phone_number)
            
            self.is_admin = False
            self.group_id.admin_count -= 1
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': _('Admin privileges removed successfully'),
                    'type': 'success',
                }
            }
            
        except Exception as e:
            _logger.error(f'Error removing admin: {e}')
            raise UserError(_('Error removing admin: %s') % str(e))

    def action_remove_from_group(self):
        """Remove member from group"""
        self.ensure_one()
        
        return self.group_id.action_remove_member(self.id)

    def action_send_message(self):
        """Send private message to member"""
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
                'default_contact_id': self.contact_id.id if self.contact_id else None,
            }
        }