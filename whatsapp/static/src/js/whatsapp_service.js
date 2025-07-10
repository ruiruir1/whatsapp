/** @odoo-module **/

import { registry } from "@web/core/registry";
import { reactive } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";

export const whatsAppService = {
    dependencies: ["orm", "notification", "bus_service"],
    
    start(env, { orm, notification, bus_service }) {
        const state = reactive({
            accounts: [],
            activeAccount: null,
            messages: [],
            contacts: [],
            groups: [],
            isConnected: false,
            socket: null,
        });

        async function initializeService() {
            try {
                // Load WhatsApp accounts
                await loadAccounts();
                
                // Initialize socket connection
                initializeSocket();
                
            } catch (error) {
                console.error("Error initializing WhatsApp service:", error);
                notification.add("Error initializing WhatsApp service", { type: "danger" });
            }
        }

        async function loadAccounts() {
            try {
                const accounts = await orm.searchRead(
                    "whatsapp.account",
                    [["active", "=", true]],
                    ["name", "phone_number", "status", "last_seen", "messages_sent", "messages_received"]
                );
                
                state.accounts = accounts;
                
                // Set active account if none selected
                if (!state.activeAccount && accounts.length > 0) {
                    state.activeAccount = accounts[0];
                    await loadAccountData(accounts[0].id);
                }
                
            } catch (error) {
                console.error("Error loading accounts:", error);
                notification.add("Error loading WhatsApp accounts", { type: "danger" });
            }
        }

        async function loadAccountData(accountId) {
            try {
                // Load messages
                const messages = await orm.searchRead(
                    "whatsapp.message",
                    [["account_id", "=", accountId]],
                    ["message", "message_type", "direction", "from_number", "to_number", "timestamp", "status"],
                    { order: "timestamp desc", limit: 100 }
                );
                
                // Load contacts
                const contacts = await orm.searchRead(
                    "whatsapp.contact",
                    [["account_id", "=", accountId], ["status", "=", "active"]],
                    ["name", "phone_number", "profile_pic_url", "is_business", "last_seen", "message_count"]
                );
                
                // Load groups
                const groups = await orm.searchRead(
                    "whatsapp.group",
                    [["account_id", "=", accountId], ["is_member", "=", true]],
                    ["name", "group_id", "member_count", "is_admin", "last_activity"]
                );
                
                state.messages = messages;
                state.contacts = contacts;
                state.groups = groups;
                
            } catch (error) {
                console.error("Error loading account data:", error);
                notification.add("Error loading account data", { type: "danger" });
            }
        }

        function initializeSocket() {
            try {
                // Connect to WhatsApp Node.js server
                const socketUrl = getSocketUrl();
                if (typeof io !== 'undefined') {
                    state.socket = io(socketUrl);
                    
                    state.socket.on("connect", () => {
                        console.log("Connected to WhatsApp server");
                        state.isConnected = true;
                        
                        // Join session for active account
                        if (state.activeAccount) {
                            state.socket.emit("join_session", state.activeAccount.session_name);
                        }
                    });
                    
                    state.socket.on("disconnect", () => {
                        console.log("Disconnected from WhatsApp server");
                        state.isConnected = false;
                    });
                    
                    state.socket.on("message", (data) => {
                        handleIncomingMessage(data);
                    });
                    
                    state.socket.on("message_sent", (data) => {
                        handleSentMessage(data);
                    });
                    
                    state.socket.on("message_ack", (data) => {
                        handleMessageAck(data);
                    });
                    
                    state.socket.on("qr", (data) => {
                        handleQRCode(data);
                    });
                    
                    state.socket.on("ready", (data) => {
                        handleAccountReady(data);
                    });
                    
                    state.socket.on("authenticated", (data) => {
                        handleAccountAuthenticated(data);
                    });
                    
                    state.socket.on("disconnected", (data) => {
                        handleAccountDisconnected(data);
                    });
                }
                
            } catch (error) {
                console.error("Error initializing socket:", error);
            }
        }

        function getSocketUrl() {
            // Get socket URL from system parameters or default
            return "http://localhost:3000";
        }

        function startBusListener() {
            // Listen for Odoo bus notifications
            bus_service.addEventListener("whatsapp.message", (event) => {
                handleBusMessage(event.detail);
            });
            
            bus_service.addEventListener("whatsapp.status", (event) => {
                handleBusStatus(event.detail);
            });
        }

        function handleIncomingMessage(data) {
            console.log("Incoming message:", data);
            
            // Add message to state
            state.messages.unshift({
                id: Date.now(), // Temporary ID
                message: data.message.body,
                message_type: data.message.type,
                direction: "incoming",
                from_number: data.message.from.replace("@c.us", ""),
                timestamp: new Date(data.message.timestamp * 1000),
                status: "delivered"
            });
            
            // Show notification
            notification.add(
                `New message from ${data.message.contact.name || data.message.from}`,
                { type: "info" }
            );
            
            // Play notification sound
            playNotificationSound();
        }

        function handleSentMessage(data) {
            console.log("Sent message:", data);
            
            // Update message status in state
            const messageIndex = state.messages.findIndex(
                msg => msg.temp_id === data.temp_id
            );
            
            if (messageIndex !== -1) {
                state.messages[messageIndex].status = "sent";
                state.messages[messageIndex].wa_message_id = data.message.id;
            }
        }

        function handleMessageAck(data) {
            console.log("Message ACK:", data);
            
            // Update message status
            const messageIndex = state.messages.findIndex(
                msg => msg.wa_message_id === data.messageId
            );
            
            if (messageIndex !== -1) {
                state.messages[messageIndex].status = data.ack;
            }
        }

        function handleQRCode(data) {
            console.log("QR Code received:", data);
            
            // Show QR code dialog
            showQRCodeDialog(data.qr, data.qrImage);
        }

        function handleAccountReady(data) {
            console.log("Account ready:", data);
            
            // Update account status
            const accountIndex = state.accounts.findIndex(
                acc => acc.session_name === data.session
            );
            
            if (accountIndex !== -1) {
                state.accounts[accountIndex].status = "ready";
            }
            
            notification.add("WhatsApp account is ready", { type: "success" });
        }

        function handleAccountAuthenticated(data) {
            console.log("Account authenticated:", data);
            
            // Update account status
            const accountIndex = state.accounts.findIndex(
                acc => acc.session_name === data.session
            );
            
            if (accountIndex !== -1) {
                state.accounts[accountIndex].status = "authenticated";
            }
        }

        function handleAccountDisconnected(data) {
            console.log("Account disconnected:", data);
            
            // Update account status
            const accountIndex = state.accounts.findIndex(
                acc => acc.session_name === data.session
            );
            
            if (accountIndex !== -1) {
                state.accounts[accountIndex].status = "disconnected";
            }
            
            notification.add("WhatsApp account disconnected", { type: "warning" });
        }

        function handleBusMessage(data) {
            console.log("Bus message:", data);
            
            // Handle message from Odoo bus
            if (data.account_id === state.activeAccount?.id) {
                state.messages.unshift({
                    id: data.message_id,
                    message: data.message,
                    message_type: data.message_type,
                    direction: "incoming",
                    from_number: data.from_number,
                    from_name: data.from_name,
                    timestamp: new Date(),
                    status: "delivered"
                });
                
                playNotificationSound();
            }
        }

        function handleBusStatus(data) {
            console.log("Bus status:", data);
            
            // Update account status from bus
            const accountIndex = state.accounts.findIndex(
                acc => acc.id === data.account_id
            );
            
            if (accountIndex !== -1) {
                state.accounts[accountIndex].status = data.status;
            }
        }

        async function sendMessage(to, message, messageType = "text", attachment = null) {
            try {
                if (!state.activeAccount) {
                    throw new Error("No active account");
                }
                
                // Create temporary message
                const tempId = Date.now();
                const tempMessage = {
                    id: tempId,
                    temp_id: tempId,
                    message: message,
                    message_type: messageType,
                    direction: "outgoing",
                    to_number: to,
                    timestamp: new Date(),
                    status: "pending"
                };
                
                // Add to messages immediately
                state.messages.unshift(tempMessage);
                
                // Send via Odoo
                const result = await orm.call(
                    "whatsapp.account",
                    "send_message",
                    [state.activeAccount.id],
                    {
                        to: to,
                        message: message,
                        message_type: messageType,
                        attachment: attachment
                    }
                );
                
                // Update message with result
                const messageIndex = state.messages.findIndex(
                    msg => msg.temp_id === tempId
                );
                
                if (messageIndex !== -1) {
                    state.messages[messageIndex].id = result.id;
                    state.messages[messageIndex].status = "sent";
                    state.messages[messageIndex].wa_message_id = result.wa_message_id;
                }
                
                return result;
                
            } catch (error) {
                console.error("Error sending message:", error);
                notification.add("Error sending message", { type: "danger" });
                throw error;
            }
        }

        async function connectAccount(accountId) {
            try {
                await orm.call("whatsapp.account", "action_connect", [accountId]);
                
                // Reload account data
                await loadAccounts();
                
                notification.add("Connecting to WhatsApp...", { type: "info" });
                
            } catch (error) {
                console.error("Error connecting account:", error);
                notification.add("Error connecting account", { type: "danger" });
            }
        }

        async function disconnectAccount(accountId) {
            try {
                await orm.call("whatsapp.account", "action_disconnect", [accountId]);
                
                // Reload account data
                await loadAccounts();
                
                notification.add("Account disconnected", { type: "info" });
                
            } catch (error) {
                console.error("Error disconnecting account:", error);
                notification.add("Error disconnecting account", { type: "danger" });
            }
        }

        async function syncContacts(accountId) {
            try {
                await orm.call("whatsapp.account", "sync_contacts", [accountId]);
                
                // Reload contacts
                if (state.activeAccount?.id === accountId) {
                    await loadAccountData(accountId);
                }
                
                notification.add("Contacts synced successfully", { type: "success" });
                
            } catch (error) {
                console.error("Error syncing contacts:", error);
                notification.add("Error syncing contacts", { type: "danger" });
            }
        }

        async function switchAccount(accountId) {
            try {
                const account = state.accounts.find(acc => acc.id === accountId);
                if (!account) {
                    throw new Error("Account not found");
                }
                
                // Leave current session
                if (state.activeAccount && state.socket) {
                    state.socket.emit("leave_session", state.activeAccount.session_name);
                }
                
                // Set new active account
                state.activeAccount = account;
                
                // Join new session
                if (state.socket) {
                    state.socket.emit("join_session", account.session_name);
                }
                
                // Load account data
                await loadAccountData(accountId);
                
            } catch (error) {
                console.error("Error switching account:", error);
                notification.add("Error switching account", { type: "danger" });
            }
        }

        function showQRCodeDialog(qrCode, qrImage) {
            // Use Odoo's dialog service instead of jQuery modal
            env.services.dialog.add(QRCodeDialog, {
                qrCode: qrCode,
                qrImage: qrImage,
            });
        }

        function playNotificationSound() {
            try {
                const audio = new Audio("/whatsapp/static/audio/notification.mp3");
                audio.play().catch(e => console.log("Could not play notification sound:", e));
            } catch (error) {
                console.log("Could not play notification sound:", error);
            }
        }

        function formatMessageTime(timestamp) {
            const date = new Date(timestamp);
            const now = new Date();
            
            if (date.toDateString() === now.toDateString()) {
                // Today - show time
                return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            } else if (date.getTime() > now.getTime() - 7 * 24 * 60 * 60 * 1000) {
                // This week - show day and time
                return date.toLocaleDateString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' });
            } else {
                // Older - show date
                return date.toLocaleDateString();
            }
        }

        function getMessageStatusIcon(status) {
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

        function cleanup() {
            if (state.socket) {
                state.socket.disconnect();
            }
        }

        // Initialize the service
        initializeService();
        startBusListener();

        // Return the service API
        return {
            state,
            sendMessage,
            connectAccount,
            disconnectAccount,
            syncContacts,
            switchAccount,
            loadAccounts,
            loadAccountData,
            formatMessageTime,
            getMessageStatusIcon,
            cleanup,
        };
    }
};

// Register the service
registry.category("services").add("whatsapp", whatsAppService);