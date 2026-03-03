class ChatbotRAG {
    constructor() {
        this.apiUrl = window.location.origin.startsWith('http')
            ? window.location.origin
            : 'http://localhost:5000';
        this.sourcesCollapsed = false;
        this.isAuthenticated = false;
        this.currentUser = null;
        this.authConfig = null;
        this.init();
    }

    async init() {
        this.cacheElements();
        this.bindEvents();
        this.setupAutoResize();
        await this.initializeAuth();
    }

    cacheElements() {
        this.chatMessages    = document.getElementById('chat-messages');
        this.userInput       = document.getElementById('user-input');
        this.sendButton      = document.getElementById('send-button');
        this.uploadForm      = document.getElementById('upload-form');
        this.fileInput       = document.getElementById('file-input');
        this.resetDocumentsButton = document.getElementById('reset-documents-button');
        this.documentsList   = document.getElementById('documents-list');
        this.statusIndicator = document.getElementById('status-indicator');
        this.statusText      = document.getElementById('status-text');
        this.sourcesDiv      = document.getElementById('sources');
        this.authOverlay     = document.getElementById('auth-overlay');
        this.authFeedback    = document.getElementById('auth-feedback');
        this.googleButton    = document.getElementById('google-signin-button');
        this.logoutButton    = document.getElementById('logout-button');
        this.sessionUserName = document.getElementById('session-user-name');
        this.sessionUserEmail = document.getElementById('session-user-email');
        this.sessionUserAvatar = document.getElementById('session-user-avatar');
    }

    bindEvents() {
        this.sendButton.addEventListener('click', () => this.sendMessage());
        this.logoutButton.addEventListener('click', () => this.logout());

        this.userInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });

        this.uploadForm.addEventListener('submit', (e) => {
            e.preventDefault();
            this.uploadDocuments();
        });

        this.resetDocumentsButton.addEventListener('click', () => this.resetDocuments());

        // Drag-and-drop on upload area
        const uploadArea = this.uploadForm;
        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.style.borderColor = 'rgba(240,175,60,0.6)';
        });
        uploadArea.addEventListener('dragleave', () => {
            uploadArea.style.borderColor = '';
        });
        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.style.borderColor = '';
            const dt = new DataTransfer();
            Array.from(e.dataTransfer.files).forEach(f => dt.items.add(f));
            this.fileInput.files = dt.files;
            this.updateUploadLabel();
        });

        this.fileInput.addEventListener('change', () => this.updateUploadLabel());
    }

    async initializeAuth() {
        await this.loadAuthConfig();
        const authState = await this.fetchCurrentUser();

        if (authState?.authenticated) {
            this.setAuthenticatedState(authState.user);
            await this.refreshProtectedData();
            return;
        }

        this.setLoggedOutState();
        await this.renderGoogleButton();
    }

    async loadAuthConfig() {
        try {
            const response = await fetch(`${this.apiUrl}/api/auth/config`);
            this.authConfig = await response.json();
        } catch {
            this.authConfig = { enabled: false, google_client_id: '' };
        }
    }

    async fetchCurrentUser() {
        try {
            const response = await fetch(`${this.apiUrl}/api/auth/me`);
            return await response.json();
        } catch {
            return { authenticated: false, user: null };
        }
    }

    async waitForGoogleIdentityServices(timeoutMs = 5000) {
        const startedAt = Date.now();
        while (!(window.google && window.google.accounts && window.google.accounts.id)) {
            if (Date.now() - startedAt > timeoutMs) {
                throw new Error('Google Identity Services não carregou.');
            }
            await new Promise(resolve => setTimeout(resolve, 100));
        }
    }

    async renderGoogleButton() {
        if (!this.authConfig?.enabled || !this.authConfig?.google_client_id) {
            this.authFeedback.textContent = 'Configure GOOGLE_CLIENT_ID no backend para habilitar o login Google.';
            return;
        }

        try {
            await this.waitForGoogleIdentityServices();
        } catch (error) {
            this.authFeedback.textContent = error.message;
            return;
        }

        this.googleButton.innerHTML = '';
        window.google.accounts.id.initialize({
            client_id: this.authConfig.google_client_id,
            callback: (response) => this.handleGoogleLogin(response),
        });
        window.google.accounts.id.renderButton(this.googleButton, {
            theme: 'outline',
            size: 'large',
            shape: 'pill',
            text: 'signin_with',
            width: 280,
        });
    }

    async handleGoogleLogin(googleResponse) {
        if (!googleResponse?.credential) {
            this.authFeedback.textContent = 'Não foi possível obter a credencial do Google.';
            return;
        }

        this.authFeedback.textContent = 'Validando login...';

        try {
            const response = await fetch(`${this.apiUrl}/api/auth/google`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ credential: googleResponse.credential }),
            });
            const data = await response.json();

            if (!response.ok) {
                this.authFeedback.textContent = data.error || 'Falha no login Google.';
                return;
            }

            this.setAuthenticatedState(data.user);
            this.addMessage(`Sessão iniciada como ${data.user?.name || data.user?.email}.`, 'bot');
            await this.refreshProtectedData();
        } catch {
            this.authFeedback.textContent = 'Erro ao conectar com o backend durante o login.';
        }
    }

    async logout() {
        try {
            await fetch(`${this.apiUrl}/api/auth/logout`, { method: 'POST' });
        } catch {
            // Ignora erro de rede no logout; o estado local ainda será limpo.
        }

        this.setLoggedOutState();
        this.resetConversation();
        this.clearSources();
        this.documentsList.innerHTML = '<li style="color:var(--text-muted);border-style:dashed">Faça login para listar documentos</li>';
        await this.renderGoogleButton();
    }

    setAuthenticatedState(user) {
        this.isAuthenticated = true;
        this.currentUser = user;
        this.authOverlay.classList.add('hidden');
        this.logoutButton.hidden = false;
        this.logoutButton.disabled = false;
        this.sessionUserName.textContent = user?.name || 'Usuário autenticado';
        this.sessionUserEmail.textContent = user?.email || '';

        if (user?.picture) {
            this.sessionUserAvatar.src = user.picture;
            this.sessionUserAvatar.hidden = false;
        } else {
            this.sessionUserAvatar.hidden = true;
            this.sessionUserAvatar.removeAttribute('src');
        }

        this.enableApp();
    }

    setLoggedOutState() {
        this.isAuthenticated = false;
        this.currentUser = null;
        this.authOverlay.classList.remove('hidden');
        this.authFeedback.textContent = 'Faça login para liberar consulta, upload e manutenção.';
        this.logoutButton.hidden = true;
        this.sessionUserName.textContent = 'Login necessário';
        this.sessionUserEmail.textContent = 'Use Google para entrar';
        this.sessionUserAvatar.hidden = true;
        this.sessionUserAvatar.removeAttribute('src');
        this.disableApp();
    }

    enableApp() {
        this.userInput.disabled = false;
        this.sendButton.disabled = false;
        this.fileInput.disabled = false;
        this.resetDocumentsButton.disabled = false;
    }

    disableApp() {
        this.userInput.disabled = true;
        this.sendButton.disabled = true;
        this.fileInput.disabled = true;
        this.resetDocumentsButton.disabled = true;
        this.statusIndicator.className = 'status-dot';
        this.statusText.textContent = 'Login necessário';
    }

    async refreshProtectedData() {
        await Promise.all([
            this.checkStatus(),
            this.loadDocuments(),
        ]);
    }

    handleUnauthorized() {
        this.setLoggedOutState();
        this.clearSources();
        this.documentsList.innerHTML = '<li style="color:var(--text-muted);border-style:dashed">Faça login para listar documentos</li>';
        this.renderGoogleButton();
    }

    updateUploadLabel() {
        const files = this.fileInput.files;
        const hint  = this.uploadForm.querySelector('.upload-hint');
        if (!hint) return;
        if (files && files.length > 0) {
            hint.textContent = files.length === 1
                ? files[0].name
                : `${files.length} arquivos selecionados`;
            hint.style.color = 'var(--gold)';
        } else {
            hint.textContent = 'Arraste ou clique para enviar';
            hint.style.color = '';
        }
    }

    setupAutoResize() {
        this.userInput.addEventListener('input', () => {
            this.userInput.style.height = 'auto';
            this.userInput.style.height = Math.min(this.userInput.scrollHeight, 160) + 'px';
        });
    }

    async checkStatus() {
        try {
            const response = await fetch(`${this.apiUrl}/api/status`);
            if (response.status === 401) {
                this.handleUnauthorized();
                return;
            }
            const data = await response.json();

            const llmLabel = data.llm_ready
                ? `LLM: ${data.llm_provider}`
                : 'LLM: fallback';

            this.statusIndicator.className = 'status-dot online';
            this.statusText.textContent = `Online · ${data.documents_count} docs · ${llmLabel}`;
        } catch {
            this.statusIndicator.className = 'status-dot';
            this.statusText.textContent = 'Servidor offline';
        }
    }

    async loadDocuments() {
        try {
            const response = await fetch(`${this.apiUrl}/api/documents`);
            if (response.status === 401) {
                this.handleUnauthorized();
                return;
            }
            const data = await response.json();

            this.documentsList.innerHTML = '';

            if (data.documents.length === 0) {
                this.documentsList.innerHTML = '<li style="color:var(--text-muted);border-style:dashed">Nenhum documento carregado</li>';
            } else {
                data.documents.forEach(doc => {
                    const li = document.createElement('li');
                    li.className = 'document-item';
                    li.title = doc;

                    const name = document.createElement('span');
                    name.className = 'document-name';
                    name.textContent = doc;

                    const deleteButton = document.createElement('button');
                    deleteButton.type = 'button';
                    deleteButton.className = 'document-delete-btn';
                    deleteButton.textContent = 'Excluir';
                    deleteButton.title = `Excluir ${doc}`;
                    deleteButton.addEventListener('click', () => this.deleteDocument(doc));

                    li.appendChild(name);
                    li.appendChild(deleteButton);
                    this.documentsList.appendChild(li);
                });
            }
        } catch {
            this.documentsList.innerHTML = '<li style="color:var(--text-muted)">Erro ao carregar documentos</li>';
        }
    }

    async deleteDocument(filename) {
        if (!this.isAuthenticated) return;
        const confirmed = window.confirm(`Excluir o documento "${filename}" e atualizar a base?`);
        if (!confirmed) return;

        try {
            const response = await fetch(`${this.apiUrl}/api/documents/${encodeURIComponent(filename)}`, {
                method: 'DELETE'
            });
            if (response.status === 401) {
                this.handleUnauthorized();
                return;
            }
            const data = await response.json();

            if (response.ok) {
                this.addMessage(`Documento removido: ${filename}`, 'bot');
                this.loadDocuments();
                this.checkStatus();
                this.clearSources();
            } else {
                this.addMessage(`Erro ao excluir documento: ${data.error}`, 'bot');
            }
        } catch {
            this.addMessage('Erro ao excluir documento', 'bot');
        }
    }

    async resetDocuments() {
        if (!this.isAuthenticated) return;
        const confirmed = window.confirm('Isso vai apagar todos os documentos enviados e zerar a base vetorial. Deseja continuar?');
        if (!confirmed) return;

        this.resetDocumentsButton.disabled = true;
        this.resetDocumentsButton.textContent = 'Resetando...';

        try {
            const response = await fetch(`${this.apiUrl}/api/documents/reset`, {
                method: 'POST'
            });
            if (response.status === 401) {
                this.handleUnauthorized();
                return;
            }
            const data = await response.json();

            if (response.ok) {
                this.addMessage('Todos os documentos foram apagados e a base foi zerada.', 'bot');
                this.loadDocuments();
                this.checkStatus();
                this.clearSources();
                this.resetConversation();
            } else {
                this.addMessage(`Erro no reset: ${data.error}`, 'bot');
            }
        } catch {
            this.addMessage('Erro ao resetar documentos e base', 'bot');
        } finally {
            this.resetDocumentsButton.disabled = false;
            this.resetDocumentsButton.textContent = 'Resetar tudo';
        }
    }

    async uploadDocuments() {
        if (!this.isAuthenticated) return;
        const files = this.fileInput.files;
        if (files.length === 0) return;

        const btn = this.uploadForm.querySelector('.upload-btn');
        if (btn) { btn.disabled = true; btn.textContent = 'Enviando…'; }

        const formData = new FormData();
        for (let file of files) formData.append('file', file);

        try {
            const response = await fetch(`${this.apiUrl}/api/upload`, {
                method: 'POST',
                body: formData
            });
            if (response.status === 401) {
                this.handleUnauthorized();
                return;
            }

            const data = await response.json();

            if (response.ok) {
                const count = Array.isArray(data.filenames) ? data.filenames.length : 1;
                this.addMessage(`✓ ${count} documento(s) enviado(s) com sucesso!`, 'bot');
                if (Array.isArray(data.ignored) && data.ignored.length > 0) {
                    this.addMessage(`Arquivos ignorados: ${data.ignored.join(', ')}`, 'bot');
                }
                this.fileInput.value = '';
                this.updateUploadLabel();
                this.loadDocuments();
                this.checkStatus();
            } else {
                this.addMessage(`Erro no envio: ${data.error}`, 'bot');
            }
        } catch {
            this.addMessage('Erro ao conectar com o servidor', 'bot');
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M5 12h14M12 5l7 7-7 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg> Enviar arquivos`;
            }
        }
    }

    async sendMessage() {
        if (!this.isAuthenticated) return;
        const query = this.userInput.value.trim();
        if (!query) return;

        this.addMessage(query, 'user');
        this.userInput.value = '';
        this.userInput.style.height = 'auto';

        // Hide old sources
        this.clearSources();

        const loadingId = this.showLoading();

        try {
            const response = await fetch(`${this.apiUrl}/api/query`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query })
            });
            if (response.status === 401) {
                this.removeLoading(loadingId);
                this.handleUnauthorized();
                return;
            }

            const data = await response.json();
            this.removeLoading(loadingId);

            if (response.ok) {
                this.addMessage(data.answer, 'bot');
                this.showSources(data.sources);
            } else {
                this.addMessage(`Erro: ${data.error}`, 'bot');
            }
        } catch {
            this.removeLoading(loadingId);
            this.addMessage('Erro de conexão com o servidor', 'bot');
        }
    }

    addMessage(text, sender) {
        const wrap = document.createElement('div');
        wrap.className = `message ${sender}`;

        const time = new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });

        // Avatar icon SVG
        const botSVG = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
        const userSVG = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><circle cx="12" cy="7" r="4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

        // Convert plain text newlines to paragraphs
        const formatted = text.split('\n').filter(l => l.trim()).map(l => `<p>${l}</p>`).join('') || `<p>${text}</p>`;

        wrap.innerHTML = `
            <div class="msg-avatar">${sender === 'bot' ? botSVG : userSVG}</div>
            <div class="msg-body">
                <div class="msg-content">${formatted}</div>
                <div class="msg-time">${time}</div>
            </div>`;

        this.chatMessages.appendChild(wrap);
        this.scrollToBottom();
    }

    showLoading() {
        const id = 'loading-' + Date.now();
        const wrap = document.createElement('div');
        wrap.className = 'message bot';
        wrap.id = id;

        const botSVG = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

        wrap.innerHTML = `
            <div class="msg-avatar">${botSVG}</div>
            <div class="msg-body">
                <div class="msg-content">
                    <div class="loading">
                        <span class="loading-dot"></span>
                        <span class="loading-dot"></span>
                        <span class="loading-dot"></span>
                    </div>
                </div>
            </div>`;

        this.chatMessages.appendChild(wrap);
        this.scrollToBottom();
        return id;
    }

    removeLoading(id) {
        const el = document.getElementById(id);
        if (el) el.remove();
    }

    showSources(sources) {
        this.sourcesDiv.innerHTML = '';

        if (!sources || sources.length === 0) return;

        this.sourcesCollapsed = false;
        this.sourcesDiv.classList.add('has-content');

        const header = document.createElement('div');
        header.className = 'sources-header';

        const title = document.createElement('strong');
        title.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none"><path d="M9 11l3 3L22 4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg> Fontes consultadas`;

        const actions = document.createElement('div');
        actions.className = 'sources-actions';

        const collapseButton = document.createElement('button');
        collapseButton.type = 'button';
        collapseButton.className = 'sources-action-btn';
        collapseButton.title = 'Colapsar fontes';
        collapseButton.setAttribute('aria-label', 'Colapsar fontes');
        collapseButton.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none"><path d="M6 9l6 6 6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
        collapseButton.addEventListener('click', () => this.toggleSourcesCollapse());

        const closeButton = document.createElement('button');
        closeButton.type = 'button';
        closeButton.className = 'sources-action-btn';
        closeButton.title = 'Fechar fontes';
        closeButton.setAttribute('aria-label', 'Fechar fontes');
        closeButton.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none"><path d="M18 6L6 18M6 6l12 12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>`;
        closeButton.addEventListener('click', () => this.clearSources());

        actions.appendChild(collapseButton);
        actions.appendChild(closeButton);
        header.appendChild(title);
        header.appendChild(actions);
        this.sourcesDiv.appendChild(header);

        const content = document.createElement('div');
        content.className = 'sources-content';

        sources.forEach(source => {
            const item = document.createElement('div');
            item.className = 'source-item';
            item.innerHTML = `
                <strong>${source.source}</strong>: ${source.content}
                <small>Relevância: ${source.relevance}</small>`;
            content.appendChild(item);
        });

        this.sourcesDiv.appendChild(content);
    }

    scrollToBottom() {
        this.chatMessages.scrollTo({ top: this.chatMessages.scrollHeight, behavior: 'smooth' });
    }

    clearSources() {
        this.sourcesCollapsed = false;
        this.sourcesDiv.innerHTML = '';
        this.sourcesDiv.classList.remove('has-content');
        this.sourcesDiv.classList.remove('collapsed');
    }

    toggleSourcesCollapse() {
        if (!this.sourcesDiv.classList.contains('has-content')) return;

        this.sourcesCollapsed = !this.sourcesCollapsed;
        this.sourcesDiv.classList.toggle('collapsed', this.sourcesCollapsed);
    }

    resetConversation() {
        this.chatMessages.innerHTML = `
            <div class="message bot">
                <div class="msg-avatar">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                        <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                </div>
                <div class="msg-body">
                    <div class="msg-content">
                        <p>Olá! Sou seu assistente RAG. Faça perguntas sobre os documentos que você enviar.</p>
                    </div>
                    <div class="msg-time"></div>
                </div>
            </div>`;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new ChatbotRAG();
});
