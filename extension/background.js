// background.js
// Service worker: keeps the WebSocket to the HandOff backend and decides
// which tab HandOff works in.
//
// HandOff works in ONE tab per session (the "work tab"):
//   - the tab whose address carries ?udaa_session_id=..., found automatically;
//   - any tab the user picks by clicking the HandOff toolbar icon;
//   - a new tab opened from the work tab (e.g. a link with target=_blank).
// Actions and screenshots always go to the work tab, never to whatever tab
// happens to be in front (the dashboard is a tab too).

let ws = null;
let streamingInterval = null;
let currentSessionId = null;
let workTabId = null;

// Tabs where content_script.js is already running, to avoid re-injection errors
const injectedTabs = new Set();

const PAGE_SCRIPTS = ["overlay.js", "page_map.js", "content_script.js"];

chrome.runtime.onInstalled.addListener(() => {
    console.log("HandOff extension installed.");
});

function connectWebSocket(sessionId, tabId) {
    if (tabId != null) workTabId = tabId;
    if (ws && currentSessionId === sessionId && ws.readyState <= WebSocket.OPEN) return;
    if (ws) ws.close();
    currentSessionId = sessionId;

    ws = new WebSocket(`ws://localhost:8080/ws/live_ext/${sessionId}`);

    ws.onopen = () => {
        console.log("HandOff: connected to backend for session", sessionId, "work tab", workTabId);
        startStreamingFrames();
    };

    ws.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.type === "execute_action") {
            executeInWorkTab(message);
        } else if (message.type === "stop_stream") {
            stopStreamingFrames();
        } else if (message.type === "UDAA_STATUS" || message.type === "status") {
            const payload = message.payload || message;
            sendToWorkTab({ type: "UDAA_STATUS", payload });
        } else if (message.type === "action_preview") {
            sendToWorkTab({ type: "ACTION_PREVIEW", payload: message }, captureAndSendFrame);
        }
    };

    ws.onclose = () => {
        console.log("HandOff: disconnected");
        stopStreamingFrames();
    };
}

// ── Work tab ────────────────────────────────────────────────────────────────

function getWorkTab(callback) {
    if (workTabId == null) {
        // No work tab known yet: fall back to the active tab, once.
        chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
            const tab = tabs && tabs[0];
            if (tab) workTabId = tab.id;
            callback(tab || null);
        });
        return;
    }
    chrome.tabs.get(workTabId, (tab) => {
        if (chrome.runtime.lastError || !tab) {
            workTabId = null;
            callback(null);
            return;
        }
        callback(tab);
    });
}

function ensureScripts(tabId, callback) {
    if (injectedTabs.has(tabId)) {
        callback(true);
        return;
    }
    chrome.scripting.executeScript({ target: { tabId }, files: PAGE_SCRIPTS }, () => {
        if (chrome.runtime.lastError) {
            console.warn("HandOff: could not add scripts to tab:", chrome.runtime.lastError.message);
            callback(false);
            return;
        }
        injectedTabs.add(tabId);
        callback(true);
    });
}

function sendToWorkTab(message, after) {
    getWorkTab((tab) => {
        if (!tab) return;
        ensureScripts(tab.id, () => {
            chrome.tabs.sendMessage(tab.id, message, () => {
                void chrome.runtime.lastError; // tab may be loading; ignore
                if (after) after();
            });
        });
    });
}

function reportResult(result) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "action_result", result }));
    }
}

function executeInWorkTab(command) {
    getWorkTab((tab) => {
        if (!tab) {
            reportResult({ action: command.action, success: false, detail: "HandOff's tab was closed." });
            return;
        }
        ensureScripts(tab.id, () => {
            chrome.tabs.sendMessage(tab.id, {
                type: "EXECUTE_ACTION",
                payload: { action: command.action, args: command }
            }, (response) => {
                if (chrome.runtime.lastError) {
                    console.warn("HandOff: could not reach the page:", chrome.runtime.lastError.message);
                }
                captureAndSendFrame();
                reportResult(response || {
                    action: command.action,
                    success: false,
                    detail: "The page did not answer (it may still be loading).",
                    url: tab.url,
                });
            });
        });
    });
}

