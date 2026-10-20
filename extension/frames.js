// frames.js
// Pages often put forms and buttons inside frames (card payments, embedded
// booking or sign-up forms). Each frame builds its own page map; these
// functions join them into one numbered list for the backend, and find which
// frame an element number belongs to.
//
// Numbers in the top page stay as they are. Frame k (1, 2, ...) numbers its
// elements k * FRAME_STEP + its own number, so "click 200004" means element 4
// of frame 2.
//
// Plain functions only: loaded by background.js and tested with Node.

const FRAME_STEP = 100000;

function frameElementId(frameIndex, localId) {
    return frameIndex === 0 ? Number(localId) : frameIndex * FRAME_STEP + Number(localId);
}

function splitElementId(id) {
    const n = Number(id);
    return { frameIndex: Math.floor(n / FRAME_STEP), localId: n % FRAME_STEP };
}

function hostOf(url) {
    try {
        return new URL(url).hostname;
    } catch (e) {
        return "";
    }
}

function sameFrameAddress(a, b) {
    try {
        const x = new URL(a), y = new URL(b);
        return x.origin === y.origin && x.pathname === y.pathname;
    } catch (e) {
        return a === b;
    }
}

// results: [{ frameId, result }] from chrome.scripting.executeScript with
// allFrames; result is a page map, or null where the frame couldn't be read.
// frameIndexes: Map of frameId -> frame number, kept per tab so an element's
// number doesn't change between page views.
function mergeFrameMaps(results, frameIndexes) {
    const top = results.find((r) => r.frameId === 0);
    if (!top || !top.result) return null;
    const merged = { ...top.result, elements: [...(top.result.elements || [])] };
    const read = [];
    const payment = [];

    for (const r of results) {
        if (r.frameId === 0 || !r.result) continue;
        if (!frameIndexes.has(r.frameId)) frameIndexes.set(r.frameId, frameIndexes.size + 1);
        const index = frameIndexes.get(r.frameId);
        const host = hostOf(r.result.url);
        read.push(r.result.url);
        if (r.result.payment_frame) payment.push(host);
        for (const el of r.result.elements || []) {
            merged.elements.push({ ...el, id: frameElementId(index, el.id), frame: host });
        }
    }

    // Visible frames the top page shows that no page map came back from.
    merged.unreadable_frames = (top.result.frames || [])
        .filter((f) => !read.some((url) => sameFrameAddress(url, f.src)))
        .map((f) => hostOf(f.src) || "an embedded part of the page");
    merged.payment_frames = [...new Set(payment)];
    delete merged.frames;
    return merged;
}

function frameIdForIndex(frameIndexes, frameIndex) {
    if (frameIndex === 0) return 0;
    for (const [frameId, index] of frameIndexes) {
        if (index === frameIndex) return frameId;
    }
    return null;
}

if (typeof module !== "undefined") {
    module.exports = { FRAME_STEP, frameElementId, splitElementId, mergeFrameMaps, frameIdForIndex };
}
