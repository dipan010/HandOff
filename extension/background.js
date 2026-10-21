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

importScripts("frames.js", "live_view.js");

let ws = null;
let currentSessionId = null;
let workTabId = null;

// Tabs where content_script.js is already running, to avoid re-injection errors
const injectedTabs = new Set();

// Per tab: frameId -> frame number, so element numbers stay put (see frames.js).
const frameIndexesByTab = new Map();
// The frame HandOff last clicked or typed in, so key presses go to it.
let lastFrameId = 0;

function frameIndexes(tabId) {
    if (!frameIndexesByTab.has(tabId)) frameIndexesByTab.set(tabId, new Map());
    return frameIndexesByTab.get(tabId);
}

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
        // The live view starts when the backend says a task is running.
        console.log("HandOff: connected to backend for session", sessionId, "work tab", workTabId);
    };

    ws.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.type === "execute_action") {
            executeInWorkTab(message);
        } else if (message.type === "start_stream") {
            liveView.start();
        } else if (message.type === "stop_stream") {
            liveView.stop();
        } else if (message.type === "UDAA_STATUS" || message.type === "status") {
            const payload = message.payload || message;
            sendToWorkTab({ type: "UDAA_STATUS", payload });
        } else if (message.type === "action_preview") {
            sendToWorkTab({ type: "ACTION_PREVIEW", payload: message }, captureAndSendFrame);
        }
    };

    ws.onclose = () => {
        console.log("HandOff: disconnected");
        liveView.stop();
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
    chrome.scripting.executeScript({ target: { tabId, allFrames: true }, files: PAGE_SCRIPTS }, () => {
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
            chrome.tabs.sendMessage(tab.id, message, { frameId: 0 }, () => {
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

// Wait until the tab has finished loading (or give up after `timeoutMs`).
function waitForLoad(tabId, timeoutMs = 10000) {
    return new Promise((resolve) => {
        let done = false;
        const finish = () => {
            if (done) return;
            done = true;
            chrome.tabs.onUpdated.removeListener(listener);
            clearTimeout(timer);
            chrome.tabs.get(tabId, (tab) => resolve(chrome.runtime.lastError ? null : tab));
        };
        const listener = (id, info) => { if (id === tabId && info.status === "complete") finish(); };
        const timer = setTimeout(finish, timeoutMs);
        chrome.tabs.onUpdated.addListener(listener);
    });
}

// Going to another page unloads the page script before it can reply, so the
// background does it with the tabs API and replies once the page has loaded.
async function navigateWorkTab(tab, command) {
    try {
        if (command.action === "go_back") {
            await chrome.tabs.goBack(tab.id);
        } else {
            const url = command.url;
            if (!url || url === "about:blank") {
                reportResult({ action: command.action, success: true, url: tab.url });
                return;
            }
            await chrome.tabs.update(tab.id, { url });
        }
        const loaded = await waitForLoad(tab.id);
        captureAndSendFrame();
        reportResult({ action: command.action, success: true, url: loaded ? loaded.url : command.url });
    } catch (e) {
        reportResult({ action: command.action, success: false, detail: String(e && e.message || e) });
    }
}

function executeInWorkTab(command) {
    getWorkTab((tab) => {
        if (!tab) {
            reportResult({ action: command.action, success: false, detail: "HandOff's tab was closed." });
            return;
        }
        if (command.action === "navigate" || command.action === "open_web_browser" || command.action === "go_back") {
            navigateWorkTab(tab, command);
            return;
        }
        if (command.action === "screenshot") {
            fullScreenshot(tab);
            return;
        }
        ensureScripts(tab.id, () => {
            if (command.action === "page_map") {
                pageMapAllFrames(tab);
                return;
            }
            // Element numbers from a frame go to that frame; key presses and
            // suggestion picks go to the frame last used; the rest to the top page.
            let frameId = 0;
            let args = command;
            if (command.element_id != null) {
                const { frameIndex, localId } = splitElementId(command.element_id);
                if (frameIndex > 0) {
                    frameId = frameIdForIndex(frameIndexes(tab.id), frameIndex);
                    if (frameId == null) {
                        reportResult({ action: command.action, success: false, stale: true,
                                       detail: `Element ${command.element_id} is no longer on the page.` });
                        return;
                    }
                    args = { ...command, element_id: localId };
                }
                lastFrameId = frameId;
            } else if (command.action === "press_key" || command.action === "choose_option") {
                // Keys and picking a suggestion follow the box HandOff just used.
                frameId = lastFrameId;
            }
            chrome.tabs.sendMessage(tab.id, {
                type: "EXECUTE_ACTION",
                payload: { action: command.action, args }
            }, { frameId }, (response) => {
                if (chrome.runtime.lastError) {
                    console.warn("HandOff: could not reach the page:", chrome.runtime.lastError.message);
                }
                captureAndSendFrame();
                reportResult(response || {
                    action: command.action,
                    success: false,
                    no_answer: true,   // e.g. a click that opened a new page before the reply was sent
                    detail: "The page did not answer (it may still be loading).",
                    url: tab.url,
                });
            });
        });
    });
}

// One page map for the whole tab, frames included (see frames.js).
function pageMapAllFrames(tab) {
    chrome.scripting.executeScript({
        target: { tabId: tab.id, allFrames: true },
        func: () => (window.handoffPage ? window.handoffPage.map() : null),
    }, (results) => {
        if (chrome.runtime.lastError || !results) {
            reportResult({ action: "page_map", success: false,
                           detail: "Could not read the page: " + (chrome.runtime.lastError ? chrome.runtime.lastError.message : "no answer") });
            return;
        }
        const page = mergeFrameMaps(results, frameIndexes(tab.id));
        reportResult(page ? { action: "page_map", success: true, page }
                          : { action: "page_map", success: false, detail: "The page reader isn't loaded yet." });
    });
}

// ── Screen frames ───────────────────────────────────────────────────────────

const tabCapturer = makeTabCapturer(({ windowId, format }) => new Promise((resolve, reject) => {
    const options = format === "jpeg" ? { format, quality: 70 } : { format };
    chrome.tabs.captureVisibleTab(windowId, options, (dataUrl) => {
        if (chrome.runtime.lastError || !dataUrl) reject(new Error(chrome.runtime.lastError?.message || "no picture"));
        else resolve(dataUrl);
    });
}));

const workTab = () => new Promise((resolve) => getWorkTab(resolve));

const liveView = new LiveView({
    // Only the visible tab of a window can be captured. If the work tab is
    // behind another tab, skip this frame rather than send the wrong page.
    capture: async () => {
        const tab = await workTab();
        if (!tab || !tab.active) return null;
        return { dataUrl: await tabCapturer.take({ windowId: tab.windowId, format: "jpeg" }), url: tab.url || "unknown" };
    },
    shrink: shrinkToJpeg,
    send: ({ image, url }) => {
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "screen_frame", image, url }));
    },
});

// A fresh live frame right after something happened, if the live view is on.
function captureAndSendFrame() {
    liveView.frame();
}

// A full-size picture, for when HandOff itself needs to look.
async function fullScreenshot(tab) {
    if (!tab.active) {
        reportResult({ action: "screenshot", success: false, url: tab.url,
                       detail: "HandOff's tab isn't in front, so it can't be seen." });
        return;
    }
    try {
        const dataUrl = await tabCapturer.take({ windowId: tab.windowId, format: "png" });
        reportResult({ action: "screenshot", success: true, image: dataUrl.split(",")[1], url: tab.url });
    } catch (e) {
        reportResult({ action: "screenshot", success: false, url: tab.url, detail: String(e && e.message || e) });
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
    if (request.type === "USER_INPUT") {
        // Only the user's own use of HandOff's tab matters, not other tabs.
        const tabId = sender && sender.tab ? sender.tab.id : null;
        if (tabId != null && tabId === workTabId && ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "user_input", kind: request.kind }));
        }
        return;
    }
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

// Reloads and new addresses wipe the page scripts' state. A reload has no
// changeInfo.url (same address), so it isn't required.
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
    if (changeInfo.status === 'loading') {
        injectedTabs.delete(tabId);
        frameIndexesByTab.delete(tabId);
    }
});

chrome.tabs.onRemoved.addListener((tabId) => {
    injectedTabs.delete(tabId);
    frameIndexesByTab.delete(tabId);
    if (tabId === workTabId) {
        console.log("HandOff: work tab closed");
        workTabId = null;
    }
});
