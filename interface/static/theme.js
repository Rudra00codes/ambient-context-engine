/**
 * OmniContext Multi-Palette Theme Manager
 * Combines palettes config, useTheme hook behavior, and accessible PalettePicker
 * for vanilla DOM (4 palettes x light/dark = 8 themes).
 */
(function () {
  const PALETTES = [
    { id: 'crimson', label: 'Crimson editorial', swatch: ['#FAF8F5', '#141414', '#D7263D'] },
    { id: 'cobalt', label: 'Electric cobalt', swatch: ['#F7F8FA', '#0B1020', '#2F5BFF'] },
    { id: 'lime', label: 'Ink and lime', swatch: ['#F4F4EF', '#111111', '#C6F432'] },
    { id: 'orange', label: 'Warm signal orange', swatch: ['#FBF7F2', '#1C1917', '#FF5A1F'] },
  ];

  const DEFAULT_PALETTE = 'crimson';
  const PALETTE_KEY = 'omnicontext-palette';
  // Only an explicit toggle is saved; without it the site follows the OS light/dark setting
  const THEME_KEY = 'omnicontext-theme-choice';

  const isPalette = (id) => PALETTES.some((p) => p.id === id);
  const read = (k) => {
    try { return localStorage.getItem(k); } catch { return null; }
  };
  const write = (k, v) => {
    try { localStorage.setItem(k, v); } catch { /* private mode */ }
  };

  function getInitialTheme() {
    return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
  }

  function getInitialPalette() {
    const applied = document.documentElement.getAttribute('data-palette');
    return isPalette(applied) ? applied : DEFAULT_PALETTE;
  }

  let currentTheme = getInitialTheme();
  let currentPalette = getInitialPalette();
  const listeners = new Set();

  function applyAttributes() {
    const root = document.documentElement;
    root.setAttribute('data-theme', currentTheme);
    root.setAttribute('data-palette', currentPalette);
    const bg = getComputedStyle(root).getPropertyValue('--bg').trim();
    if (bg) {
      const meta = document.querySelector('meta[name="theme-color"]');
      if (meta) meta.setAttribute('content', bg);
    }
    listeners.forEach((fn) => fn({ theme: currentTheme, palette: currentPalette }));
  }

  function toggleTheme() {
    currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
    write(THEME_KEY, currentTheme);
    applyAttributes();
  }

  function setPalette(id) {
    if (!isPalette(id)) return;
    currentPalette = id;
    write(PALETTE_KEY, id);
    applyAttributes();
  }

  // Follow the OS until the visitor explicitly picks a theme
  if (window.matchMedia) {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onOsChange = (e) => {
      if (read(THEME_KEY) === null) {
        currentTheme = e.matches ? 'dark' : 'light';
        applyAttributes();
      }
    };
    if (mq.addEventListener) {
      mq.addEventListener('change', onOsChange);
    } else if (mq.addListener) {
      mq.addListener(onOsChange);
    }
  }

  function createChip(swatch) {
    const chip = document.createElement('span');
    chip.className = 'palette-chip';
    chip.setAttribute('aria-hidden', 'true');
    swatch.forEach((c) => {
      const i = document.createElement('i');
      i.style.background = c;
      chip.appendChild(i);
    });
    return chip;
  }

  function mountThemeControls(container) {
    if (!container) return;

    // ─── Palette Picker (Swatch Button + Accessible Menu) ───────────
    const wrap = document.createElement('div');
    wrap.className = 'theme-picker-wrap';
    wrap.style.position = 'relative';

    const pickerBtn = document.createElement('button');
    pickerBtn.type = 'button';
    pickerBtn.className = 'btn btn-secondary nav-theme-btn';
    pickerBtn.id = 'btn-palette-picker';
    pickerBtn.setAttribute('aria-haspopup', 'menu');
    pickerBtn.setAttribute('aria-expanded', 'false');

    const menu = document.createElement('div');
    menu.className = 'palette-menu hidden';
    menu.setAttribute('role', 'menu');
    menu.setAttribute('aria-label', 'Colour palette');

    let isOpen = false;

    function renderPickerButton() {
      const active = PALETTES.find((p) => p.id === currentPalette) || PALETTES[0];
      pickerBtn.setAttribute('aria-label', `Colour palette: ${active.label}`);
      pickerBtn.title = `Palette: ${active.label}`;
      pickerBtn.innerHTML = '';
      pickerBtn.appendChild(createChip(active.swatch));
    }

    function renderMenuOptions() {
      menu.innerHTML = '';
      PALETTES.forEach((p) => {
        const opt = document.createElement('button');
        opt.type = 'button';
        opt.setAttribute('role', 'menuitemradio');
        opt.setAttribute('aria-checked', String(currentPalette === p.id));
        opt.className = 'palette-option';
        opt.appendChild(createChip(p.swatch));
        const labelSpan = document.createElement('span');
        labelSpan.textContent = p.label;
        opt.appendChild(labelSpan);
        opt.addEventListener('click', () => {
          setPalette(p.id);
          closeMenu(true);
        });
        menu.appendChild(opt);
      });
    }

    function openMenu() {
      isOpen = true;
      pickerBtn.setAttribute('aria-expanded', 'true');
      renderMenuOptions();
      menu.classList.remove('hidden');
      requestAnimationFrame(() => {
        const checked = menu.querySelector('[aria-checked="true"]');
        if (checked) checked.focus();
      });
    }

    function closeMenu(returnFocus) {
      if (!isOpen) return;
      isOpen = false;
      pickerBtn.setAttribute('aria-expanded', 'false');
      menu.classList.add('hidden');
      if (returnFocus) pickerBtn.focus();
    }

    pickerBtn.addEventListener('click', () => {
      if (isOpen) closeMenu(false);
      else openMenu();
    });

    document.addEventListener('pointerdown', (e) => {
      if (isOpen && !wrap.contains(e.target)) {
        closeMenu(false);
      }
    });

    wrap.addEventListener('focusout', () => {
      if (!isOpen) return;
      requestAnimationFrame(() => {
        if (isOpen && !wrap.contains(document.activeElement)) {
          closeMenu(false);
        }
      });
    });

    document.addEventListener('keydown', (e) => {
      if (!isOpen) return;
      if (e.key === 'Escape') {
        e.preventDefault();
        closeMenu(true);
        return;
      }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        const items = Array.from(menu.querySelectorAll('[role="menuitemradio"]'));
        const idx = items.indexOf(document.activeElement);
        const next = e.key === 'ArrowDown'
          ? (idx + 1) % items.length
          : (idx - 1 + items.length) % items.length;
        if (items[next]) items[next].focus();
        e.preventDefault();
      }
    });

    wrap.appendChild(pickerBtn);
    wrap.appendChild(menu);

    // ─── Light / Dark Toggle Button ─────────────────────────────────
    const toggleBtn = document.createElement('button');
    toggleBtn.type = 'button';
    toggleBtn.className = 'btn btn-secondary nav-theme-btn';
    toggleBtn.id = 'btn-theme-toggle';

    function renderToggleButton() {
      const isDark = currentTheme === 'dark';
      toggleBtn.setAttribute('aria-label', isDark ? 'Switch to light mode' : 'Switch to dark mode');
      toggleBtn.title = isDark ? 'Switch to light mode' : 'Switch to dark mode';
      toggleBtn.innerHTML = isDark
        ? '<i data-lucide="sun" class="icon-xs"></i><span>Light</span>'
        : '<i data-lucide="moon" class="icon-xs"></i><span>Dark</span>';
      if (window.lucide && typeof window.lucide.createIcons === 'function') {
        window.lucide.createIcons({ root: toggleBtn });
      }
    }

    toggleBtn.addEventListener('click', toggleTheme);

    // Initial render + subscribe to state changes
    renderPickerButton();
    renderToggleButton();
    listeners.add(() => {
      renderPickerButton();
      renderMenuOptions();
      renderToggleButton();
    });

    container.appendChild(wrap);
    container.appendChild(toggleBtn);
  }

  window.OmniTheme = {
    PALETTES,
    DEFAULT_PALETTE,
    PALETTE_KEY,
    THEME_KEY,
    isPalette,
    getTheme: () => currentTheme,
    getPalette: () => currentPalette,
    toggleTheme,
    setPalette,
    mountThemeControls,
  };

  document.addEventListener('DOMContentLoaded', () => {
    const mount = document.getElementById('theme-controls-mount');
    if (mount) mountThemeControls(mount);
    applyAttributes();
  });
})();
