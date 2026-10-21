// Run by backend/tests/test_live_view.py with Node.
const assert = require("assert");
const lv = require("../live_view.js");

(async () => {
    // Frames are shrunk to a small width, keeping their shape.
    assert.deepStrictEqual(lv.liveFrameSize(1920, 1080), { width: 960, height: 540 });
    assert.deepStrictEqual(lv.liveFrameSize(800, 600), { width: 800, height: 600 });

    // Frames are sent only between start() and stop().
    const sent = [];
    const ticks = [];
    const timers = { setInterval: (fn) => { ticks.push(fn); return 1; }, clearInterval: () => { ticks.length = 0; } };
    const view = new lv.LiveView({
        capture: async () => ({ dataUrl: "data:image/jpeg;base64,AAAA", url: "https://example.com/" }),
        shrink: async (dataUrl) => "small:" + dataUrl.split(",")[1],
        send: (frame) => sent.push(frame),
        timers,
    });
    await view.frame();
    assert.strictEqual(sent.length, 0, "no frames before a task starts");
    view.start();
    await new Promise((r) => setTimeout(r, 0));
    assert.strictEqual(sent.length, 1, "a frame at once when a task starts");
    assert.deepStrictEqual(sent[0], { image: "small:AAAA", url: "https://example.com/" });
    await ticks[0]();
    assert.strictEqual(sent.length, 2);
    view.stop();
    assert.strictEqual(ticks.length, 0);
    await view.frame();
    assert.strictEqual(sent.length, 2, "no frames after the task ends");

    // Chrome allows two tab captures a second: captures are spaced out.
    let clock = 0;
    const times = [];
    const capturer = lv.makeTabCapturer(async () => { times.push(clock); return "shot"; },
        () => clock, async (ms) => { clock += ms; });
    await Promise.all([capturer.take(), capturer.take(), capturer.take()]);
    assert.deepStrictEqual(times, [0, lv.CAPTURE_GAP_MS, 2 * lv.CAPTURE_GAP_MS]);

    console.log("live view ok");
})().catch((e) => { console.error(e); process.exit(1); });
