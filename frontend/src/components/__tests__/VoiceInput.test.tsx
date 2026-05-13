import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { VoiceInput } from '../VoiceInput';

// ── Fake SpeechRecognition ────────────────────────────────────────────────
class FakeSpeechRecognition {
    continuous = false;
    interimResults = false;
    onresult: ((e: any) => void) | null = null;
    onerror: ((e: any) => void) | null = null;
    onend: (() => void) | null = null;
    started = false;
    aborted = false;

    start() {
        this.started = true;
    }
    stop() {
        this.started = false;
        this.onend?.();
    }
    abort() {
        this.aborted = true;
    }

    emit(transcript: string) {
        this.onresult?.({ results: [[{ transcript }]] });
    }
}

let lastInstance: FakeSpeechRecognition | null = null;

beforeEach(() => {
    lastInstance = null;
    (window as any).SpeechRecognition = class extends FakeSpeechRecognition {
        constructor() {
            super();
            lastInstance = this;
        }
    };
});

describe('VoiceInput', () => {
    it('renders the voice input button when supported', () => {
        render(<VoiceInput onTranscript={() => {}} />);
        expect(screen.getByTitle(/Speak your task/i)).toBeInTheDocument();
    });

    it('renders Not Supported fallback when API is missing', () => {
        delete (window as any).SpeechRecognition;
        delete (window as any).webkitSpeechRecognition;
        render(<VoiceInput onTranscript={() => {}} />);
        expect(screen.getByText(/Not Supported/i)).toBeInTheDocument();
    });

    it('starts recording on click', async () => {
        const user = userEvent.setup();
        render(<VoiceInput onTranscript={() => {}} />);
        await user.click(screen.getByRole('button'));
        expect(lastInstance?.started).toBe(true);
        expect(screen.getByText(/Listening.../i)).toBeInTheDocument();
    });

    it('forwards the transcript to onTranscript via the latest callback ref (M11 regression)', async () => {
        const cb1 = vi.fn();
        const cb2 = vi.fn();
        const user = userEvent.setup();
        const { rerender } = render(<VoiceInput onTranscript={cb1} />);

        // Re-render with a new callback — should still be picked up via ref
        rerender(<VoiceInput onTranscript={cb2} />);

        await user.click(screen.getByRole('button'));
        lastInstance?.emit('hello world');

        // Latest callback received the transcript; old one did not
        expect(cb2).toHaveBeenCalledWith('hello world');
        expect(cb1).not.toHaveBeenCalled();
    });

    it('creates the recognition object only once across re-renders (M11)', () => {
        const { rerender } = render(<VoiceInput onTranscript={() => {}} />);
        const first = lastInstance;
        rerender(<VoiceInput onTranscript={() => 'changed'} />);
        rerender(<VoiceInput onTranscript={() => 'changed-again'} />);
        // Same instance after re-renders — not recreated each time
        expect(lastInstance).toBe(first);
    });

    it('respects the disabled prop', () => {
        render(<VoiceInput onTranscript={() => {}} disabled />);
        const button = screen.getByRole('button');
        expect(button).toBeDisabled();
    });

    it('aborts recognition on unmount', () => {
        const { unmount } = render(<VoiceInput onTranscript={() => {}} />);
        const inst = lastInstance;
        unmount();
        expect(inst?.aborted).toBe(true);
    });
});
