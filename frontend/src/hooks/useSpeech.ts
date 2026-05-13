"use client";

import { useRef, useCallback, useEffect } from 'react';

/**
 * Queue-based wrapper around the Web SpeechSynthesis API.
 * - Multiple speak() calls queue and play in order — they no longer cancel each other.
 * - Skips duplicate consecutive utterances (Gemini sometimes repeats).
 * - Caps the queue so a burst of state changes can't pile up audio indefinitely.
 * - Cleans up on unmount.
 *
 * For visually-impaired users this matters: narration, status updates and
 * action previews all reach the ears in the order they happened, without
 * a later message silencing an earlier one mid-sentence.
 */
const MAX_QUEUE = 5;

export function useSpeech(enabled: boolean) {
    const synthRef = useRef<SpeechSynthesis | null>(null);
    const queueRef = useRef<string[]>([]);
    const isSpeakingRef = useRef(false);
    const lastQueuedRef = useRef<string>('');

    useEffect(() => {
        if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
            synthRef.current = window.speechSynthesis;
        }
        return () => {
            synthRef.current?.cancel();
            queueRef.current = [];
            isSpeakingRef.current = false;
        };
    }, []);

    const speakNext = useCallback(() => {
        if (!synthRef.current) {
            isSpeakingRef.current = false;
            return;
        }
        const next = queueRef.current.shift();
        if (!next) {
            isSpeakingRef.current = false;
            return;
        }
        isSpeakingRef.current = true;
        const utterance = new SpeechSynthesisUtterance(next);
        utterance.rate = 0.95;
        utterance.pitch = 1.0;
        utterance.volume = 1.0;
        utterance.onend = () => speakNext();
        utterance.onerror = () => speakNext();
        synthRef.current.speak(utterance);
    }, []);

    const speak = useCallback((text: string) => {
        if (!enabled || !synthRef.current || !text.trim()) return;
        const trimmed = text.trim();
        // Skip immediate duplicates (last queued OR currently playing)
        if (trimmed === lastQueuedRef.current) return;
        lastQueuedRef.current = trimmed;

        queueRef.current.push(trimmed);
        // Drop oldest if queue grows too large — keep audio "current"
        if (queueRef.current.length > MAX_QUEUE) {
            queueRef.current = queueRef.current.slice(-MAX_QUEUE);
        }
        if (!isSpeakingRef.current) {
            speakNext();
        }
    }, [enabled, speakNext]);

    const stop = useCallback(() => {
        synthRef.current?.cancel();
        queueRef.current = [];
        isSpeakingRef.current = false;
        lastQueuedRef.current = '';
    }, []);

    return { speak, stop };
}
