/** @odoo-module **/

import { Component, useState, onMounted, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class WhatsAppMessageComposer extends Component {
    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        
        this.textArea = useRef("textArea");
        this.fileInput = useRef("fileInput");
        
        this.state = useState({
            message: "",
            messageType: "text",
            attachment: null,
            showEmojiPicker: false,
            showTemplates: false,
            templates: [],
            selectedTemplate: null,
            isRecording: false,
            recordingTime: 0,
            mediaRecorder: null,
            recordingBlob: null,
        });

        onMounted(() => {
            this.loadTemplates();
            this.autoResizeTextArea();
        });
    }

    async loadTemplates() {
        try {
            const templates = await this.orm.searchRead(
                "whatsapp.template",
                [["active", "=", true], ["template_type", "=", "text"]],
                ["name", "content", "template_type"]
            );
            
            this.state.templates = templates;
        } catch (error) {
            console.error("Error loading templates:", error);
        }
    }

    onMessageInput(event) {
        this.state.message = event.target.value;
        this.autoResizeTextArea();
        
        // Emit typing event
        if (this.props.onTyping) {
            this.props.onTyping(this.state.message.length > 0);
        }
    }

    autoResizeTextArea() {
        if (this.textArea.el) {
            this.textArea.el.style.height = "auto";
            this.textArea.el.style.height = Math.min(this.textArea.el.scrollHeight, 120) + "px";
        }
    }

    onKeyDown(event) {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            this.sendMessage();
        }
    }

    async sendMessage() {
        if (!this.state.message.trim() && !this.state.attachment && !this.state.recordingBlob) {
            return;
        }
        
        try {
            let messageData = {
                message: this.state.message,
                messageType: this.state.messageType,
                attachment: this.state.attachment || this.state.recordingBlob,
            };
            
            if (this.props.onSendMessage) {
                await this.props.onSendMessage(messageData);
            }
            
            // Clear composer
            this.clearComposer();
            
        } catch (error) {
            console.error("Error sending message:", error);
            this.notification.add("Error sending message", { type: "danger" });
        }
    }

    clearComposer() {
        this.state.message = "";
        this.state.messageType = "text";
        this.state.attachment = null;
        this.state.recordingBlob = null;
        this.state.selectedTemplate = null;
        this.autoResizeTextArea();
        
        if (this.fileInput.el) {
            this.fileInput.el.value = "";
        }
    }

    onFileSelect(event) {
        const file = event.target.files[0];
        if (file) {
            this.handleFileUpload(file);
        }
    }

    handleFileUpload(file) {
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

    removeAttachment() {
        this.state.attachment = null;
        this.state.recordingBlob = null;
        this.state.messageType = "text";
        
        if (this.fileInput.el) {
            this.fileInput.el.value = "";
        }
    }

    triggerFileInput() {
        if (this.fileInput.el) {
            this.fileInput.el.click();
        }
    }

    onDragOver(event) {
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
    }

    onDrop(event) {
        event.preventDefault();
        const files = event.dataTransfer.files;
        if (files.length > 0) {
            this.handleFileUpload(files[0]);
        }
    }

    toggleEmojiPicker() {
        this.state.showEmojiPicker = !this.state.showEmojiPicker;
        this.state.showTemplates = false;
    }

    toggleTemplates() {
        this.state.showTemplates = !this.state.showTemplates;
        this.state.showEmojiPicker = false;
    }

    insertEmoji(emoji) {
        this.state.message += emoji;
        this.state.showEmojiPicker = false;
        this.textArea.el.focus();
    }

    selectTemplate(template) {
        this.state.selectedTemplate = template;
        this.state.message = template.content;
        this.state.messageType = template.template_type;
        this.state.showTemplates = false;
        this.autoResizeTextArea();
        this.textArea.el.focus();
    }

    async startVoiceRecording() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            
            this.state.mediaRecorder = new MediaRecorder(stream);
            this.state.isRecording = true;
            this.state.recordingTime = 0;
            
            const chunks = [];
            
            this.state.mediaRecorder.ondataavailable = (event) => {
                chunks.push(event.data);
            };
            
            this.state.mediaRecorder.onstop = () => {
                const blob = new Blob(chunks, { type: "audio/webm" });
                this.state.recordingBlob = blob;
                this.state.messageType = "voice";
                this.state.isRecording = false;
                
                // Stop all tracks
                stream.getTracks().forEach(track => track.stop());
            };
            
            this.state.mediaRecorder.start();
            
            // Start recording timer
            this.recordingTimer = setInterval(() => {
                this.state.recordingTime++;
            }, 1000);
            
        } catch (error) {
            console.error("Error starting voice recording:", error);
            this.notification.add("Error starting voice recording", { type: "danger" });
        }
    }

    stopVoiceRecording() {
        if (this.state.mediaRecorder && this.state.isRecording) {
            this.state.mediaRecorder.stop();
            clearInterval(this.recordingTimer);
        }
    }

    cancelVoiceRecording() {
        if (this.state.mediaRecorder && this.state.isRecording) {
            this.state.mediaRecorder.stop();
            clearInterval(this.recordingTimer);
            this.state.recordingBlob = null;
            this.state.messageType = "text";
            this.state.isRecording = false;
            this.state.recordingTime = 0;
        }
    }

    formatRecordingTime(seconds) {
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = seconds % 60;
        return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`;
    }

    getAttachmentIcon() {
        switch (this.state.messageType) {
            case "image":
                return "fa-image";
            case "video":
                return "fa-video";
            case "audio":
                return "fa-music";
            case "voice":
                return "fa-microphone";
            case "document":
                return "fa-file";
            default:
                return "fa-paperclip";
        }
    }

    getAttachmentName() {
        if (this.state.attachment) {
            return this.state.attachment.name;
        } else if (this.state.recordingBlob) {
            return "Voice message";
        }
        return "";
    }

    static template = "whatsapp.MessageComposer";
    static components = {};
    static props = ["onSendMessage?", "onTyping?"];
}

// Common emojis
export const COMMON_EMOJIS = [
    "😀", "😃", "😄", "😁", "😆", "😅", "🤣", "😂", "🙂", "🙃",
    "😉", "😊", "😇", "🥰", "😍", "🤩", "😘", "😗", "😚", "😙",
    "😋", "😛", "😜", "🤪", "😝", "🤑", "🤗", "🤭", "🤫", "🤔",
    "🤐", "🤨", "😐", "😑", "😶", "😏", "😒", "🙄", "😬", "🤥",
    "😔", "😕", "🙁", "😖", "😣", "😞", "😟", "😤", "😢", "😭",
    "😦", "😧", "😨", "😩", "🤯", "😬", "😰", "😱", "🥵", "🥶",
    "👍", "👎", "👌", "✌️", "🤞", "🤟", "🤘", "🤙", "👈", "👉",
    "👆", "👇", "☝️", "✋", "🤚", "🖐️", "🖖", "👋", "🤝", "🙏",
    "❤️", "🧡", "💛", "💚", "💙", "💜", "🖤", "🤍", "🤎", "💔",
    "❣️", "💕", "💞", "💓", "💗", "💖", "💘", "💝", "💟", "♥️"
];