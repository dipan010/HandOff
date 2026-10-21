// live_view.js
// The dashboard's live view of HandOff's tab: a small JPEG a couple of times a
// second, and only while a task runs. Full-size screenshots are taken only
// when HandOff itself needs to look (the "screenshot" action in background.js).

const LIVE_FRAME_MS = 600;
const LIVE_FRAME_WIDTH = 960;
const LIVE_FRAME_QUALITY = 0.6;
const CAPTURE_GAP_MS = 520;   // Chrome allows two tab captures a second

function liveFrameSize(width, height, maxWidth = LIVE_FRAME_WIDTH) {
    if (!width || !height || width <= maxWidth) return { width, height };
    return { width: maxWidth, height: Math.round(height * maxWidth / width) };
}

// Runs tab captures one at a time, spaced out so Chrome doesn't refuse them.
function makeTabCapturer(capture, now = Date.now, wait = (ms) => new Promise((r) => setTimeout(r, ms))) {
    let last = -Infinity;
    let queue = Promise.resolve();
    return {
        take(options) {
            const run = queue.then(async () => {
                const gap = last + CAPTURE_GAP_MS - now();
                if (gap > 0) await wait(gap);
                last = now();
                return capture(options);
            });
            queue = run.catch(() => {});
            return run;
        },
    };
}

class LiveView {
    // capture() -> {dataUrl, url} or null; shrink(dataUrl) -> base64 JPEG; send({image, url}).
    constructor({ capture, shrink, send, every = LIVE_FRAME_MS, timers = globalThis }) {
        Object.assign(this, { capture, shrink, send, every, timers });
        this.timer = null;
        this.busy = false;
    }

    get on() {
        return this.timer !== null;
    }

    start() {
        if (this.on) return;
        this.timer = this.timers.setInterval(() => this.frame(), this.every);
        this.frame();
    }

    stop() {
        if (!this.on) return;
        this.timers.clearInterval(this.timer);
        this.timer = null;
    }

    async frame() {
        if (!this.on || this.busy) return;
        this.busy = true;
        try {
            const shot = await this.capture();
            if (!shot || !this.on) return;
            const image = await this.shrink(shot.dataUrl);
            if (image && this.on) this.send({ image, url: shot.url });
        } catch (e) {
            // A missed frame is fine; the next one follows shortly.
        } finally {
            this.busy = false;
        }
    }
}

// In the extension: shrink a captured frame with an offscreen canvas.
async function shrinkToJpeg(dataUrl) {
    const bitmap = await createImageBitmap(await (await fetch(dataUrl)).blob());
    const { width, height } = liveFrameSize(bitmap.width, bitmap.height);
    const canvas = new OffscreenCanvas(width, height);
    canvas.getContext("2d").drawImage(bitmap, 0, 0, width, height);
    bitmap.close();
    const blob = await canvas.convertToBlob({ type: "image/jpeg", quality: LIVE_FRAME_QUALITY });
    const bytes = new Uint8Array(await blob.arrayBuffer());
    let text = "";
    for (let i = 0; i < bytes.length; i += 0x8000) text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    return btoa(text);
}

if (typeof module !== "undefined") {
    module.exports = { LIVE_FRAME_MS, CAPTURE_GAP_MS, liveFrameSize, makeTabCapturer, LiveView };
}
