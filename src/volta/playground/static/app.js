/**
 * volta Playground frontend.
 * Vanilla JS -- no build step, no framework dependencies.
 */

class PlaygroundApp {
    constructor() {
        this.ws = null;
        this.sessionId = null;
        this.operations = [];
        this.init();
    }

    init() {
        this.connectWebSocket();
        this.setupUpload();
        this.loadOperations();
    }

    connectWebSocket() {
        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.ws = new WebSocket(`${protocol}//${location.host}/ws`);
        this.ws.onmessage = (event) => this.handleMessage(JSON.parse(event.data));
        this.ws.onclose = () => {
            this.log('WebSocket disconnected. Reconnecting in 2s...');
            setTimeout(() => this.connectWebSocket(), 2000);
        };
    }

    handleMessage(msg) {
        switch (msg.type) {
            case 'connected':
                this.log('Connected to volta');
                break;
            case 'progress':
                this.log(msg.message);
                break;
            case 'complete':
                this.log('Operation complete');
                this.showResult(msg.result);
                break;
            case 'error':
                this.log(`Error: ${msg.message}`, 'error');
                break;
        }
    }

    setupUpload() {
        const dropzone = document.getElementById('dropzone');
        const fileInput = document.getElementById('file-input');
        const uploadBtn = document.getElementById('upload-btn');

        uploadBtn.addEventListener('click', () => fileInput.click());
        dropzone.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.classList.add('dragover'); });
        dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
        dropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropzone.classList.remove('dragover');
            if (e.dataTransfer.files.length) this.uploadFile(e.dataTransfer.files[0]);
        });
        fileInput.addEventListener('change', () => {
            if (fileInput.files.length) this.uploadFile(fileInput.files[0]);
        });
    }

    async uploadFile(file) {
        const formData = new FormData();
        formData.append('file', file);
        try {
            const resp = await fetch('/api/upload', { method: 'POST', body: formData });
            if (!resp.ok) {
                const err = await resp.json();
                this.log(`Upload failed: ${err.detail}`, 'error');
                return;
            }
            const data = await resp.json();
            this.sessionId = data.session_id;
            this.log(`Uploaded: ${data.filename} (${data.size} bytes)`);
            this.loadPreview(data.session_id);
        } catch (err) {
            this.log(`Upload error: ${err}`, 'error');
        }
    }

    async loadOperations() {
        try {
            const resp = await fetch('/api/operations');
            this.operations = await resp.json();
            this.renderOperations();
        } catch (err) {
            this.log('Failed to load operations', 'error');
        }
    }

    renderOperations() {
        const palette = document.getElementById('operation-palette');
        palette.innerHTML = '';
        for (const op of this.operations) {
            const btn = document.createElement('button');
            btn.className = 'operation-btn';
            btn.textContent = op.name;
            btn.addEventListener('click', () => this.executeOperation(op));
            palette.appendChild(btn);
        }
    }

    async executeOperation(op) {
        this.log(`Executing: ${op.name}`);
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ action: 'execute', operation: { op_type: op.name } }));
        } else {
            const resp = await fetch('/api/execute', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ operation: { op_type: op.name }, session_id: this.sessionId }),
            });
            const data = await resp.json();
            this.showResult(data.result);
        }
    }

    async loadPreview(sessionId) {
        try {
            const previewEl = document.getElementById('svg-preview');
            previewEl.innerHTML = '';
            const img = document.createElement('img');
            img.src = `/api/preview/${sessionId}`;
            img.alt = 'Schematic preview';
            img.style.maxWidth = '100%';
            img.onerror = () => { previewEl.innerHTML = '<p class="placeholder">Preview unavailable</p>'; };
            previewEl.appendChild(img);
        } catch (err) {
            this.log('Preview failed', 'error');
        }
    }

    async runERC() {
        if (!this.sessionId) { this.log('Upload a file first', 'error'); return; }
        const resp = await fetch('/api/erc', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: this.sessionId }),
        });
        const data = await resp.json();
        document.getElementById('report-panel').innerHTML =
            `<h3>ERC Results</h3><p>Violations: ${data.violation_count}</p><pre>${data.output}</pre>`;
    }

    async runDRC() {
        if (!this.sessionId) { this.log('Upload a file first', 'error'); return; }
        const resp = await fetch('/api/drc', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: this.sessionId }),
        });
        const data = await resp.json();
        document.getElementById('report-panel').innerHTML =
            `<h3>DRC Results</h3><p>Violations: ${data.violation_count}</p><pre>${data.output}</pre>`;
    }

    showResult(result) {
        if (result) {
            this.log(JSON.stringify(result, null, 2));
        }
    }

    log(message, level = 'info') {
        const panel = document.getElementById('log-panel');
        const entry = document.createElement('div');
        entry.className = `log-entry log-${level}`;
        entry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
        panel.appendChild(entry);
        panel.scrollTop = panel.scrollHeight;
    }
}

document.addEventListener('DOMContentLoaded', () => new PlaygroundApp());
