import '@testing-library/jest-dom/vitest';
import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

afterEach(() => {
    cleanup();
    vi.clearAllMocks();
});

// jsdom doesn't ship with speechSynthesis — fake it for tests that need it.
class FakeSpeechSynthesisUtterance {
    text: string;
    rate = 1;
    pitch = 1;
    volume = 1;
    onend: (() => void) | null = null;
    onerror: (() => void) | null = null;
    constructor(text: string) {
        this.text = text;
    }
}

class FakeSpeechSynthesis {
    speaking = false;
    private utterances: FakeSpeechSynthesisUtterance[] = [];
    speak(u: FakeSpeechSynthesisUtterance) {
        this.utterances.push(u);
        this.speaking = true;
        // Simulate async completion
        queueMicrotask(() => {
            this.speaking = false;
            u.onend?.();
        });
    }
    cancel() {
        this.utterances = [];
        this.speaking = false;
    }
    getUtterances() {
        return this.utterances;
    }
}

if (typeof window !== 'undefined') {
    // @ts-expect-error
    window.SpeechSynthesisUtterance = FakeSpeechSynthesisUtterance;
    // @ts-expect-error
    window.speechSynthesis = new FakeSpeechSynthesis();
}

// AudioContext stub — useWebSocket creates one for audio playback
class FakeAudioBuffer {
    constructor(public length: number, public sampleRate: number) {}
    copyToChannel() {}
}
class FakeAudioBufferSource {
    buffer: FakeAudioBuffer | null = null;
    onended: (() => void) | null = null;
    connect() {}
    start() {
        queueMicrotask(() => this.onended?.());
    }
}
class FakeAudioContext {
    state: 'running' | 'suspended' | 'closed' = 'running';
    destination = {};
    sampleRate: number;
    constructor(opts?: { sampleRate?: number }) {
        this.sampleRate = opts?.sampleRate ?? 24000;
    }
    createBuffer(_channels: number, length: number, sampleRate: number) {
        return new FakeAudioBuffer(length, sampleRate);
    }
    createBufferSource() {
        return new FakeAudioBufferSource();
    }
    resume() {
        this.state = 'running';
        return Promise.resolve();
    }
    close() {
        this.state = 'closed';
        return Promise.resolve();
    }
}
if (typeof window !== 'undefined') {
    // @ts-expect-error
    window.AudioContext = FakeAudioContext;
}