// ── Screen frames ───────────────────────────────────────────────────────────

function captureAndSendFrame() {
    getWorkTab((tab) => {
        // Only the visible tab of a window can be captured. If the work tab is
        // behind another tab, skip this frame rather than send the wrong page.
        if (!tab || !tab.active) return;
        chrome.tabs.captureVisibleTab(tab.windowId, { format: "png" }, (dataUrl) => {
            if (chrome.runtime.lastError || !dataUrl) return;
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({
                    type: "screen_frame",
                    image: dataUrl.split(',')[1],
                    url: tab.url || "unknown",
                }));
            }
        });
    });
}

function startStreamingFrames() {
    if (streamingInterval) return;
    streamingInterval = setInterval(captureAndSendFrame, 1200);
}

function stopStreamingFrames() {
    if (streamingInterval) {
        clearInterval(streamingInterval);
        streamingInterval = null;
    }
}

// ── Finding the session ─────────────────────────────────────────────────────

function sessionIdFromUrl(url) {
    try {
        return new URL(url).searchParams.get('udaa_session_id');
    } catch (e) {
        return null; // chrome:// and other special pages
    }
}

chrome.runtime.onMessage.addListener((request, sender) => {
    if (request.type === "CONNECT_WS") {
        const tabId = sender && sender.tab ? sender.tab.id : null;
        console.log("HandOff: page asked to connect session", request.sessionId, "from tab", tabId);
        connectWebSocket(request.sessionId, tabId);
    }
});

// Failsafe: look through all tabs for the session id, in case the page
// script can't run there (restricted pages).
setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) return;
    chrome.tabs.query({}, (tabs) => {
        for (const tab of tabs || []) {
            const sessionId = tab.url && sessionIdFromUrl(tab.url);
            if (sessionId && sessionId !== currentSessionId) {
                console.log("HandOff: found session id in tab", tab.id);
                connectWebSocket(sessionId, tab.id);
                return;
            }
        }
    });
}, 1000);

// Toolbar icon: "use this tab". If no session is connected yet, ask for one.
chrome.action.onClicked.addListener((tab) => {
    if (ws && ws.readyState === WebSocket.OPEN) {
        workTabId = tab.id;
        console.log("HandOff: user picked tab", tab.id);
        sendToWorkTab({
            type: "UDAA_STATUS",
            payload: { status: "active", message: "HandOff will work in this tab." }
        }, captureAndSendFrame);
        return;
    }
    chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (current) => prompt("Enter the HandOff session ID to connect this tab:", current || ""),
        args: [currentSessionId]
    }, (results) => {
        if (chrome.runtime.lastError) {
            console.error(chrome.runtime.lastError.message);
            return;
        }
        if (results && results[0] && results[0].result) {
            connectWebSocket(results[0].result, tab.id);
        }
    });
});

// ── Tab lifecycle ───────────────────────────────────────────────────────────

// Follow new tabs opened from the work tab (links that open in a new tab).
chrome.tabs.onCreated.addListener((tab) => {
    if (workTabId != null && tab.openerTabId === workTabId) {
        console.log("HandOff: following new tab", tab.id, "opened from work tab");
        workTabId = tab.id;
    }
});

// Reloads and new addresses wipe the page scripts' state.
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
    if (changeInfo.status === 'loading' && changeInfo.url) {
        injectedTabs.delete(tabId);
    }
});

chrome.tabs.onRemoved.addListener((tabId) => {
    injectedTabs.delete(tabId);
    if (tabId === workTabId) {
        console.log("HandOff: work tab closed");
        workTabId = null;
    }
});
