class ChatbotRAG {
    constructor() {
        this.apiUrl = window.location.origin.startsWith('http')
            ? window.location.origin
            : 'http://localhost:5000';
        this.sourcesCollapsed = true;
        this.isAuthenticated = false;
        this.currentUser = null;
        this.currentAccess = null;
        this.currentUsage = null;
        this.currentDocuments = [];
        this.isMobileSidebarOpen = false;
        this.mobileSidebarBackdropTimer = null;
        this.authConfig = null;
        this.init();
    }

    async init() {
        this.cacheElements();
        this.bindEvents();
        this.configureMarkdown();
        this.setupAutoResize();
        this.resetConversation();
        await this.initializeAuth();
    }

    cacheElements() {
        this.chatMessages    = document.getElementById('chat-messages');
        this.userInput       = document.getElementById('user-input');
        this.sendButton      = document.getElementById('send-button');
        this.clearChatButton = document.getElementById('clear-chat-button');
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
        this.sessionUserPlan = document.getElementById('session-user-plan');
        this.mobileSessionUserName = document.getElementById('mobile-session-user-name');
        this.mobileSessionUserEmail = document.getElementById('mobile-session-user-email');
        this.mobileSessionUserAvatar = document.getElementById('mobile-session-user-avatar');
        this.mobileSessionUserPlan = document.getElementById('mobile-session-user-plan');
        this.uploadPolicy = document.getElementById('upload-policy');
        this.sidebar = document.querySelector('.sidebar');
        this.mobileMenuButton = document.getElementById('mobile-menu-button');
        this.mobileSidebarBackdrop = document.getElementById('mobile-sidebar-backdrop');
    }

