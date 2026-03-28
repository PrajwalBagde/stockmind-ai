// ─── Navbar Scroll Effect ────────────────────────────────────────────────────
window.addEventListener('scroll', () => {
    const nav = document.getElementById('navbar');
    if (nav) nav.classList.toggle('scrolled', window.scrollY > 20);
});

// ─── Mobile Nav Toggle ───────────────────────────────────────────────────────
document.getElementById('nav-toggle')?.addEventListener('click', () => {
    document.getElementById('nav-links')?.classList.toggle('open');
});

// Close mobile nav when clicking a link
document.querySelectorAll('.nav-link').forEach(link => {
    link.addEventListener('click', () => {
        document.getElementById('nav-links')?.classList.remove('open');
    });
});

// ─── User Dropdown ───────────────────────────────────────────────────────────
document.getElementById('user-menu-btn')?.addEventListener('click', (e) => {
    e.stopPropagation();
    const dd = document.getElementById('user-dropdown');
    dd?.classList.toggle('open');
    const chevron = document.querySelector('#user-menu-btn .fa-chevron-down, #user-menu-btn .fa-chevron-up');
    if (chevron) chevron.classList.toggle('fa-chevron-up');
});

document.addEventListener('click', () => {
    document.getElementById('user-dropdown')?.classList.remove('open');
});

// ─── Flash Message Auto-dismiss ──────────────────────────────────────────────
document.querySelectorAll('.flash-msg').forEach(msg => {
    setTimeout(() => {
        msg.style.animation = 'slideOut 0.3s ease-in forwards';
        setTimeout(() => msg.remove(), 300);
    }, 5000);
});

// ─── Utility Functions ───────────────────────────────────────────────────────

/**
 * Format number as Indian Rupees
 */
function formatINR(num) {
    if (!num && num !== 0) return '₹0';
    return '₹' + parseFloat(num).toLocaleString('en-IN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}

/**
 * Format large volumes to human-readable
 */
function formatVolume(vol) {
    if (!vol) return '0';
    if (vol >= 10000000) return (vol / 10000000).toFixed(2) + ' Cr';
    if (vol >= 100000) return (vol / 100000).toFixed(2) + ' L';
    if (vol >= 1000) return (vol / 1000).toFixed(1) + ' K';
    return vol.toString();
}

/**
 * Show a toast notification
 */
function showToast(message, duration = 3000) {
    const existing = document.querySelector('.toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.innerHTML = `<i class="fas fa-check-circle" style="color: var(--green); margin-right: 8px;"></i>${message}`;
    document.body.appendChild(toast);

    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease-in forwards';
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

// ─── Slide Out Animation ─────────────────────────────────────────────────────
const slideOutStyle = document.createElement('style');
slideOutStyle.textContent = `
    @keyframes slideOut {
        from { opacity: 1; transform: translateX(0); }
        to { opacity: 0; transform: translateX(40px); }
    }
`;
document.head.appendChild(slideOutStyle);

// ─── Number Counter Animation ────────────────────────────────────────────────
function animateValue(element, start, end, duration) {
    const startTime = performance.now();
    const update = (currentTime) => {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3); // easeOutCubic
        const current = start + (end - start) * eased;
        element.textContent = formatINR(current);
        if (progress < 1) requestAnimationFrame(update);
    };
    requestAnimationFrame(update);
}

// ─── Page Visibility API — Pause updates when tab is hidden ──────────────────
let isPageVisible = true;
document.addEventListener('visibilitychange', () => {
    isPageVisible = !document.hidden;
});

console.log('%c🚀 StockPulse India', 'color: #6366f1; font-size: 16px; font-weight: bold;');
console.log('%cIndian Stock Market Dashboard', 'color: #94a3b8; font-size: 12px;');
