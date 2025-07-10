/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";

export class WhatsAppChatWindow extends Component {
    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.whatsapp = useService("whatsapp");
        
        this.chatContainer = useRef("chatContainer");
        this.messageInput = useRef("messageInput");
        
        this.state = useState({
            accountId: this.props.accountId,
            contactId: this.props.contactId,
            groupId: this.props.groupId,
            messages: [],
            contacts: [],
            groups: [],
            activeChat: null,
            newMessage: "",
            isLoading: false,
            isTyping: false,
            attachment: null,
            showEmojiPicker: false,
            messageType: "text",
        });

        onMounted(() => {
            this.loadChatData();
            this.setupEventListeners();
        });

        onWillUnmount(() => {
            this.cleanup();
        });
    }

    async loadChatData() {
        try {
            this.state.isLoading = true;
            
            // Load contacts
            const contacts = await this.orm.searchRead(
                "whatsapp.contact",
                [["account_id", "=", this.state.accountId], ["status", "=", "active"]],
                ["name", "phone_number", "profile_pic_url", "last_seen", "message_count"]
            );
            
            // Load groups
            const groups = await this.orm.searchRead(
                "whatsapp.group",
                [["account_id", "=", this.state.accountId], ["is_member", "=", true]],
                ["name", "group_id", "member_count", "last_activity"]
            );
            
            this.state.contacts = contacts;
            this.state.groups = groups;
            
            // Set active chat
            if (this.state.contactId) {
                const contact = contacts.find(c => c.id === this.state.contactId);
                if (contact) {
                    this.state.activeChat = { type: "contact", data: contact };
                    await this.loadMessages();
                }
            } else if (this.state.groupId) {
                const group = groups.find(g => g.id === this.state.groupId);
                if (group) {
                    this.state.activeChat = { type: "group", data: group };
                    await this.loadMessages();
                }
            }
            
        } catch (error) {
            console.error("Error loading chat data:", error);
            this.notification.add("Error loading chat data", { type: "danger" });
        } finally {
            this.state.isLoading = false;
        }
    }

    async loadMessages() {
        if (!this.state.activeChat) return;
        
        try {
            const domain = [["account_id", "=", this.state.accountId]];
            
            if (this.state.activeChat.type === "contact") {
                domain.push(["contact_id", "=", this.state.activeChat.data.id]);
            } else if (this.state.activeChat.type === "group") {
                domain.push(["group_id", "=", this.state.activeChat.data.id]);
            }
            
            const messages = await this.orm.searchRead(
                "whatsapp.message",
                domain,
                [
                    "message", "message_type", "direction", "from_number", "to_number",
                    "from_name", "timestamp", "status", "attachment_id", "media_url"
                ],
                { order: "timestamp desc", limit: 50 }
            );
            
            this.state.messages = messages.reverse();
            
            // Scroll to bottom
            this.scrollToBottom();
            
        } catch (error) {
            console.error("Error loading messages:", error);
            this.notification.add("Error loading messages", { type: "danger" });
        }
    }

    setupEventListeners() {
        // Listen for WhatsApp events
        if (this.whatsapp.state.socket) {
            this.whatsapp.state.socket.on("message", (data) => {
                this.handleIncomingMessage(data);
            });
            
            this.whatsapp.state.socket.on("message_sent", (data) => {
                this.handleSentMessage(data);
            });
            
            this.whatsapp.state.socket.on("message_ack", (data) => {
                this.handleMessageAck(data);
            });
        }
    }

    cleanup() {
        // Remove event listeners
        if (this.whatsapp.state.socket) {
            this.whatsapp.state.socket.off("message");
            this.whatsapp.state.socket.off("message_sent");
            this.whatsapp.state.socket.off("message_ack");
        }
    }

    handleIncomingMessage(data) {
        // Check if message is for active chat
        const messageFrom = data.message.from.replace("@c.us", "");
        const isForActiveChat = this.state.activeChat &&
            ((this.state.activeChat.type === "contact" && this.state.activeChat.data.phone_number === messageFrom) ||
             (this.state.activeChat.type === "group" && data.message.from.endsWith("@g.us")));
        
        if (isForActiveChat) {
            this.state.messages.push({
                message: data.message.body,
                message_type: data.message.type,
                direction: "incoming",
                from_name: data.message.contact.name,
                from_number: messageFrom,
                timestamp: new Date(data.message.timestamp * 1000),
                status: "delivered"
            });
            
            this.scrollToBottom();
            this.playNotificationSound();
        }
    }

    handleSentMessage(data) {
        // Update message status
        const messageIndex = this.state.messages.findIndex(
            msg => msg.temp_id === data.temp_id
        );
        
        if (messageIndex !== -1) {
            this.state.messages[messageIndex].status = "sent";
            this.state.messages[messageIndex].wa_message_id = data.message.id;
        }
    }

    handleMessageAck(data) {
        // Update message status
        const messageIndex = this.state.messages.findIndex(
            msg => msg.wa_message_id === data.messageId
        );
        
        if (messageIndex !== -1) {
            this.state.messages[messageIndex].status = data.ack;
        }
    }

    async selectChat(chat) {
        this.state.activeChat = chat;
        await this.loadMessages();
    }

    async sendMessage() {
        if (!this.state.newMessage.trim() && !this.state.attachment) return;
        if (!this.state.activeChat) return;
        
        try {
            const toNumber = this.state.activeChat.type === "contact" 
                ? this.state.activeChat.data.phone_number 
                : this.state.activeChat.data.wa_group_id;
            
            // Create temporary message
            const tempId = Date.now();
            const tempMessage = {
                id: tempId,
                temp_id: tempId,
                message: this.state.newMessage,
                message_type: this.state.messageType,
                direction: "outgoing",
                timestamp: new Date(),
                status: "pending"
            };
            
            this.state.messages.push(tempMessage);
            
            // Clear input
            const message = this.state.newMessage;
            this.state.newMessage = "";
            this.state.attachment = null;
            
            this.scrollToBottom();
            
            // Send message
            await this.whatsapp.sendMessage(toNumber, message, this.state.messageType, this.state.attachment);
            
        } catch (error) {
            console.error("Error sending message:", error);
            this.notification.add("Error sending message", { type: "danger" });
        }
    }

    onMessageInput(event) {
        this.state.newMessage = event.target.value;
        
        // Handle Enter key
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            this.sendMessage();
        }
    }

    onFileUpload(event) {
        const file = event.target.files[0];
        if (file) {
            // Check file size (50MB limit)
            if (file.size > 50 * 1024 * 1024) {
                this.notification.add("File size too large. Maximum 50MB allowed.", { type: "danger" });
                return;
            }
            
            // Set attachment
            this.state.attachment = file;
            
            // Set message type based on file type
            if (file.type.startsWith("image/")) {
                this.state.messageType = "image";
            } else if (file.type.startsWith("video/")) {
                this.state.messageType = "video";
            } else if (file.type.startsWith("audio/")) {
                this.state.messageType = "audio";
            } else {
                this.state.messageType = "document";
            }
            
            this.notification.add(`File selected: ${file.name}`, { type: "info" });
        }
    }

    removeAttachment() {
        this.state.attachment = null;
        this.state.messageType = "text";
    }

    scrollToBottom() {
        setTimeout(() => {
            if (this.chatContainer.el) {
                this.chatContainer.el.scrollTop = this.chatContainer.el.scrollHeight;
            }
        }, 100);
    }

    playNotificationSound() {
        try {
            const audio = new Audio("/whatsapp/static/audio/notification.mp3");
            audio.play().catch(e => console.log("Could not play notification sound:", e));
        } catch (error) {
            console.log("Could not play notification sound:", error);
        }
    }

    formatMessageTime(timestamp) {
        const date = new Date(timestamp);
        const now = new Date();
        
        if (date.toDateString() === now.toDateString()) {
            return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        } else {
            return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
        }
    }

    getMessageStatusIcon(status) {
        switch (status) {
            case "pending":
                return "fa-clock-o";
            case "sent":
                return "fa-check";
            case "delivered":
                return "fa-check-double";
            case "read":
                return "fa-check-double text-primary";
            case "failed":
                return "fa-exclamation-triangle text-danger";
            default:
                return "fa-clock-o";
        }
    }

    toggleEmojiPicker() {
        this.state.showEmojiPicker = !this.state.showEmojiPicker;
    }

    insertEmoji(emoji) {
        this.state.newMessage += emoji;
        this.state.showEmojiPicker = false;
        this.messageInput.el.focus();
    }

    static template = "whatsapp.ChatWindow";
    static components = {};
    static props = ["accountId", "contactId?", "groupId?"];
}