    bindEvents() {
        this.sendButton.addEventListener('click', () => this.sendMessage());
        this.clearChatButton.addEventListener('click', () => this.resetConversation());
        this.logoutButton.addEventListener('click', () => this.logout());
        this.mobileMenuButton.addEventListener('click', () => this.toggleMobileSidebar());
        this.mobileSidebarBackdrop.addEventListener('click', () => this.closeMobileSidebar());
        window.addEventListener('resize', () => {
            if (!this.isMobileViewport()) {
                this.closeMobileSidebar({ force: true });
            }
        });

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

    isMobileViewport() {
        return window.matchMedia('(max-width: 768px)').matches;
    }

    escapeHtml(value) {
        return String(value ?? '')
            .replaceAll('&', '&amp;')
            .replaceAll('<', '&lt;')
            .replaceAll('>', '&gt;')
            .replaceAll('"', '&quot;')
            .replaceAll("'", '&#39;');
    }

    configureMarkdown() {
        if (!window.marked?.setOptions) return;

        window.marked.setOptions({
            breaks: true,
            gfm: true,
        });
    }

    renderPlainText(text) {
        const normalizedText = String(text ?? '').trim();
        if (!normalizedText) {
            return '<p></p>';
        }

        return normalizedText
            .split(/\n{2,}/)
            .map(paragraph => `<p>${this.escapeHtml(paragraph).replaceAll('\n', '<br>')}</p>`)
            .join('');
    }

    renderMarkdown(text) {
        const normalizedText = String(text ?? '').trim();
        if (!normalizedText) {
            return '<p></p>';
        }

        if (!window.marked?.parse || !window.DOMPurify?.sanitize) {
            return this.renderPlainText(normalizedText);
        }

        const rawHtml = window.marked.parse(normalizedText);
        return window.DOMPurify.sanitize(rawHtml);
    }

    hashString(value) {
        let hash = 0;
        for (const char of String(value ?? '')) {
            hash = ((hash << 5) - hash) + char.charCodeAt(0);
            hash |= 0;
        }
        return Math.abs(hash);
    }

    buildAvatarInitials(user = this.currentUser) {
        const email = String(user?.email || '').trim();
        const name = String(user?.name || '').trim();
        const source = name || email.split('@')[0] || 'U';
        const parts = source.split(/[\s._-]+/).filter(Boolean);

        if (parts.length === 0) {
            return 'U';
        }

        if (parts.length === 1) {
            return parts[0].slice(0, 2).toUpperCase();
        }

        return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
    }

    buildAvatarDataUrl(user = this.currentUser) {
        const seed = user?.email || user?.name || 'usuario';
        const hue = this.hashString(seed) % 360;
        const secondaryHue = (hue + 28) % 360;
        const initials = this.buildAvatarInitials(user);
        const svg = `
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
                <defs>
                    <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
                        <stop offset="0%" stop-color="hsl(${hue} 68% 46%)" />
                        <stop offset="100%" stop-color="hsl(${secondaryHue} 72% 30%)" />
                    </linearGradient>
                </defs>
                <rect width="64" height="64" rx="32" fill="url(#g)" />
                <text x="50%" y="53%" text-anchor="middle" dominant-baseline="middle"
                    font-family="DM Sans, Arial, sans-serif" font-size="24" font-weight="700" fill="white">
                    ${this.escapeHtml(initials)}
                </text>
            </svg>
        `;

        return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
    }

    updateSessionAvatars(user) {
        const avatarSrc = user?.picture || this.buildAvatarDataUrl(user);
        this.sessionUserAvatar.src = avatarSrc;
        this.sessionUserAvatar.hidden = false;
        this.mobileSessionUserAvatar.src = avatarSrc;
        this.mobileSessionUserAvatar.hidden = false;
    }

    buildUserAvatarMarkup(user = this.currentUser) {
        const avatarSrc = this.buildAvatarDataUrl(user);
        const altText = this.escapeHtml(user?.email || user?.name || 'Usuário');
        return `<img class="msg-avatar-image" src="${avatarSrc}" alt="${altText}">`;
    }

    getMessageContentMarkup(text, sender) {
        return sender === 'bot'
            ? this.renderMarkdown(text)
            : this.renderPlainText(text);
    }

    toggleMobileSidebar() {
        if (!this.isMobileViewport()) return;

        if (this.isMobileSidebarOpen) {
            this.closeMobileSidebar();
            return;
        }

        this.openMobileSidebar();
    }

    openMobileSidebar() {
        if (!this.isMobileViewport()) return;

        clearTimeout(this.mobileSidebarBackdropTimer);
        this.isMobileSidebarOpen = true;
        this.sidebar.classList.add('mobile-open');
        this.mobileMenuButton.setAttribute('aria-expanded', 'true');
        this.mobileSidebarBackdrop.hidden = false;
        requestAnimationFrame(() => {
            this.mobileSidebarBackdrop.classList.add('visible');
        });
        document.body.classList.add('mobile-sidebar-open');
    }

    closeMobileSidebar({ force = false } = {}) {
        if (!force && !this.isMobileSidebarOpen) return;

        clearTimeout(this.mobileSidebarBackdropTimer);
        this.isMobileSidebarOpen = false;
        this.sidebar.classList.remove('mobile-open');
        this.mobileMenuButton.setAttribute('aria-expanded', 'false');
        this.mobileSidebarBackdrop.classList.remove('visible');
        this.mobileSidebarBackdropTimer = setTimeout(() => {
            if (!this.isMobileSidebarOpen) {
                this.mobileSidebarBackdrop.hidden = true;
            }
        }, 220);
        document.body.classList.remove('mobile-sidebar-open');
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
            const planLabel = data.user?.access?.plan?.label || 'plano atual';
            this.addMessage(
                `Sessão iniciada como ${data.user?.name || data.user?.email}. Workspace isolado habilitado em ${planLabel}.`,
                'bot'
            );
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

        this.closeMobileSidebar({ force: true });
        this.setLoggedOutState();
        this.resetConversation();
        this.clearSources();
        this.documentsList.innerHTML = '<li style="color:var(--text-muted);border-style:dashed">Faça login para listar documentos</li>';
        await this.renderGoogleButton();
    }

    setAuthenticatedState(user) {
        this.isAuthenticated = true;
        this.currentUser = user;
        this.currentAccess = user?.access || null;
        this.authOverlay.classList.add('hidden');
        this.logoutButton.hidden = false;
        this.logoutButton.disabled = false;
        this.sessionUserName.textContent = user?.name || 'Usuário autenticado';
        this.sessionUserEmail.textContent = user?.email || '';
        this.mobileSessionUserName.textContent = user?.name || 'Usuário autenticado';
        this.mobileSessionUserEmail.textContent = user?.email || '';
        this.updateSessionAvatars(user);

        this.updateAccessUi();
        this.enableApp();
    }

    setLoggedOutState() {
        this.isAuthenticated = false;
        this.currentUser = null;
        this.currentAccess = null;
        this.currentUsage = null;
        this.currentDocuments = [];
        this.closeMobileSidebar({ force: true });
        this.authOverlay.classList.remove('hidden');
        this.authFeedback.textContent = 'Faça login para liberar consulta, upload e manutenção.';
        this.logoutButton.hidden = true;
        this.sessionUserName.textContent = 'Login necessário';
        this.sessionUserEmail.textContent = 'Use Google para entrar';
        this.mobileSessionUserName.textContent = 'Login necessário';
        this.mobileSessionUserEmail.textContent = 'Use Google para entrar';
        this.sessionUserPlan.textContent = 'Plano indisponível';
        this.mobileSessionUserPlan.textContent = 'Plano indisponível';
        this.sessionUserAvatar.hidden = true;
        this.sessionUserAvatar.removeAttribute('src');
        this.mobileSessionUserAvatar.hidden = true;
        this.mobileSessionUserAvatar.removeAttribute('src');
        this.updateAccessUi();
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

    formatBytes(bytes) {
        if (!Number.isFinite(bytes) || bytes <= 0) {
            return '0 MB';
        }

        const megabytes = bytes / (1024 * 1024);
        if (megabytes >= 10) {
            return `${megabytes.toFixed(0)} MB`;
        }

        return `${megabytes.toFixed(1)} MB`;
    }

    buildUploadPolicyText() {
        const access = this.currentAccess;
        const usage = this.currentUsage;

        if (!access) {
            return 'Faça login para ver os limites da sua conta.';
        }

        const parts = [access.plan?.label || 'Plano ativo'];
        const maxDocuments = access.limits?.max_documents;
        const maxFileSizeBytes = access.limits?.max_file_size_bytes;
        const usedDocuments = usage?.documents_count ?? this.currentDocuments.length;

        if (Number.isFinite(maxDocuments)) {
            parts.push(`${usedDocuments}/${maxDocuments} arquivos`);
        }

        if (Number.isFinite(maxFileSizeBytes)) {
            parts.push(`${this.formatBytes(maxFileSizeBytes)} por arquivo`);
        }

        if (usage?.limit_reached) {
            parts.push('limite atingido');
        }

        return parts.join(' · ');
    }

    updateAccessUi() {
        if (this.sessionUserPlan) {
            this.sessionUserPlan.textContent = this.currentAccess?.plan?.label || 'Plano indisponível';
        }
        if (this.mobileSessionUserPlan) {
            this.mobileSessionUserPlan.textContent = this.currentAccess?.plan?.label || 'Plano indisponível';
        }

        if (this.uploadPolicy) {
            this.uploadPolicy.textContent = this.buildUploadPolicyText();
            this.uploadPolicy.classList.toggle('is-warning', Boolean(this.currentUsage?.limit_reached));
        }
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
            this.currentAccess = data.access || this.currentAccess;
            this.currentUsage = data.usage || null;
            this.updateAccessUi();

            const llmLabel = data.llm_ready
                ? `LLM: ${data.llm_provider}`
                : 'LLM: fallback';
            const workspaceLabel = data.workspace?.scope === 'user'
                ? 'espaço isolado'
                : 'espaço global';
            const planLabel = data.access?.plan?.key || 'sem-plano';
            const documentUsageLabel = Number.isFinite(data.access?.limits?.max_documents)
                ? `${data.usage?.documents_count ?? data.documents_count}/${data.access.limits.max_documents} docs`
                : `${data.documents_count} docs`;

            this.statusIndicator.className = 'status-dot online';
            this.statusText.textContent = `Online · ${documentUsageLabel} · ${planLabel} · ${workspaceLabel} · ${llmLabel}`;
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
            this.currentDocuments = Array.isArray(data.documents) ? data.documents : [];
            this.updateAccessUi();

            this.documentsList.innerHTML = '';

            if (this.currentDocuments.length === 0) {
                this.documentsList.innerHTML = '<li style="color:var(--text-muted);border-style:dashed">Nenhum documento carregado</li>';
            } else {
                this.currentDocuments.forEach(doc => {
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
                this.closeMobileSidebar();
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
                this.closeMobileSidebar();
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

        const selectedFiles = Array.from(files);
        const maxFileSizeBytes = this.currentAccess?.limits?.max_file_size_bytes;
        const maxDocuments = this.currentAccess?.limits?.max_documents;
        const projectedDocumentNames = new Set(this.currentDocuments);

        for (const file of selectedFiles) {
            projectedDocumentNames.add(file.name);
        }

        if (Number.isFinite(maxFileSizeBytes)) {
            const oversizedFiles = selectedFiles.filter(file => file.size > maxFileSizeBytes);
            if (oversizedFiles.length > 0) {
                this.addMessage(
                    `Arquivos acima do limite de ${this.formatBytes(maxFileSizeBytes)}: ${oversizedFiles.map(file => file.name).join(', ')}`,
                    'bot'
                );
                return;
            }
        }

        if (Number.isFinite(maxDocuments) && projectedDocumentNames.size > maxDocuments) {
            this.addMessage(
                `O plano atual permite no máximo ${maxDocuments} documento(s) armazenado(s). Exclua algum arquivo antes de enviar novos.`,
                'bot'
            );
            return;
        }

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
                this.currentAccess = data.access || this.currentAccess;
                this.currentUsage = data.usage || this.currentUsage;
                this.updateAccessUi();
                this.addMessage(`✓ ${count} documento(s) enviado(s) com sucesso!`, 'bot');
                this.closeMobileSidebar();
                if (Array.isArray(data.ignored) && data.ignored.length > 0) {
                    this.addMessage(`Arquivos ignorados: ${data.ignored.join(', ')}`, 'bot');
                }
                this.fileInput.value = '';
                this.updateUploadLabel();
                this.loadDocuments();
                this.checkStatus();
            } else {
                this.currentUsage = data.usage || this.currentUsage;
                this.updateAccessUi();
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

        this.closeMobileSidebar();
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

        const botSVG = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
        const userAvatarMarkup = this.buildUserAvatarMarkup();
        const formatted = this.getMessageContentMarkup(text, sender);

        wrap.innerHTML = `
            <div class="msg-avatar ${sender === 'user' ? 'has-image' : ''}">
                ${sender === 'bot' ? botSVG : userAvatarMarkup}
            </div>
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

        this.sourcesCollapsed = true;
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
        this.sourcesDiv.classList.toggle('collapsed', this.sourcesCollapsed);
        this.updateSourcesCollapseButton(collapseButton);
    }

    scrollToBottom() {
        this.chatMessages.scrollTo({ top: this.chatMessages.scrollHeight, behavior: 'smooth' });
    }

    clearSources() {
        this.sourcesCollapsed = true;
        this.sourcesDiv.innerHTML = '';
        this.sourcesDiv.classList.remove('has-content');
        this.sourcesDiv.classList.remove('collapsed');
    }

    updateSourcesCollapseButton(button = this.sourcesDiv.querySelector('.sources-action-btn')) {
        if (!button) return;

        const label = this.sourcesCollapsed ? 'Expandir fontes' : 'Colapsar fontes';
        button.title = label;
        button.setAttribute('aria-label', label);
    }

    toggleSourcesCollapse() {
        if (!this.sourcesDiv.classList.contains('has-content')) return;

        this.sourcesCollapsed = !this.sourcesCollapsed;
        this.sourcesDiv.classList.toggle('collapsed', this.sourcesCollapsed);
        this.updateSourcesCollapseButton();
    }

    resetConversation() {
        this.chatMessages.innerHTML = '';
        this.addMessage('Olá! Sou seu assistente RAG. Faça perguntas sobre os documentos que você enviar.', 'bot');
        this.clearSources();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new ChatbotRAG();
});
