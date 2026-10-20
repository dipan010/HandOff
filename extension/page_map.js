// page_map.js
// Builds a short list of what a person can see and use on the page right now:
// buttons, links, boxes to type in, dropdowns, checkboxes... Each one gets a
// number (stored in a data-handoff-id attribute) so the backend can say
// "click 12" or "type 'Delhi' into 4".
//
// Plain DOM code only (no chrome.* calls) so it also runs in an ordinary page
// for testing. Exposes window.handoffPage.

(function () {
    if (window.handoffPage) return;

    const ID_ATTR = "data-handoff-id";
    const MAX_ELEMENTS = 150;
    const MAX_LABEL = 80;
    const MAX_TEXT = 12000;

    const CANDIDATES = [
        "a[href]", "button", "input:not([type=hidden])", "textarea", "select", "summary",
        "[role=button]", "[role=link]", "[role=checkbox]", "[role=radio]", "[role=switch]",
        "[role=tab]", "[role=menuitem]", "[role=menuitemcheckbox]", "[role=menuitemradio]",
        "[role=option]", "[role=combobox]", "[role=textbox]", "[role=searchbox]",
        "[role=slider]", "[role=spinbutton]", "[role=treeitem]", "[role=gridcell][tabindex]",
        "[contenteditable=''], [contenteditable=true]", "[onclick]", "[tabindex]:not([tabindex='-1'])",
    ].join(",");

    // Fields whose value must never leave the page.
    const SECRET_NAME = /pass(word)?|pwd|card|cc-?(num|number|csc|exp)|cvv|cvc|security.?code|\bpin\b|otp|one.?time/i;

    let nextId = 1;

    function clean(text, max = MAX_LABEL) {
        const t = (text || "").replace(/\s+/g, " ").trim();
        return t.length > max ? t.slice(0, max - 1) + "…" : t;
    }

    function* walk(root, depth = 0) {
        // Elements in the page plus open shadow roots (web components).
        for (const el of root.querySelectorAll(CANDIDATES)) yield el;
        if (depth > 3) return;
        for (const host of root.querySelectorAll("*")) {
            if (host.shadowRoot) yield* walk(host.shadowRoot, depth + 1);
        }
    }

    function isShown(el) {
        const rect = el.getBoundingClientRect();
        if (rect.width < 2 || rect.height < 2) return false;
        const style = window.getComputedStyle(el);
        if (style.display === "none" || style.visibility === "hidden" || style.visibility === "collapse") return false;
        if (parseFloat(style.opacity) < 0.05) return false;
        if (el.closest("[aria-hidden=true], [inert]")) return false;
        return true;
    }

    function inViewport(rect) {
        return rect.bottom > 0 && rect.right > 0 && rect.top < window.innerHeight && rect.left < window.innerWidth;
    }

    // Is the element actually on top at its centre, or covered by something
    // (a cookie banner, a modal)? Elements inside shadow roots are trusted.
    function isOnTop(el, rect) {
        const x = Math.min(Math.max(rect.left + rect.width / 2, 0), window.innerWidth - 1);
        const y = Math.min(Math.max(rect.top + rect.height / 2, 0), window.innerHeight - 1);
        const hit = document.elementFromPoint(x, y);
        if (!hit) return false;
        if (hit === el || el.contains(hit) || hit.contains(el)) return true;
        if (el.getRootNode() !== document) return true;
        // Labels often sit on top of their own (styled) checkbox or input.
        const label = hit.closest("label");
        return !!(label && (label.control === el || label.contains(el)));
    }

    function textOfIds(ids) {
        return ids.split(/\s+/).map((id) => document.getElementById(id)?.innerText || "").join(" ");
    }

    function roleOf(el) {
        const explicit = el.getAttribute("role");
        if (explicit) return explicit.replace("textbox", "text box").replace("searchbox", "search box").replace("combobox", "dropdown");
        const tag = el.tagName.toLowerCase();
        if (tag === "a") return "link";
        if (tag === "button" || tag === "summary") return "button";
        if (tag === "select") return "dropdown";
        if (tag === "textarea") return "text box";
        if (el.isContentEditable) return "text box";
        if (tag === "input") {
            const type = (el.getAttribute("type") || "text").toLowerCase();
            if (["submit", "button", "reset", "image"].includes(type)) return "button";
            if (type === "checkbox" || type === "radio") return type;
            if (type === "search") return "search box";
            if (["date", "time", "datetime-local", "month", "week"].includes(type)) return `${type} box`;
            if (type === "range") return "slider";
            return "text box";
        }
        return "clickable";
    }

    function labelOf(el) {
        const aria = el.getAttribute("aria-label");
        if (aria) return clean(aria);
        const labelledBy = el.getAttribute("aria-labelledby");
        if (labelledBy) {
            const t = clean(textOfIds(labelledBy));
            if (t) return t;
        }
        if (el.labels && el.labels.length) {
            const t = clean([...el.labels].map((l) => l.innerText).join(" "));
            if (t) return t;
        }
        const tag = el.tagName.toLowerCase();
        if (tag === "input" && ["submit", "button", "reset"].includes((el.type || "").toLowerCase()) && el.value) {
            return clean(el.value);
        }
        for (const attr of ["placeholder", "title", "alt", "name"]) {
            const v = el.getAttribute(attr);
            if (v) return clean(v);
        }
        const img = el.querySelector && el.querySelector("img[alt]");
        const text = clean(el.innerText || el.textContent || "");
        if (text) return text;
        if (img) return clean(img.getAttribute("alt"));
        return "";
    }

    function isSecret(el) {
        const type = (el.getAttribute("type") || "").toLowerCase();
        if (type === "password") return true;
        const hints = [el.name, el.id, el.getAttribute("autocomplete"), el.getAttribute("aria-label"), el.getAttribute("placeholder")].join(" ");
        return SECRET_NAME.test(hints);
    }

    function valueOf(el) {
        const tag = el.tagName.toLowerCase();
        if (tag === "select") return clean(el.selectedOptions?.[0]?.text || "");
        if (tag === "input" || tag === "textarea") {
            const type = (el.getAttribute("type") || "text").toLowerCase();
            if (["checkbox", "radio", "submit", "button", "reset", "image"].includes(type)) return "";
            if (!el.value) return "";
            return isSecret(el) ? "(filled, hidden)" : clean(el.value, 60);
        }
        if (el.isContentEditable) return clean(el.innerText, 60);
        return "";
    }

    function stateOf(el) {
        const state = [];
        if (el.disabled || el.getAttribute("aria-disabled") === "true") state.push("disabled");
        if (el.checked || el.getAttribute("aria-checked") === "true") state.push("checked");
        if (el.getAttribute("aria-selected") === "true") state.push("selected");
        const expanded = el.getAttribute("aria-expanded");
        if (expanded === "true") state.push("open");
        if (expanded === "false") state.push("closed");
        if (el.required || el.getAttribute("aria-required") === "true") state.push("required");
        if (document.activeElement === el) state.push("focused");
        return state;
    }

    function idFor(el) {
        let id = el.getAttribute(ID_ATTR);
        if (!id) {
            id = String(nextId++);
            el.setAttribute(ID_ATTR, id);
        }
        return Number(id);
    }

    // Skip a span inside a link that says the same thing as the link.
    function insideChosen(el, chosen) {
        let node = el.parentElement;
        while (node) {
            if (chosen.has(node)) return true;
            node = node.parentElement;
        }
        return false;
    }

    function map() {
        const chosen = new Set();
        const elements = [];
        let below = 0;
        let above = 0;
        for (const el of walk(document)) {
            if (chosen.has(el) || !isShown(el)) continue;
            const rect = el.getBoundingClientRect();
            if (!inViewport(rect)) {
                if (rect.top >= window.innerHeight) below++;
                else if (rect.bottom <= 0) above++;
                continue;
            }
            const tag = el.tagName.toLowerCase();
            const isField = ["input", "textarea", "select"].includes(tag);
            if (!isField && insideChosen(el, chosen)) continue;
            if (!isOnTop(el, rect)) continue;
            const label = labelOf(el);
            const role = roleOf(el);
            if (!label && role === "clickable") continue;
            chosen.add(el);
            elements.push({
                id: idFor(el),
                role,
                label,
                value: valueOf(el),
                state: stateOf(el),
                secret: isSecret(el) || undefined,
                href: tag === "a" ? clean(el.getAttribute("href"), 100) : undefined,
                box: [Math.round(rect.left), Math.round(rect.top), Math.round(rect.width), Math.round(rect.height)],
            });
            if (elements.length >= MAX_ELEMENTS) break;
        }
        const scroller = document.scrollingElement || document.documentElement;
        return {
            url: location.href,
            title: document.title,
            elements,
            hidden_above: above,
            hidden_below: below,
            scroll: {
                y: Math.round(scroller.scrollTop),
                max: Math.max(0, Math.round(scroller.scrollHeight - window.innerHeight)),
            },
            viewport: [window.innerWidth, window.innerHeight],
            dialog_open: !!document.querySelector("dialog[open], [role=dialog]:not([aria-hidden=true]), [aria-modal=true]"),
        };
    }

    // The readable text of the page: the main content if the page marks it,
    // otherwise the whole body. innerText already skips hidden elements.
    function readText(maxChars = MAX_TEXT) {
        const main = document.querySelector("main, [role=main], article") || document.body;
        const lines = (main.innerText || "")
            .split("\n")
            .map((l) => l.replace(/\s+/g, " ").trim())
            .filter(Boolean);
        let text = lines.join("\n");
        if (text.length > maxChars) text = text.slice(0, maxChars) + "\n…(page continues)";
        return { url: location.href, title: document.title, text };
    }

    // ── Search results ──────────────────────────────────────────────────
    // Works on Google, Bing and DuckDuckGo alike: a result is a link that
    // holds a heading, or sits inside one. Ads and the search site's own
    // links are left out, and redirect links are turned into the real address.

    const AD_MARK = /(^|[\s_-])(ads?|sponsored|b_ad|commercial)([\s_-]|$)/i;

    const SEARCH_SITE = /(^|\.)(google|bing|duckduckgo)\.[a-z.]+$/i;

    function isAd(el) {
        for (let node = el; node && node !== document.body; node = node.parentElement) {
            if (node.hasAttribute("data-text-ad") || node.hasAttribute("data-ad")) return true;
            if (node.id === "tads" || node.id === "bottomads") return true;   // Google's ad blocks
            const marks = [node.className && String(node.className), node.getAttribute("aria-label"), node.id].join(" ");
            if (AD_MARK.test(marks)) return true;
        }
        return false;
    }

    function fromBase64(text) {
        try {
            const b64 = text.replace(/-/g, "+").replace(/_/g, "/");
            return atob(b64 + "=".repeat((4 - (b64.length % 4)) % 4));
        } catch (e) {
            return "";
        }
    }

    // Search sites send clicks through their own address first.
    function realAddress(href) {
        let url;
        try {
            url = new URL(href, location.href);
        } catch (e) {
            return "";
        }
        for (const key of ["q", "url", "uddg", "u"]) {
            let value = url.searchParams.get(key);
            if (!value) continue;
            if (key === "u" && value.startsWith("a1")) value = fromBase64(value.slice(2));
            if (/^https?:\/\//.test(value)) return value;
        }
        return url.protocol.startsWith("http") ? url.href : "";
    }

    function sameSite(a, b) {
        const root = (host) => host.replace(/^www\./, "").split(".").slice(-2).join(".");
        try {
            return root(new URL(a).hostname) === root(new URL(b).hostname);
        } catch (e) {
            return false;
        }
    }

    function snippetOf(link) {
        // The nearest block around the link that has more text than the title.
        const title = (link.innerText || link.textContent || "").trim();
        for (let node = link.parentElement, i = 0; node && i < 5; node = node.parentElement, i++) {
            const text = clean(node.innerText || node.textContent || "", 400);
            if (text.length > title.length + 40) return clean(text.replace(title, ""), 200);
        }
        return "";
    }

    function searchResults(max = 8) {
        const seen = new Set();
        const results = [];
        for (const link of document.querySelectorAll("a[href]")) {
            const heading = link.querySelector("h1, h2, h3") || link.closest("h2, h3");
            if (!heading || isAd(link)) continue;
            const rect = link.getBoundingClientRect();
            if (rect.width < 2 || rect.height < 2) continue;
            const url = realAddress(link.getAttribute("href"));
            if (!url || sameSite(url, location.href) || SEARCH_SITE.test(new URL(url).hostname) || seen.has(url)) continue;
            const title = clean(heading.innerText || heading.textContent || link.textContent, 120);
            if (!title) continue;
            seen.add(url);
            results.push({ title, url, snippet: snippetOf(link) });
            if (results.length >= max) break;
        }
        return { url: location.href, results };
    }

    function element(id) {
        const selector = `[${ID_ATTR}="${Number(id)}"]`;
        const found = document.querySelector(selector);
        if (found) return found;
        // Look inside open shadow roots too.
        for (const host of document.querySelectorAll("*")) {
            const inner = host.shadowRoot && host.shadowRoot.querySelector(selector);
            if (inner) return inner;
        }
        return null;
    }

    window.handoffPage = { map, readText, searchResults, element, ID_ATTR };
})();
