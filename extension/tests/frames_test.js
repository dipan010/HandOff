// Run by backend/tests/test_frames.py with Node.
const assert = require("assert");
const f = require("../frames.js");

const top = { url: "https://shop.example.com/pay", title: "Pay", elements: [{ id: 1, role: "button", label: "Back" }],
              frames: [{ src: "https://js.stripe.com/v3/elements" }, { src: "https://ads.example.net/slot" }] };
const card = { url: "https://js.stripe.com/v3/elements", elements: [{ id: 4, role: "text box", label: "Card number", secret: true }],
               payment_frame: true };
const indexes = new Map();
const merged = f.mergeFrameMaps([{ frameId: 0, result: top }, { frameId: 17, result: card }, { frameId: 23, result: null }], indexes);

assert.deepStrictEqual(merged.elements.map((e) => e.id), [1, 100004]);
assert.strictEqual(merged.elements[1].frame, "js.stripe.com");
assert.deepStrictEqual(merged.payment_frames, ["js.stripe.com"]);
assert.deepStrictEqual(merged.unreadable_frames, ["ads.example.net"]);
assert.strictEqual(merged.frames, undefined);

// The same frame keeps its number on the next page view.
f.mergeFrameMaps([{ frameId: 0, result: top }, { frameId: 31, result: card }, { frameId: 17, result: card }], indexes);
assert.strictEqual(indexes.get(17), 1);
assert.strictEqual(indexes.get(31), 2);

assert.deepStrictEqual(f.splitElementId(100004), { frameIndex: 1, localId: 4 });
assert.deepStrictEqual(f.splitElementId(12), { frameIndex: 0, localId: 12 });
assert.strictEqual(f.frameIdForIndex(indexes, 1), 17);
assert.strictEqual(f.frameIdForIndex(indexes, 0), 0);
assert.strictEqual(f.frameIdForIndex(indexes, 9), null);
assert.strictEqual(f.mergeFrameMaps([{ frameId: 0, result: null }], new Map()), null);
console.log("frames ok");
