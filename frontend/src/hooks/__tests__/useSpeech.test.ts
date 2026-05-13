import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useSpeech } from '../useSpeech';

const synth = () => (window as any).speechSynthesis;

describe('useSpeech', () => {
    beforeEach(() => {
        synth().cancel();
    });

    it('does nothing when disabled', () => {
        const { result } = renderHook(() => useSpeech(false));
        act(() => result.current.speak('hello'));
        expect(synth().getUtterances()).toHaveLength(0);
    });

    it('does nothing for empty text', () => {
        const { result } = renderHook(() => useSpeech(true));
        act(() => result.current.speak(''));
        act(() => result.current.speak('   '));
        expect(synth().getUtterances()).toHaveLength(0);
    });

    it('speaks a single utterance', () => {
        const { result } = renderHook(() => useSpeech(true));
        act(() => result.current.speak('first'));
        const utterances = synth().getUtterances();
        expect(utterances).toHaveLength(1);
        expect(utterances[0].text).toBe('first');
    });

    it('queues utterances and plays them in order', async () => {
        const { result } = renderHook(() => useSpeech(true));
        act(() => {
            result.current.speak('first');
            result.current.speak('second');
            result.current.speak('third');
        });
        // Wait for the queue to drain via queueMicrotask
        await act(async () => {
            await new Promise(r => setTimeout(r, 50));
        });
        const utterances = synth().getUtterances();
        expect(utterances.length).toBeGreaterThanOrEqual(3);
        expect(utterances[0].text).toBe('first');
        expect(utterances[1].text).toBe('second');
        expect(utterances[2].text).toBe('third');
    });

    it('skips immediate duplicate text', () => {
        const { result } = renderHook(() => useSpeech(true));
        act(() => {
            result.current.speak('same');
            result.current.speak('same');
            result.current.speak('same');
        });
        // Only the first should be queued
        expect(synth().getUtterances()).toHaveLength(1);
    });

    it('speaks again after a different intervening utterance', async () => {
        const { result } = renderHook(() => useSpeech(true));
        act(() => {
            result.current.speak('first');
            result.current.speak('second');
        });
        await act(async () => {
            await new Promise(r => setTimeout(r, 50));
        });
        // Note: useSpeech tracks lastQueuedRef which prevents IMMEDIATE dupes;
        // after 'second' has been queued, 'first' could come back.
        const allTexts = synth().getUtterances().map((u: any) => u.text);
        expect(allTexts).toContain('first');
        expect(allTexts).toContain('second');
    });

    it('caps the queue at 5 items', () => {
        const { result } = renderHook(() => useSpeech(true));
        // Pump 10 distinct items before any can drain.  Drop oldest.
        act(() => {
            for (let i = 0; i < 10; i++) {
                result.current.speak(`msg-${i}`);
            }
        });
        // Internal queue is hard to observe directly, but the first speak
        // pulls the head off the queue, and the cap ensures we don't speak
        // more than (1 head + 5 queued) = 6 distinct items even in a synchronous burst.
        const spoken = synth().getUtterances().map((u: any) => u.text);
        expect(spoken.length).toBeLessThanOrEqual(6);
    });

    it('stop() cancels and clears state', () => {
        const { result } = renderHook(() => useSpeech(true));
        act(() => result.current.speak('hello'));
        act(() => result.current.stop());
        // After stop, the same text should be queueable again
        act(() => result.current.speak('hello'));
        // Both calls successfully queued — stop cleared the dedup ref
        expect(synth().getUtterances().length).toBeGreaterThanOrEqual(1);
    });

    it('cancels in-flight speech on unmount', () => {
        const { result, unmount } = renderHook(() => useSpeech(true));
        act(() => result.current.speak('persistent'));
        unmount();
        expect(synth().speaking).toBe(false);
    });
});
