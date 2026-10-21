// overlay.js
// Injects a visual overlay to highlight target elements for explainability

window.udaaOverlay = {
    drawHighlight: (x, y, width = 20, height = 20) => {
        const el = document.createElement("div");
        el.className = "udaa-highlight";   // HandOff's own mark: not a change made by the click
        el.style.position = "fixed";
        el.style.left = `${x - width / 2}px`;
        const settingsTop = `${y - height / 2}px`; // Fix implicit global
        el.style.top = settingsTop;
        el.style.width = `${width}px`;
        el.style.height = `${height}px`;
        el.style.border = "3px solid #00f2fe"; // UDAA cyan
        el.style.backgroundColor = "rgba(0, 242, 254, 0.2)";
        el.style.borderRadius = "4px";
        el.style.pointerEvents = "none";
        el.style.zIndex = "999999";
        el.style.transition = "all 0.3s ease";

        document.body.appendChild(el);

        // Auto-remove after 1.5 seconds
        setTimeout(() => {
            el.style.opacity = "0";
            setTimeout(() => el.remove(), 300);
        }, 1500);
    },

    statusBanner: null,

    showStatus: (message, type = 'active') => {
        if (!window.udaaOverlay.statusBanner) {
            const banner = document.createElement("div");
            banner.id = "udaa-status-banner";
            banner.style.position = "fixed";
            banner.style.bottom = "20px";
            banner.style.right = "20px";
            banner.style.padding = "12px 20px";
            banner.style.borderRadius = "8px";
            banner.style.backgroundColor = "#1a1a2e"; // Dark theme
            banner.style.color = "#ffffff";
            banner.style.fontFamily = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";
            banner.style.fontSize = "14px";
            banner.style.fontWeight = "500";
            banner.style.boxShadow = "0 4px 15px rgba(0, 0, 0, 0.3)";
            banner.style.zIndex = "999999";
            banner.style.display = "flex";
            banner.style.alignItems = "center";
            banner.style.gap = "10px";
            banner.style.pointerEvents = "none";
            banner.style.transition = "all 0.3s ease";

            // Add pulse animation keyframes if not exists
            if (!document.getElementById("udaa-keyframes")) {
                const style = document.createElement("style");
                style.id = "udaa-keyframes";
                style.textContent = `
                    @keyframes udaa-pulse {
                        0% { transform: scale(1); opacity: 1; }
                        50% { transform: scale(1.1); opacity: 0.7; }
                        100% { transform: scale(1); opacity: 1; }
                    }
                `;
                document.head.appendChild(style);
            }

            const dot = document.createElement("div");
            dot.id = "udaa-status-dot";
            dot.style.width = "8px";
            dot.style.height = "8px";
            dot.style.borderRadius = "50%";
            banner.appendChild(dot);

            const text = document.createElement("span");
            text.id = "udaa-status-text";
            banner.appendChild(text);

            document.body.appendChild(banner);
            window.udaaOverlay.statusBanner = banner;
        }

        const banner = window.udaaOverlay.statusBanner;
        const textEl = banner.querySelector("#udaa-status-text");
        const dotEl = banner.querySelector("#udaa-status-dot");

        textEl.textContent = message;

        if (type === 'active') {
            banner.style.border = "1px solid #00f2fe";
            dotEl.style.backgroundColor = "#00f2fe";
            dotEl.style.animation = "udaa-pulse 1.5s infinite ease-in-out";
        } else if (type === 'completed') {
            banner.style.border = "1px solid #2ecc71"; // Green
            dotEl.style.backgroundColor = "#2ecc71";
            dotEl.style.animation = "none";
        } else if (type === 'error') {
            banner.style.border = "1px solid #e74c3c"; // Red
            dotEl.style.backgroundColor = "#e74c3c";
            dotEl.style.animation = "none";
        }
    },

    hideStatus: () => {
        if (window.udaaOverlay.statusBanner) {
            window.udaaOverlay.statusBanner.style.opacity = "0";
            setTimeout(() => {
                if (window.udaaOverlay.statusBanner) {
                    window.udaaOverlay.statusBanner.remove();
                    window.udaaOverlay.statusBanner = null;
                }
            }, 300);
        }
    }
};
