/**
 * Ambient Context Engine — Frontend Controller
 * Complete interactive manager for Chat, Grounded Citations, Timeline,
 * Activity Analytics, Library Search, Command Palette, Custom Pills,
 * Mode/Depth Selectors, and Manual Capture Shutter.
 */

document.addEventListener('DOMContentLoaded', () => {
    // ─── Global State ────────────────────────────────────────────────
    let currentTab = 'chat';
    let hasChatted = false;
    let timelineOffset = 0;
    const timelineLimit = 40;
    let totalTimelineEpisodes = 0;
    let currentInspectorEpId = null;
    let searchDebounceTimer = null;
    let paletteSearchTimer = null;

    // Active query options
    let currentMode = 'hybrid'; // 'hybrid' | 'semantic' | 'keyword'
    let currentDepth = 10;      // 3 | 10 | 25
    let captureRunning = true;

    // ─── DOM Element References ──────────────────────────────────────
    const navItems = document.querySelectorAll('.nav-item');
    const viewTitle = document.getElementById('view-title');
    const viewSub = document.getElementById('view-sub');
    const statDbHeader = document.getElementById('stat-db-header');
    const statCapsHeader = document.getElementById('stat-caps-header');
    const headerModelName = document.getElementById('header-model-name');
    const ollamaStatusDot = document.getElementById('ollama-status-dot');
    const sidebarEpCount = document.getElementById('sidebar-ep-count');
    const recentsList = document.getElementById('recents-list');
    
    // View Panes
    const paneChat = document.getElementById('pane-chat');
    const paneTimeline = document.getElementById('pane-timeline');
    const paneActivity = document.getElementById('pane-activity');
    const paneLibrary = document.getElementById('pane-library');
    const paneScheduled = document.getElementById('pane-scheduled');
    const paneConnections = document.getElementById('pane-connections');
    const paneSettings = document.getElementById('pane-settings');
    const allPanes = [paneChat, paneTimeline, paneActivity, paneLibrary, paneScheduled, paneConnections, paneSettings];

    // Chat Elements
    const welcomeState = document.getElementById('welcome-state');
    const chatHistory = document.getElementById('chat-history');
    const chatInput = document.getElementById('chat-input');
    const chatSubmit = document.getElementById('chat-submit');
    const btnDayRecap = document.getElementById('btn-day-recap');
    const btnInsights = document.getElementById('btn-insights');
    const nudgeText = document.getElementById('nudge-text');
    const actionPillsContainer = document.getElementById('action-pills-container');
    const btnCustomPrompt = document.getElementById('btn-custom-prompt');
    const bottomInputContainer = document.getElementById('bottom-input-container');

    // Popover Elements & Triggers
    const btnAttachMenu = document.getElementById('btn-attach-menu');
    const popoverAttach = document.getElementById('popover-attach');
    const btnModeToggle = document.getElementById('btn-mode-toggle');
    const popoverMode = document.getElementById('popover-mode');
    const labelModeBtn = document.getElementById('label-mode-btn');
    const btnDepthToggle = document.getElementById('btn-depth-toggle');
    const popoverDepth = document.getElementById('popover-depth');
    const labelDepthBtn = document.getElementById('label-depth-btn');
    const allPopovers = [popoverAttach, popoverMode, popoverDepth];

    // Popover Actions
    const popoverActionSnapshot = document.getElementById('popover-action-snapshot');
    const popoverActionClear = document.getElementById('popover-action-clear');
    const popoverActionRecap = document.getElementById('popover-action-recap');
    const popoverActionCustom = document.getElementById('popover-action-custom');

    // Shutter & Flash Elements
    const btnCaptureShutter = document.getElementById('btn-capture-shutter');
    const screenFlash = document.getElementById('screen-flash');
    const toastContainer = document.getElementById('toast-container');

    // Command Palette Elements
    const btnQuickSearch = document.getElementById('btn-quick-search');
    const btnPaletteTriggerBar = document.getElementById('btn-palette-trigger-bar');
    const modalCommandPalette = document.getElementById('modal-command-palette');
    const paletteSearchInput = document.getElementById('palette-search-input');
    const paletteResultsList = document.getElementById('palette-results-list');

    // Custom Pill Modal Elements
    const modalCustomPill = document.getElementById('modal-custom-pill');
    const btnCloseCustomModal = document.getElementById('btn-close-custom-modal');
    const btnCancelCustomPill = document.getElementById('btn-cancel-custom-pill');
    const btnSaveCustomPill = document.getElementById('btn-save-custom-pill');
    const customPillLabel = document.getElementById('custom-pill-label');
    const customPillQuery = document.getElementById('custom-pill-query');

    // Help Modal Elements
    const btnHelp = document.getElementById('btn-help');
    const modalHelp = document.getElementById('modal-help');
    const btnCloseHelpModal = document.getElementById('btn-close-help-modal');
    const btnCloseHelpModal2 = document.getElementById('btn-close-help-modal-2');

    // Timeline Elements
    const timelineContainer = document.getElementById('timeline-container');
    const timelineSearchInput = document.getElementById('timeline-search-input');
    const timelineProcessFilter = document.getElementById('timeline-process-filter');
    const timelineDateFilter = document.getElementById('timeline-date-filter');
    const btnRefreshTimeline = document.getElementById('btn-refresh-timeline');
    const timelineCountDisplay = document.getElementById('timeline-count-display');
    const btnLoadMoreEpisodes = document.getElementById('btn-load-more-episodes');
    const timelinePagination = document.getElementById('timeline-pagination');

    // Activity Elements
    const activityDateSelector = document.getElementById('activity-date-selector');
    const kpiTotalTime = document.getElementById('kpi-total-time');
    const kpiTotalEpisodes = document.getElementById('kpi-total-episodes');
    const kpiTotalCaptures = document.getElementById('kpi-total-captures');
    const kpiTopApp = document.getElementById('kpi-top-app');
    const appBreakdownContainer = document.getElementById('app-breakdown-container');
    const hourlyBarsContainer = document.getElementById('hourly-bars-container');
    const topWindowsContainer = document.getElementById('top-windows-container');

    // Library Elements
    const librarySearchInput = document.getElementById('library-search-input');
    const btnLibrarySearch = document.getElementById('btn-library-search');
    const libraryResultsContainer = document.getElementById('library-results-container');
    const libraryResultsMeta = document.getElementById('library-results-meta');

    // Settings Elements
    const settingUseTemporal = document.getElementById('setting-use-temporal');
    const settingUseEpisodes = document.getElementById('setting-use-episodes');
    const settingUseGrounding = document.getElementById('setting-use-grounding');
    const settingModelSelect = document.getElementById('setting-model-select');

    // Drawer Elements
    const drawerOverlay = document.getElementById('drawer-overlay');
    const inspectorDrawer = document.getElementById('inspector-drawer');
    const btnCloseDrawer = document.getElementById('btn-close-drawer');
    const drawerEpId = document.getElementById('drawer-ep-id');
    const drawerTitle = document.getElementById('drawer-title');
    const drawerProc = document.getElementById('drawer-proc');
    const drawerDur = document.getElementById('drawer-dur');
    const drawerTime = document.getElementById('drawer-time');
    const drawerCapsCount = document.getElementById('drawer-caps-count');
    const drawerRepText = document.getElementById('drawer-rep-text');
    const btnCopyDrawerText = document.getElementById('btn-copy-drawer-text');
    const drawerCapturesContainer = document.getElementById('drawer-captures-container');
    const btnAskAboutEpisode = document.getElementById('btn-ask-about-episode');

    // Day Recap Modal Elements
    const modalRecapOverlay = document.getElementById('modal-recap-overlay');
    const btnCloseRecapModal = document.getElementById('btn-close-recap-modal');
    const btnCloseRecapModal2 = document.getElementById('btn-close-recap-modal-2');
    const modalRecapDate = document.getElementById('modal-recap-date');
    const modalRecapSummary = document.getElementById('modal-recap-summary');
    const modalRecapTime = document.getElementById('modal-recap-time');
    const modalRecapEpisodes = document.getElementById('modal-recap-episodes');
    const modalRecapHighlights = document.getElementById('modal-recap-highlights');
    const btnChatDeeperRecap = document.getElementById('btn-chat-deeper-recap');

    // Power Toggle
    const btnPowerToggle = document.getElementById('btn-power-toggle');
    const schedStatusLabel = document.getElementById('sched-status-label');
    const schedLiveDot = document.getElementById('sched-live-dot');

    // ─── Toast Notification Helper ───────────────────────────────────
    function showToast(message, type = 'success') {
        if (!toastContainer) return;
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        
        let iconName = 'check-circle';
        if (type === 'warn') iconName = 'alert-triangle';
        if (type === 'info') iconName = 'info';

        toast.innerHTML = `
            <i data-lucide="${iconName}" class="icon-xs text-lime"></i>
            <span>${escapeHtml(message)}</span>
        `;
        toastContainer.appendChild(toast);
        lucide.createIcons({ root: toast });

        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(20px)';
            toast.style.transition = 'all 0.25s ease';
            setTimeout(() => toast.remove(), 250);
        }, 3200);
    }

    // ─── Popovers Manager ────────────────────────────────────────────
    function closeAllPopovers() {
        allPopovers.forEach(p => {
            if (p) p.classList.add('hidden');
        });
    }

    function togglePopover(popoverEl) {
        if (!popoverEl) return;
        const isHidden = popoverEl.classList.contains('hidden');
        closeAllPopovers();
        if (isHidden) {
            popoverEl.classList.remove('hidden');
        }
    }

    if (btnAttachMenu) {
        btnAttachMenu.addEventListener('click', (e) => {
            e.stopPropagation();
            togglePopover(popoverAttach);
        });
    }

    if (btnModeToggle) {
        btnModeToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            togglePopover(popoverMode);
        });
    }

    if (btnDepthToggle) {
        btnDepthToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            togglePopover(popoverDepth);
        });
    }

    // Close popovers when clicking outside
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.input-box') && !e.target.closest('.floating-popover')) {
            closeAllPopovers();
        }
    });

    // Popover Mode items
    if (popoverMode) {
        popoverMode.querySelectorAll('.popover-item').forEach(item => {
            item.addEventListener('click', () => {
                popoverMode.querySelectorAll('.popover-item').forEach(i => {
                    i.classList.remove('active');
                    const check = i.querySelector('.check-icon');
                    if (check) check.classList.add('hidden');
                });
                item.classList.add('active');
                const check = item.querySelector('.check-icon');
                if (check) check.classList.remove('hidden');

                currentMode = item.getAttribute('data-mode') || 'hybrid';
                if (labelModeBtn) {
                    labelModeBtn.innerText = currentMode.toUpperCase();
                }
                closeAllPopovers();
                showToast(`Search mode set to ${currentMode.toUpperCase()}`, 'info');
            });
        });
    }

    // Popover Depth items
    if (popoverDepth) {
        popoverDepth.querySelectorAll('.popover-item').forEach(item => {
            item.addEventListener('click', () => {
                popoverDepth.querySelectorAll('.popover-item').forEach(i => {
                    i.classList.remove('active');
                    const check = i.querySelector('.check-icon');
                    if (check) check.classList.add('hidden');
                });
                item.classList.add('active');
                const check = item.querySelector('.check-icon');
                if (check) check.classList.remove('hidden');

                const depthVal = parseInt(item.getAttribute('data-depth'), 10) || 10;
                const depthLabel = item.getAttribute('data-label') || 'MEDIUM';
                currentDepth = depthVal;
                if (labelDepthBtn) {
                    labelDepthBtn.innerText = depthLabel;
                }
                closeAllPopovers();
                showToast(`Reasoning depth set to ${depthLabel} (${depthVal} episodes)`, 'info');
            });
        });
    }

    // Popover Attach actions
    if (popoverActionSnapshot) {
        popoverActionSnapshot.addEventListener('click', () => {
            closeAllPopovers();
            handleManualCapture();
        });
    }

    if (popoverActionClear) {
        popoverActionClear.addEventListener('click', () => {
            closeAllPopovers();
            clearChatSession();
        });
    }

    if (popoverActionRecap) {
        popoverActionRecap.addEventListener('click', () => {
            closeAllPopovers();
            openDayRecapModal();
        });
    }

    if (popoverActionCustom) {
        popoverActionCustom.addEventListener('click', () => {
            closeAllPopovers();
            openCustomPillModal();
        });
    }

    // ─── Manual Screen Capture Shutter ───────────────────────────────
    async function handleManualCapture() {
        // Visual shutter flash
        if (screenFlash) {
            screenFlash.classList.add('active');
            setTimeout(() => screenFlash.classList.remove('active'), 180);
        }

        try {
            const res = await fetch('/api/capture_now', { method: 'POST' });
            const data = await res.json();

            if (data.status === 'success') {
                showToast(`📸 Captured frame #${data.id} (${data.process_name || 'Active Screen'})`, 'success');
                fetchSystemStatus();
                fetchRecents();
                if (currentTab === 'timeline') loadEpisodes(true);
            } else {
                showToast('Capture error: ' + (data.error || 'Failed'), 'warn');
            }
        } catch (e) {
            showToast('Failed to trigger capture.', 'warn');
        }
    }

    if (btnCaptureShutter) {
        btnCaptureShutter.addEventListener('click', handleManualCapture);
    }

    function clearChatSession() {
        chatHistory.innerHTML = '';
        hasChatted = false;
        welcomeState.classList.remove('hidden');
        chatHistory.classList.add('hidden');
        chatInput.value = '';
        chatInput.style.height = 'auto';
        chatInput.focus();
        showToast('Chat conversation cleared', 'info');
    }

    // ─── Command Palette (Ctrl+K) ────────────────────────────────────
    const defaultCommands = [
        { id: 'nav-chat', icon: 'message-square', category: 'Navigation', title: 'Go to Chat', desc: 'Personal Grounded Assistant', action: () => switchTab('chat') },
        { id: 'nav-timeline', icon: 'calendar', category: 'Navigation', title: 'Go to Timeline', desc: 'Chronological activity episodes', action: () => switchTab('timeline') },
        { id: 'nav-activity', icon: 'activity', category: 'Navigation', title: 'Go to Activity Analytics', desc: 'Screen time and app distribution', action: () => switchTab('activity') },
        { id: 'nav-library', icon: 'library', category: 'Navigation', title: 'Go to Context Library', desc: 'Full-text search across OCR captures', action: () => switchTab('library') },
        { id: 'nav-settings', icon: 'settings', category: 'Navigation', title: 'Go to Settings', desc: 'Model flags and privacy verification', action: () => switchTab('settings') },
        { id: 'act-snapshot', icon: 'camera', category: 'Actions', title: 'Snapshot Screen Now', desc: 'Instantly grab active screen frame and index', action: () => handleManualCapture() },
        { id: 'act-recap', icon: 'calendar-days', category: 'Actions', title: 'Day Recap Summary', desc: 'Review focus hours and completed tasks', action: () => openDayRecapModal() },
        { id: 'act-clear', icon: 'trash-2', category: 'Actions', title: 'Clear Chat Conversation', desc: 'Reset conversation history', action: () => clearChatSession() },
        { id: 'act-custom', icon: 'plus-circle', category: 'Actions', title: 'Create Custom Action Pill', desc: 'Add personal prompt template shortcut', action: () => openCustomPillModal() },
    ];

    let paletteSelectedIndex = 0;
    let paletteCurrentItems = [];

    function openCommandPalette() {
        if (!modalCommandPalette) return;
        modalCommandPalette.classList.remove('hidden');
        paletteSearchInput.value = '';
        paletteSelectedIndex = 0;
        renderPaletteItems(defaultCommands);
        paletteSearchInput.focus();
    }

    function closeCommandPalette() {
        if (modalCommandPalette) modalCommandPalette.classList.add('hidden');
    }

    function renderPaletteItems(items) {
        paletteCurrentItems = items;
        paletteResultsList.innerHTML = '';

        if (!items || items.length === 0) {
            paletteResultsList.innerHTML = '<div style="color:var(--text-muted); padding:1.5rem 0; text-align:center; font-size:0.85rem;">No matching commands or episodes found.</div>';
            return;
        }

        let currentCat = '';
        items.forEach((item, idx) => {
            if (item.category && item.category !== currentCat) {
                currentCat = item.category;
                const catEl = document.createElement('div');
                catEl.className = 'palette-category-title';
                catEl.innerText = currentCat;
                paletteResultsList.appendChild(catEl);
            }

            const el = document.createElement('button');
            el.className = `palette-item ${idx === paletteSelectedIndex ? 'selected' : ''}`;
            el.setAttribute('data-idx', idx);
            el.innerHTML = `
                <i data-lucide="${item.icon || 'arrow-right'}" class="icon-xs" style="color:var(--accent-neon)"></i>
                <div class="palette-item-text">
                    <strong>${escapeHtml(item.title)}</strong>
                    <small>${escapeHtml(item.desc || '')}</small>
                </div>
            `;

            el.addEventListener('click', () => {
                executePaletteItem(item);
            });

            paletteResultsList.appendChild(el);
        });

        lucide.createIcons({ root: paletteResultsList });
    }

    function executePaletteItem(item) {
        closeCommandPalette();
        if (item.action) {
            item.action();
        } else if (item.episodeId) {
            openInspectorDrawer(item.episodeId);
        }
    }

    if (btnQuickSearch) btnQuickSearch.addEventListener('click', openCommandPalette);
    if (btnPaletteTriggerBar) btnPaletteTriggerBar.addEventListener('click', openCommandPalette);

    if (paletteSearchInput) {
        paletteSearchInput.addEventListener('input', () => {
            clearTimeout(paletteSearchTimer);
            const q = paletteSearchInput.value.trim().toLowerCase();
            if (!q) {
                paletteSelectedIndex = 0;
                renderPaletteItems(defaultCommands);
                return;
            }

            // Local filter on commands
            const matchedCommands = defaultCommands.filter(c => 
                c.title.toLowerCase().includes(q) || (c.desc && c.desc.toLowerCase().includes(q))
            );

            // Fetch live episodes matching query
            paletteSearchTimer = setTimeout(async () => {
                try {
                    const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
                    const data = await res.json();
                    const epMatches = (data.episodes || []).slice(0, 5).map(ep => ({
                        id: `ep-${ep.id}`,
                        icon: 'layers',
                        category: 'Matching Episodes',
                        title: `[E${ep.id}] ${ep.dominant_title || ep.process_name}`,
                        desc: ep.representative_text ? ep.representative_text.slice(0, 80) + '...' : ep.duration_formatted,
                        episodeId: ep.id
                    }));

                    paletteSelectedIndex = 0;
                    renderPaletteItems([...matchedCommands, ...epMatches]);
                } catch (e) {
                    paletteSelectedIndex = 0;
                    renderPaletteItems(matchedCommands);
                }
            }, 180);
        });

        paletteSearchInput.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                if (paletteCurrentItems.length > 0) {
                    paletteSelectedIndex = (paletteSelectedIndex + 1) % paletteCurrentItems.length;
                    updatePaletteSelection();
                }
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                if (paletteCurrentItems.length > 0) {
                    paletteSelectedIndex = (paletteSelectedIndex - 1 + paletteCurrentItems.length) % paletteCurrentItems.length;
                    updatePaletteSelection();
                }
            } else if (e.key === 'Enter') {
                e.preventDefault();
                if (paletteCurrentItems[paletteSelectedIndex]) {
                    executePaletteItem(paletteCurrentItems[paletteSelectedIndex]);
                }
            } else if (e.key === 'Escape') {
                closeCommandPalette();
            }
        });
    }

    function updatePaletteSelection() {
        const items = paletteResultsList.querySelectorAll('.palette-item');
        items.forEach((item, idx) => {
            if (idx === paletteSelectedIndex) {
                item.classList.add('selected');
                item.scrollIntoView({ block: 'nearest' });
            } else {
                item.classList.remove('selected');
            }
        });
    }

    if (modalCommandPalette) {
        modalCommandPalette.addEventListener('click', (e) => {
            if (e.target === modalCommandPalette) closeCommandPalette();
        });
    }

    // Global Keyboard Shortcuts
    document.addEventListener('keydown', (e) => {
        // Ctrl+K / Cmd+K -> Command Palette
        if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
            e.preventDefault();
            openCommandPalette();
        }
        // Alt+S -> Screen Snapshot
        if (e.altKey && (e.key === 's' || e.key === 'S')) {
            e.preventDefault();
            handleManualCapture();
        }
        // Alt+C -> Clear Chat
        if (e.altKey && (e.key === 'c' || e.key === 'C')) {
            e.preventDefault();
            clearChatSession();
        }
        // Alt+A -> Attach Menu
        if (e.altKey && (e.key === 'a' || e.key === 'A')) {
            e.preventDefault();
            togglePopover(popoverAttach);
        }
        // Esc -> Dismiss Modals & Drawers
        if (e.key === 'Escape') {
            closeAllPopovers();
            closeCommandPalette();
            closeCustomPillModal();
            closeHelpModal();
            closeInspectorDrawer();
            closeDayRecapModal();
        }
    });

    // ─── Custom Action Pills Manager ─────────────────────────────────
    function loadCustomActionPills() {
        if (!actionPillsContainer || !btnCustomPrompt) return;
        
        // Remove existing custom pill wraps
        actionPillsContainer.querySelectorAll('.custom-pill-wrap').forEach(el => el.remove());

        let savedPills = [];
        try {
            savedPills = JSON.parse(localStorage.getItem('ambient_custom_pills') || '[]');
        } catch (e) {
            savedPills = [];
        }

        savedPills.forEach(p => {
            const wrap = document.createElement('div');
            wrap.className = 'pill-wrap custom-pill-wrap';

            const pill = document.createElement('button');
            pill.className = 'pill';
            pill.innerText = p.label;
            pill.setAttribute('data-query', p.query);
            pill.addEventListener('click', () => {
                chatInput.value = p.query;
                handleChatSubmit(p.query);
            });

            const delBtn = document.createElement('button');
            delBtn.className = 'pill-delete-btn';
            delBtn.innerHTML = '&times;';
            delBtn.title = 'Delete shortcut';
            delBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                deleteCustomActionPill(p.label);
            });

            wrap.appendChild(pill);
            wrap.appendChild(delBtn);
            actionPillsContainer.insertBefore(wrap, btnCustomPrompt);
        });
    }

    function openCustomPillModal() {
        if (!modalCustomPill) return;
        customPillLabel.value = '';
        customPillQuery.value = '';
        modalCustomPill.classList.remove('hidden');
        customPillLabel.focus();
    }

    function closeCustomPillModal() {
        if (modalCustomPill) modalCustomPill.classList.add('hidden');
    }

    function saveCustomActionPill() {
        const label = customPillLabel.value.trim();
        const query = customPillQuery.value.trim();
        if (!label || !query) {
            alert('Please provide both a label and a prompt query template.');
            return;
        }

        let saved = [];
        try {
            saved = JSON.parse(localStorage.getItem('ambient_custom_pills') || '[]');
        } catch (e) {
            saved = [];
        }

        saved = saved.filter(p => p.label !== label);
        saved.push({ label, query });
        localStorage.setItem('ambient_custom_pills', JSON.stringify(saved));

        closeCustomPillModal();
        loadCustomActionPills();
        showToast(`Saved custom action pill "${label}"`, 'success');
    }

    function deleteCustomActionPill(label) {
        let saved = [];
        try {
            saved = JSON.parse(localStorage.getItem('ambient_custom_pills') || '[]');
        } catch (e) {
            saved = [];
        }
        saved = saved.filter(p => p.label !== label);
        localStorage.setItem('ambient_custom_pills', JSON.stringify(saved));
        loadCustomActionPills();
        showToast(`Removed custom action pill "${label}"`, 'info');
    }

    if (btnCustomPrompt) btnCustomPrompt.addEventListener('click', openCustomPillModal);
    if (btnCloseCustomModal) btnCloseCustomModal.addEventListener('click', closeCustomPillModal);
    if (btnCancelCustomPill) btnCancelCustomPill.addEventListener('click', closeCustomPillModal);
    if (btnSaveCustomPill) btnSaveCustomPill.addEventListener('click', saveCustomActionPill);
    if (modalCustomPill) {
        modalCustomPill.addEventListener('click', (e) => {
            if (e.target === modalCustomPill) closeCustomPillModal();
        });
    }

    // ─── Help & Architecture Modal ───────────────────────────────────
    function openHelpModal() {
        if (modalHelp) modalHelp.classList.remove('hidden');
    }
    function closeHelpModal() {
        if (modalHelp) modalHelp.classList.add('hidden');
    }
    if (btnHelp) btnHelp.addEventListener('click', openHelpModal);
    if (btnCloseHelpModal) btnCloseHelpModal.addEventListener('click', closeHelpModal);
    if (btnCloseHelpModal2) btnCloseHelpModal2.addEventListener('click', closeHelpModal);
    if (modalHelp) {
        modalHelp.addEventListener('click', (e) => {
            if (e.target === modalHelp) closeHelpModal();
        });
    }

    // ─── Power Button Toggle in Sidebar ──────────────────────────────
    if (btnPowerToggle) {
        btnPowerToggle.addEventListener('click', () => {
            captureRunning = !captureRunning;
            if (captureRunning) {
                schedStatusLabel.innerText = 'Continuous Capture (5s)';
                schedLiveDot.style.backgroundColor = 'var(--accent-green)';
                btnPowerToggle.style.color = 'var(--accent-neon)';
                showToast('Continuous capture loop: Active (5s)', 'success');
            } else {
                schedStatusLabel.innerText = 'Continuous Capture (Paused)';
                schedLiveDot.style.backgroundColor = 'var(--text-muted)';
                btnPowerToggle.style.color = 'var(--text-muted)';
                showToast('Continuous capture loop: Standby', 'warn');
            }
        });
    }

    // ─── Tab Navigation Manager ──────────────────────────────────────
    function switchTab(tabId) {
        currentTab = tabId;
        closeAllPopovers();
        
        // Update nav items
        navItems.forEach(item => {
            if (item.getAttribute('data-tab') === tabId) {
                item.classList.add('active');
            } else {
                item.classList.remove('active');
            }
        });

        // Hide all panes
        allPanes.forEach(pane => {
            if (pane) pane.classList.add('hidden');
        });

        // Show input bar only in chat or timeline view
        if (bottomInputContainer) {
            bottomInputContainer.style.display = (tabId === 'chat') ? 'flex' : 'none';
        }

        // Title and Pane activation
        switch (tabId) {
            case 'chat':
                viewTitle.innerText = 'Chat';
                viewSub.innerText = 'Personal Grounded Assistant';
                paneChat.classList.remove('hidden');
                if (hasChatted) {
                    welcomeState.classList.add('hidden');
                    chatHistory.classList.remove('hidden');
                } else {
                    welcomeState.classList.remove('hidden');
                    chatHistory.classList.add('hidden');
                }
                break;
            case 'timeline':
                viewTitle.innerText = 'Timeline';
                viewSub.innerText = 'Chronological Activity Episodes';
                paneTimeline.classList.remove('hidden');
                loadEpisodes(true);
                break;
            case 'activity':
                viewTitle.innerText = 'Activity Analytics';
                viewSub.innerText = 'Productivity & Screen Time Breakdown';
                paneActivity.classList.remove('hidden');
                loadActivity();
                break;
            case 'library':
                viewTitle.innerText = 'Context Library';
                viewSub.innerText = 'Full-Text Search Across OCR & Transcripts';
                paneLibrary.classList.remove('hidden');
                librarySearchInput.focus();
                break;
            case 'scheduled':
                viewTitle.innerText = 'Scheduled Tasks';
                viewSub.innerText = 'Background Daemons & Automations';
                paneScheduled.classList.remove('hidden');
                break;
            case 'connections':
                viewTitle.innerText = 'Connections';
                viewSub.innerText = 'Hardware Grabbers & Local Models';
                paneConnections.classList.remove('hidden');
                break;
            case 'settings':
                viewTitle.innerText = 'Settings';
                viewSub.innerText = 'Model Config & Privacy Proof';
                paneSettings.classList.remove('hidden');
                loadSettings();
                break;
        }

        lucide.createIcons();
    }

    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const tabId = item.getAttribute('data-tab');
            if (tabId) switchTab(tabId);
        });
    });

    // ─── Status & Recents Initializer ────────────────────────────────
    async function fetchSystemStatus() {
        try {
            const res = await fetch('/api/status');
            const data = await res.json();
            
            if (statDbHeader) statDbHeader.innerText = data.db_size_mb || '0';
            if (statCapsHeader) statCapsHeader.innerText = data.total_captures || '0';
            if (sidebarEpCount) sidebarEpCount.innerText = data.total_episodes || '0';
            if (headerModelName) headerModelName.innerText = data.active_model || 'llama3.2:3b';
            
            if (ollamaStatusDot) {
                if (data.ollama_online) {
                    ollamaStatusDot.style.backgroundColor = 'var(--accent-neon)';
                    ollamaStatusDot.title = 'Ollama Local LLM: Online';
                } else {
                    ollamaStatusDot.style.backgroundColor = 'var(--accent-amber)';
                    ollamaStatusDot.title = 'Offline Grounded Synthesizer: Active (Zero Telemetry)';
                }
            }

            // Populate settings checkboxes
            if (settingUseTemporal) settingUseTemporal.checked = !!data.use_temporal;
            if (settingUseEpisodes) settingUseEpisodes.checked = !!data.use_episodes;
            if (settingUseGrounding) settingUseGrounding.checked = !!data.use_grounding;
            if (settingModelSelect && data.active_model) settingModelSelect.value = data.active_model;

        } catch (e) {
            console.warn('Status fetch error:', e);
        }
    }

    async function fetchNudgeInsight() {
        if (!nudgeText) return;
        try {
            const res = await fetch('/api/nudge');
            const data = await res.json();
            nudgeText.innerText = data.nudge || "You're doing great. Steady cadence detected.";
        } catch (e) {
            nudgeText.innerText = "Steady workflow pattern observed.";
        }
    }

    async function fetchRecents() {
        if (!recentsList) return;
        try {
            const res = await fetch('/api/episodes?limit=4');
            const data = await res.json();
            recentsList.innerHTML = '';
            
            if (!data.episodes || data.episodes.length === 0) {
                recentsList.innerHTML = '<span style="font-size:0.75rem; color:var(--text-muted); padding:0 8px;">No recent episodes</span>';
                return;
            }

            data.episodes.forEach(ep => {
                const row = document.createElement('div');
                row.className = 'recent-nav-row';
                row.title = ep.dominant_title || ep.process_name;
                row.innerHTML = `
                    <i data-lucide="file-code" class="icon-xs" style="color:var(--accent-neon)"></i>
                    <span style="overflow:hidden; text-overflow:ellipsis;">${escapeHtml(ep.dominant_title || ep.process_name)}</span>
                `;
                row.addEventListener('click', () => {
                    openInspectorDrawer(ep.id);
                });
                recentsList.appendChild(row);
            });
            lucide.createIcons({ root: recentsList });
        } catch (e) {
            console.warn('Recents fetch error:', e);
        }
    }

    // ─── Chat Implementation ─────────────────────────────────────────
    chatInput.addEventListener('input', () => {
        chatInput.style.height = 'auto';
        chatInput.style.height = Math.min(chatInput.scrollHeight, 180) + 'px';
    });

    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleChatSubmit();
        }
    });

    chatSubmit.addEventListener('click', () => handleChatSubmit());

    async function handleChatSubmit(overrideText = null) {
        const question = (overrideText || chatInput.value).trim();
        if (!question) return;

        closeAllPopovers();

        // Transition from welcome state to conversation history
        if (!hasChatted) {
            hasChatted = true;
            welcomeState.classList.add('hidden');
            chatHistory.classList.remove('hidden');
        }

        // Switch to chat tab if not active
        if (currentTab !== 'chat') {
            switchTab('chat');
        }

        // Append user message
        appendUserMessage(question);
        chatInput.value = '';
        chatInput.style.height = 'auto';

        // Add loading indicator
        const loadingId = 'loading-' + Date.now();
        const loadingEl = document.createElement('div');
        loadingEl.id = loadingId;
        loadingEl.className = 'message ai';
        loadingEl.innerHTML = `
            <div class="msg-header">
                <i data-lucide="cpu" class="icon-sm text-lime"></i>
                <span>Ambient Agent</span>
                <span class="latency-tag">Recalling context & verifying citations...</span>
            </div>
            <div class="msg-content" style="color: var(--text-muted); display:flex; align-items:center; gap:8px;">
                <span class="pulse-dot"></span>
                <span>Searching local vector memory (${currentMode}, top ${currentDepth}) and verifying grounding...</span>
            </div>
        `;
        chatHistory.appendChild(loadingEl);
        lucide.createIcons({ root: loadingEl });
        scrollToBottom();

        try {
            const res = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    question,
                    top_k: currentDepth,
                    mode: currentMode
                })
            });
            const data = await res.json();
            
            const loader = document.getElementById(loadingId);
            if (loader) loader.remove();

            if (data.error) {
                appendAssistantMessage("⚠️ " + data.error, { refused: true, refusal_reason: data.error });
            } else {
                appendAssistantMessage(data.answer, data);
            }
        } catch (e) {
            const loader = document.getElementById(loadingId);
            if (loader) loader.remove();
            appendAssistantMessage("⚠️ Network error communicating with local agent server.", { refused: true });
        }
    }

    function appendUserMessage(text) {
        const msg = document.createElement('div');
        msg.className = 'message user';
        msg.innerHTML = `<div class="msg-content">${escapeHtml(text)}</div>`;
        chatHistory.appendChild(msg);
        scrollToBottom();
    }

    function appendAssistantMessage(rawAnswer, meta = {}) {
        const msg = document.createElement('div');
        msg.className = 'message ai';

        // Badges formatting
        let badgeHtml = '';
        if (meta.refused) {
            badgeHtml = `<span class="grounding-tag refused"><i data-lucide="shield-alert" class="icon-xs"></i> Refusal Guard</span>`;
        } else if (meta.grounding_rate !== undefined && meta.grounding_rate !== null) {
            const pct = Math.round(meta.grounding_rate * 100);
            if (pct >= 80) {
                badgeHtml = `<span class="grounding-tag verified"><i data-lucide="check-check" class="icon-xs"></i> Verified Grounded (${pct}%)</span>`;
            } else if (pct >= 50) {
                badgeHtml = `<span class="grounding-tag partial"><i data-lucide="check" class="icon-xs"></i> Partially Verified (${pct}%)</span>`;
            } else {
                badgeHtml = `<span class="grounding-tag partial">${pct}% Grounded</span>`;
            }
        }

        const latencyHtml = (meta.search_time_ms !== undefined)
            ? `<span class="latency-tag">Search: ${meta.search_time_ms}ms · Gen: ${meta.generate_time_ms}ms</span>`
            : '';

        // Format markdown & inline citation pills
        const formattedBody = formatMarkdownWithCitations(rawAnswer);

        // Build sources tray if sources are available
        let sourcesTrayHtml = '';
        if (meta.sources && meta.sources.length > 0) {
            const sourceCards = meta.sources.map(s => {
                const epId = s.id || s.episode_id || '?';
                const timeStr = formatIsoTime(s.timestamp || s.start_time);
                const titleStr = s.dominant_title || s.window_title || s.process_name || 'Activity';
                return `
                    <div class="source-card" data-ep-id="${epId}">
                        <div class="source-card-top">
                            <span class="source-ep-id">[E${epId}]</span>
                            <span class="source-time">${timeStr}</span>
                        </div>
                        <div class="source-title">${escapeHtml(titleStr)}</div>
                    </div>
                `;
            }).join('');

            sourcesTrayHtml = `
                <div class="sources-tray">
                    <button class="sources-toggle">
                        <i data-lucide="layers" class="icon-xs"></i>
                        <span>Cited Sources (${meta.sources.length} episodes)</span>
                        <i data-lucide="chevron-down" class="icon-xs arrow-icon"></i>
                    </button>
                    <div class="sources-cards-grid hidden">
                        ${sourceCards}
                    </div>
                </div>
            `;
        }

        msg.innerHTML = `
            <div class="msg-header">
                <i data-lucide="cpu" class="icon-sm" style="color:var(--accent-neon)"></i>
                <strong style="color:var(--text-primary); font-weight:600;">Ambient Agent</strong>
                <div class="msg-badges">
                    ${badgeHtml}
                    ${latencyHtml}
                </div>
            </div>
            <div class="msg-content">
                ${formattedBody}
                ${sourcesTrayHtml}
            </div>
        `;

        // Wire citation pill clicks
        msg.querySelectorAll('.citation-pill').forEach(pill => {
            pill.addEventListener('click', () => {
                const epId = pill.getAttribute('data-ep-id');
                if (epId) openInspectorDrawer(epId);
            });
        });

        // Wire source card clicks
        msg.querySelectorAll('.source-card').forEach(card => {
            card.addEventListener('click', () => {
                const epId = card.getAttribute('data-ep-id');
                if (epId) openInspectorDrawer(epId);
            });
        });

        // Wire sources accordion toggle
        const trayToggle = msg.querySelector('.sources-toggle');
        if (trayToggle) {
            trayToggle.addEventListener('click', () => {
                const grid = msg.querySelector('.sources-cards-grid');
                if (grid) {
                    grid.classList.toggle('hidden');
                    const arrow = trayToggle.querySelector('.arrow-icon');
                    if (arrow) arrow.style.transform = grid.classList.contains('hidden') ? 'rotate(0deg)' : 'rotate(180deg)';
                }
            });
        }

        chatHistory.appendChild(msg);
        lucide.createIcons({ root: msg });
        scrollToBottom();
    }

    function scrollToBottom() {
        const scrollArea = document.getElementById('workspace-scroll-area');
        if (scrollArea) {
            scrollArea.scrollTop = scrollArea.scrollHeight;
        }
    }

    // ─── Markdown & Citation Formatting ──────────────────────────────
    function formatMarkdownWithCitations(text) {
        if (!text) return '';

        // Replace citation tags [E123] or [C456] with interactive pill elements
        let processed = text.replace(/\[E(\d+)\]/g, (match, p1) => {
            return `<button class="citation-pill" data-ep-id="${p1}" title="Inspect Episode [E${p1}]"><i data-lucide="layers" class="icon-xs"></i> [E${p1}]</button>`;
        });
        processed = processed.replace(/\[C(\d+)\]/g, (match, p1) => {
            return `<button class="citation-pill" data-cap-id="${p1}" title="Capture [C${p1}]"><i data-lucide="image" class="icon-xs"></i> [C${p1}]</button>`;
        });

        // Code blocks
        processed = processed.replace(/```([\w-]*)\n([\s\S]*?)```/g, (match, lang, code) => {
            return `<pre><code class="language-${lang}">${escapeHtml(code.trim())}</code></pre>`;
        });

        // Inline code
        processed = processed.replace(/`([^`]+)`/g, '<code>$1</code>');

        // Headers
        processed = processed.replace(/^### (.*$)/gim, '<h3>$1</h3>');
        processed = processed.replace(/^## (.*$)/gim, '<h2>$1</h2>');
        processed = processed.replace(/^# (.*$)/gim, '<h2>$1</h2>');

        // Bold & Italic
        processed = processed.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        processed = processed.replace(/\*(.*?)\*/g, '<em>$1</em>');

        // Blockquotes
        processed = processed.replace(/^\> (.*$)/gim, '<blockquote>$1</blockquote>');

        // Lists
        processed = processed.replace(/^\s*-\s+(.*$)/gim, '<li>$1</li>');
        processed = processed.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>');

        // Paragraphs
        const lines = processed.split('\n\n');
        processed = lines.map(p => {
            p = p.trim();
            if (p.startsWith('<h') || p.startsWith('<pre') || p.startsWith('<ul') || p.startsWith('<blockquote')) {
                return p;
            }
            return `<p>${p.replace(/\n/g, '<br>')}</p>`;
        }).join('');

        return processed;
    }

    // ─── Action Pills & Quick Prompts ────────────────────────────────
    actionPillsContainer.querySelectorAll('.pill:not(.custom-pill)').forEach(pill => {
        pill.addEventListener('click', () => {
            const query = pill.getAttribute('data-query');
            if (query) {
                chatInput.value = query;
                handleChatSubmit(query);
            }
        });
    });

    if (btnDayRecap) {
        btnDayRecap.addEventListener('click', () => {
            openDayRecapModal();
        });
    }

    if (btnInsights) {
        btnInsights.addEventListener('click', () => {
            handleChatSubmit("What patterns, insights, or productivity improvements can you derive from my sessions?");
        });
    }

    // ─── Timeline Feed Manager ───────────────────────────────────────
    async function loadEpisodes(reset = false) {
        if (!timelineContainer) return;
        if (reset) {
            timelineOffset = 0;
            timelineContainer.innerHTML = '<div style="color:var(--text-muted); padding:2rem 0; text-align:center;">Loading activity episodes...</div>';
        }

        const q = timelineSearchInput ? timelineSearchInput.value.trim() : '';
        const proc = timelineProcessFilter ? timelineProcessFilter.value : '';
        const dateVal = timelineDateFilter ? timelineDateFilter.value : '';

        const url = `/api/episodes?limit=${timelineLimit}&offset=${timelineOffset}&q=${encodeURIComponent(q)}&process=${encodeURIComponent(proc)}&date=${encodeURIComponent(dateVal)}`;

        try {
            const res = await fetch(url);
            const data = await res.json();
            
            if (reset) {
                timelineContainer.innerHTML = '';
            }

            totalTimelineEpisodes = data.total || 0;
            if (timelineCountDisplay) {
                timelineCountDisplay.innerText = `Showing ${Math.min(timelineOffset + data.episodes.length, totalTimelineEpisodes)} of ${totalTimelineEpisodes} episodes`;
            }

            // Populate process filter options if needed
            if (reset && timelineProcessFilter && data.processes && timelineProcessFilter.children.length <= 1) {
                data.processes.forEach(p => {
                    const opt = document.createElement('option');
                    opt.value = p;
                    opt.innerText = p;
                    timelineProcessFilter.appendChild(opt);
                });
            }

            if (!data.episodes || data.episodes.length === 0) {
                if (reset) {
                    timelineContainer.innerHTML = '<div style="color:var(--text-muted); padding:3rem 0; text-align:center;">No matching activity episodes found.</div>';
                }
                if (timelinePagination) timelinePagination.classList.add('hidden');
                return;
            }

            data.episodes.forEach(ep => {
                const card = document.createElement('div');
                card.className = 'episode-card';
                card.setAttribute('data-id', ep.id);
                
                const timeSpan = `${formatIsoTime(ep.start_time)} - ${formatIsoTime(ep.end_time)}`;
                const excerpt = ep.representative_text ? escapeHtml(ep.representative_text.slice(0, 240)) : 'No text content';

                card.innerHTML = `
                    <div class="episode-header">
                        <div class="episode-header-left">
                            <span class="ep-id-tag">[E${ep.id}]</span>
                            <span class="app-badge">${escapeHtml(ep.process_name || 'System')}</span>
                            <span class="episode-duration-pill">${ep.duration_formatted}</span>
                        </div>
                        <span style="font-size:0.75rem; color:var(--text-muted);">${timeSpan}</span>
                    </div>
                    <div class="episode-title">${escapeHtml(ep.dominant_title || 'Untitled Session')}</div>
                    <div class="episode-text-snippet">${excerpt}...</div>
                    <div class="episode-footer">
                        <span><i data-lucide="image" class="icon-xs" style="vertical-align:middle"></i> ${ep.capture_count} captures</span>
                        <div style="display:flex; gap:8px;">
                            <button class="btn-outline btn-ask-ep" data-id="${ep.id}" data-title="${escapeHtml(ep.dominant_title || '')}">Ask AI</button>
                            <button class="btn-secondary btn-inspect-ep" data-id="${ep.id}">Inspect</button>
                        </div>
                    </div>
                `;

                // Card clicks
                card.querySelector('.btn-inspect-ep').addEventListener('click', (e) => {
                    e.stopPropagation();
                    openInspectorDrawer(ep.id);
                });

                card.querySelector('.btn-ask-ep').addEventListener('click', (e) => {
                    e.stopPropagation();
                    const title = ep.dominant_title || ep.process_name;
                    handleChatSubmit(`What was I doing in episode [E${ep.id}] ("${title}")?`);
                });

                card.addEventListener('click', () => {
                    openInspectorDrawer(ep.id);
                });

                timelineContainer.appendChild(card);
            });

            lucide.createIcons({ root: timelineContainer });

            // Pagination button toggle
            if (timelinePagination) {
                if (timelineOffset + data.episodes.length < totalTimelineEpisodes) {
                    timelinePagination.classList.remove('hidden');
                } else {
                    timelinePagination.classList.add('hidden');
                }
            }

        } catch (e) {
            console.error('Error loading episodes:', e);
            if (reset) {
                timelineContainer.innerHTML = '<div style="color:var(--accent-rose); padding:2rem 0; text-align:center;">Failed to load episodes.</div>';
            }
        }
    }

    if (btnLoadMoreEpisodes) {
        btnLoadMoreEpisodes.addEventListener('click', () => {
            timelineOffset += timelineLimit;
            loadEpisodes(false);
        });
    }

    if (timelineSearchInput) {
        timelineSearchInput.addEventListener('input', () => {
            clearTimeout(searchDebounceTimer);
            searchDebounceTimer = setTimeout(() => {
                loadEpisodes(true);
            }, 300);
        });
    }

    if (timelineProcessFilter) {
        timelineProcessFilter.addEventListener('change', () => loadEpisodes(true));
    }
    if (timelineDateFilter) {
        timelineDateFilter.addEventListener('change', () => loadEpisodes(true));
    }
    if (btnRefreshTimeline) {
        btnRefreshTimeline.addEventListener('click', () => loadEpisodes(true));
    }

    // ─── Activity Analytics Manager ──────────────────────────────────
    async function loadActivity(date = '') {
        try {
            const url = date ? `/api/activity?date=${encodeURIComponent(date)}` : '/api/activity';
            const res = await fetch(url);
            const data = await res.json();

            // Populate Available Dates Selector
            if (activityDateSelector && data.available_dates) {
                const currentVal = activityDateSelector.value || data.date;
                activityDateSelector.innerHTML = '';
                data.available_dates.forEach(d => {
                    const opt = document.createElement('option');
                    opt.value = d;
                    opt.innerText = d;
                    if (d === currentVal) opt.selected = true;
                    activityDateSelector.appendChild(opt);
                });
            }

            // Populate KPI Cards
            if (kpiTotalTime) kpiTotalTime.innerText = data.total_active_formatted || '0s';
            if (kpiTotalEpisodes) kpiTotalEpisodes.innerText = data.total_episodes || '0';
            if (kpiTotalCaptures) kpiTotalCaptures.innerText = data.total_captures || '0';
            if (kpiTopApp) {
                const topApp = (data.app_breakdown && data.app_breakdown[0]) ? data.app_breakdown[0].process_name : '--';
                kpiTopApp.innerText = topApp;
            }

            // Populate App Breakdown Bars
            if (appBreakdownContainer) {
                appBreakdownContainer.innerHTML = '';
                if (!data.app_breakdown || data.app_breakdown.length === 0) {
                    appBreakdownContainer.innerHTML = '<span style="color:var(--text-muted); font-size:0.8rem;">No activity data recorded.</span>';
                } else {
                    data.app_breakdown.forEach(app => {
                        const row = document.createElement('div');
                        row.className = 'app-stat-row';
                        row.innerHTML = `
                            <div class="app-stat-info">
                                <strong>${escapeHtml(app.process_name)}</strong>
                                <span>${app.duration_formatted} (${app.percentage}%)</span>
                            </div>
                            <div class="progress-track">
                                <div class="progress-fill" style="width: ${app.percentage}%;"></div>
                            </div>
                        `;
                        appBreakdownContainer.appendChild(row);
                    });
                }
            }

            // Populate Hourly Bars
            if (hourlyBarsContainer) {
                hourlyBarsContainer.innerHTML = '';
                const hourly = data.hourly_distribution || [];
                const maxCount = Math.max(...hourly.map(h => h.count), 1);

                hourly.forEach(h => {
                    const col = document.createElement('div');
                    col.className = 'hour-col';
                    col.title = `${h.label}: ${h.count} captures`;
                    
                    const heightPct = Math.max(Math.round((h.count / maxCount) * 100), 4);
                    col.innerHTML = `
                        <div class="hour-bar-fill" style="height: ${heightPct}%;"></div>
                        <span class="hour-label">${h.hour % 3 === 0 ? h.hour : ''}</span>
                    `;
                    hourlyBarsContainer.appendChild(col);
                });
            }

            // Populate Top Windows
            if (topWindowsContainer) {
                topWindowsContainer.innerHTML = '';
                if (!data.top_windows || data.top_windows.length === 0) {
                    topWindowsContainer.innerHTML = '<span style="color:var(--text-muted); font-size:0.8rem;">No window titles recorded.</span>';
                } else {
                    data.top_windows.forEach(w => {
                        const row = document.createElement('div');
                        row.className = 'window-row';
                        row.innerHTML = `
                            <span>${escapeHtml(w.window_title)}</span>
                            <strong>${w.count} events</strong>
                        `;
                        topWindowsContainer.appendChild(row);
                    });
                }
            }

        } catch (e) {
            console.error('Error loading activity analytics:', e);
        }
    }

    if (activityDateSelector) {
        activityDateSelector.addEventListener('change', () => {
            loadActivity(activityDateSelector.value);
        });
    }

    // ─── Library Full-Text Search ────────────────────────────────────
    async function executeLibrarySearch() {
        if (!librarySearchInput || !libraryResultsContainer) return;
        const q = librarySearchInput.value.trim();
        if (!q) return;

        libraryResultsMeta.innerText = `Searching local FTS5 index for "${q}"...`;
        libraryResultsContainer.innerHTML = '';

        try {
            const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
            const data = await res.json();

            const epMatches = data.episodes || [];
            const capMatches = data.captures || [];
            const totalMatches = epMatches.length + capMatches.length;

            libraryResultsMeta.innerText = `Found ${totalMatches} matching results for "${q}"`;

            if (totalMatches === 0) {
                libraryResultsContainer.innerHTML = '<div style="color:var(--text-muted); padding:2rem 0; text-align:center;">No matching entries in SQLite full-text index.</div>';
                return;
            }

            epMatches.forEach(ep => {
                const card = document.createElement('div');
                card.className = 'library-result-card';
                card.innerHTML = `
                    <div class="library-card-header">
                        <div style="display:flex; align-items:center; gap:6px;">
                            <span class="ep-id-tag">[E${ep.id}]</span>
                            <span class="app-badge">${escapeHtml(ep.process_name || 'System')}</span>
                        </div>
                        <span style="font-size:0.75rem; color:var(--text-muted);">${formatIsoTime(ep.start_time)}</span>
                    </div>
                    <strong style="font-size:0.9rem; color:var(--text-primary);">${escapeHtml(ep.dominant_title || '')}</strong>
                    <div class="library-card-text">${highlightSearchTerm(ep.representative_text, q)}</div>
                `;
                card.addEventListener('click', () => openInspectorDrawer(ep.id));
                libraryResultsContainer.appendChild(card);
            });

            capMatches.forEach(cap => {
                const card = document.createElement('div');
                card.className = 'library-result-card';
                card.innerHTML = `
                    <div class="library-card-header">
                        <div style="display:flex; align-items:center; gap:6px;">
                            <span class="ep-id-tag">[C${cap.id}]</span>
                            <span class="app-badge">${escapeHtml(cap.process_name || cap.source)}</span>
                        </div>
                        <span style="font-size:0.75rem; color:var(--text-muted);">${formatIsoTime(cap.timestamp)}</span>
                    </div>
                    <div style="font-size:0.85rem; color:var(--text-secondary);">${escapeHtml(cap.window_title || '')}</div>
                    <div class="library-card-text">${highlightSearchTerm(cap.text_content, q)}</div>
                `;
                libraryResultsContainer.appendChild(card);
            });

        } catch (e) {
            libraryResultsMeta.innerText = 'Search error.';
            console.error('Library search error:', e);
        }
    }

    if (btnLibrarySearch) {
        btnLibrarySearch.addEventListener('click', executeLibrarySearch);
    }
    if (librarySearchInput) {
        librarySearchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') executeLibrarySearch();
        });
    }

    // ─── Settings Manager ────────────────────────────────────────────
    async function loadSettings() {
        try {
            const res = await fetch('/api/settings');
            const data = await res.json();
            if (settingUseTemporal) settingUseTemporal.checked = !!data.use_temporal;
            if (settingUseEpisodes) settingUseEpisodes.checked = !!data.use_episodes;
            if (settingUseGrounding) settingUseGrounding.checked = !!data.use_grounding;
            if (settingModelSelect && data.ollama_model) settingModelSelect.value = data.ollama_model;
        } catch (e) {
            console.warn('Settings load error:', e);
        }
    }

    async function saveSettingChange(payload) {
        try {
            await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            fetchSystemStatus();
            showToast('Settings updated', 'info');
        } catch (e) {
            console.error('Failed to save settings:', e);
        }
    }

    if (settingUseTemporal) {
        settingUseTemporal.addEventListener('change', () => {
            saveSettingChange({ use_temporal: settingUseTemporal.checked });
        });
    }
    if (settingUseEpisodes) {
        settingUseEpisodes.addEventListener('change', () => {
            saveSettingChange({ use_episodes: settingUseEpisodes.checked });
        });
    }
    if (settingUseGrounding) {
        settingUseGrounding.addEventListener('change', () => {
            saveSettingChange({ use_grounding: settingUseGrounding.checked });
        });
    }
    if (settingModelSelect) {
        settingModelSelect.addEventListener('change', () => {
            saveSettingChange({ ollama_model: settingModelSelect.value });
        });
    }

    // ─── Inspector Drawer Manager ────────────────────────────────────
    async function openInspectorDrawer(episodeId) {
        if (!inspectorDrawer || !drawerOverlay) return;
        currentInspectorEpId = episodeId;

        drawerOverlay.classList.remove('hidden');
        inspectorDrawer.classList.remove('hidden');

        drawerEpId.innerText = `Episode #${episodeId}`;
        drawerTitle.innerText = 'Loading episode details...';
        drawerRepText.innerText = 'Fetching centroid text...';
        drawerCapturesContainer.innerHTML = '';

        try {
            const res = await fetch(`/api/episodes/${episodeId}`);
            const data = await res.json();
            const ep = data.episode;

            drawerTitle.innerText = ep.dominant_title || 'Untitled Session';
            drawerProc.innerText = ep.process_name || 'System';
            drawerDur.innerText = ep.duration_formatted || '0s';
            drawerTime.innerText = `${formatIsoTime(ep.start_time)} - ${formatIsoTime(ep.end_time)}`;
            drawerCapsCount.innerText = `${ep.capture_count} captures`;
            drawerRepText.innerText = ep.representative_text || '(No representative text)';

            // Populate Associated Captures
            const captures = data.captures || [];
            if (captures.length === 0) {
                drawerCapturesContainer.innerHTML = '<span style="font-size:0.75rem; color:var(--text-muted);">No raw captures mapped.</span>';
            } else {
                captures.forEach(c => {
                    const item = document.createElement('div');
                    item.className = 'drawer-capture-item';
                    item.innerHTML = `
                        <div class="drawer-capture-top">
                            <span style="font-family: 'JetBrains Mono', monospace; color:var(--accent-neon);">[C${c.id}]</span>
                            <span>${formatIsoTime(c.timestamp)}</span>
                        </div>
                        <div class="drawer-capture-snippet">${escapeHtml(c.text_content ? c.text_content.slice(0, 160) : '')}</div>
                    `;
                    drawerCapturesContainer.appendChild(item);
                });
            }

        } catch (e) {
            drawerTitle.innerText = 'Error loading episode';
            drawerRepText.innerText = 'Failed to fetch episode details.';
        }

        lucide.createIcons({ root: inspectorDrawer });
    }

    function closeInspectorDrawer() {
        if (inspectorDrawer) inspectorDrawer.classList.add('hidden');
        if (drawerOverlay) drawerOverlay.classList.add('hidden');
        currentInspectorEpId = null;
    }

    if (btnCloseDrawer) btnCloseDrawer.addEventListener('click', closeInspectorDrawer);
    if (drawerOverlay) drawerOverlay.addEventListener('click', closeInspectorDrawer);

    if (btnCopyDrawerText) {
        btnCopyDrawerText.addEventListener('click', () => {
            if (drawerRepText && drawerRepText.innerText) {
                navigator.clipboard.writeText(drawerRepText.innerText);
                btnCopyDrawerText.innerHTML = '<i data-lucide="check" class="icon-xs text-lime"></i>';
                lucide.createIcons({ root: btnCopyDrawerText });
                showToast('Representative text copied to clipboard', 'info');
                setTimeout(() => {
                    btnCopyDrawerText.innerHTML = '<i data-lucide="copy" class="icon-xs"></i>';
                    lucide.createIcons({ root: btnCopyDrawerText });
                }, 1500);
            }
        });
    }

    if (btnAskAboutEpisode) {
        btnAskAboutEpisode.addEventListener('click', () => {
            if (currentInspectorEpId) {
                const epId = currentInspectorEpId;
                const title = drawerTitle.innerText;
                closeInspectorDrawer();
                handleChatSubmit(`What was I doing in episode [E${epId}] ("${title}")?`);
            }
        });
    }

    // ─── Day Recap Modal Manager ─────────────────────────────────────
    async function openDayRecapModal() {
        if (!modalRecapOverlay) return;
        modalRecapOverlay.classList.remove('hidden');
        modalRecapSummary.innerText = 'Synthesizing day recap from indexed episodes...';

        try {
            const res = await fetch('/api/recap');
            const data = await res.json();

            modalRecapDate.innerText = `Recap for ${data.date || 'Today'}`;
            modalRecapSummary.innerText = data.summary || 'No activity recorded for this date.';
            modalRecapTime.innerText = data.total_time || '0s';
            modalRecapEpisodes.innerText = data.total_episodes || '0';

            modalRecapHighlights.innerHTML = '';
            const highlights = data.highlights || [];
            if (highlights.length === 0) {
                modalRecapHighlights.innerHTML = '<span style="color:var(--text-muted); font-size:0.8rem;">No significant highlights found.</span>';
            } else {
                highlights.forEach(h => {
                    const item = document.createElement('div');
                    item.className = 'recap-highlight-item';
                    item.innerHTML = `
                        <div class="recap-highlight-top">
                            <span class="app-badge">${escapeHtml(h.process)}</span>
                            <span>${h.time} (${h.duration})</span>
                        </div>
                        <div class="recap-highlight-title">${escapeHtml(h.title)}</div>
                    `;
                    modalRecapHighlights.appendChild(item);
                });
            }

        } catch (e) {
            modalRecapSummary.innerText = 'Failed to synthesize recap.';
        }

        lucide.createIcons({ root: modalRecapOverlay });
    }

    function closeDayRecapModal() {
        if (modalRecapOverlay) modalRecapOverlay.classList.add('hidden');
    }

    if (btnCloseRecapModal) btnCloseRecapModal.addEventListener('click', closeDayRecapModal);
    if (btnCloseRecapModal2) btnCloseRecapModal2.addEventListener('click', closeDayRecapModal);
    if (modalRecapOverlay) {
        modalRecapOverlay.addEventListener('click', (e) => {
            if (e.target === modalRecapOverlay) closeDayRecapModal();
        });
    }

    if (btnChatDeeperRecap) {
        btnChatDeeperRecap.addEventListener('click', () => {
            closeDayRecapModal();
            handleChatSubmit("Give me a comprehensive day recap: my top accomplishments, tasks completed, and any unfinished work.");
        });
    }

    // ─── Utility Helpers ─────────────────────────────────────────────
    function formatIsoTime(isoStr) {
        if (!isoStr) return '--';
        try {
            const dt = new Date(isoStr);
            if (isNaN(dt.getTime())) return isoStr.slice(11, 16);
            return dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        } catch (e) {
            return isoStr.slice(11, 16);
        }
    }

    function escapeHtml(str) {
        if (!str) return '';
        return str
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function highlightSearchTerm(text, term) {
        if (!text) return '';
        const escaped = escapeHtml(text.slice(0, 240));
        if (!term) return escaped;
        const re = new RegExp(`(${escapeHtml(term)})`, 'gi');
        return escaped.replace(re, '<mark style="background:rgba(163,230,53,0.3); color:var(--text-primary); border-radius:2px; padding:0 2px;">$1</mark>');
    }

    // ─── Initial App Boot ────────────────────────────────────────────
    fetchSystemStatus();
    fetchNudgeInsight();
    fetchRecents();
    loadCustomActionPills();
    setInterval(fetchSystemStatus, 15000); // Live heartbeat
});
