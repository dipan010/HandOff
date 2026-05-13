import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useWebSocket } from '../useWebSocket';

// ── Fake WebSocket plumbing ────────────────────────────────────────────────
const sockets: FakeWebSocket[] = [];

class FakeWebSocket {
    static CONNECTING = 0;
    static OPEN = 1;
    static CLOSING = 2;
    static CLOSED = 3;

    readyState = FakeWebSocket.CONNECTING;
    onopen: ((e: any) => void) | null = null;
    onmessage: ((e: any) => void) | null = null;
    onclose: ((e: any) => void) | null = null;
    onerror: ((e: any) => void) | null = null;
    sent: string[] = [];

    constructor(public url: string) {
        sockets.push(this);
    }

    // ── Simulation helpers ────────────────────────
    open() {
        this.readyState = FakeWebSocket.OPEN;
        this.onopen?.({});
    }
    receive(msg: any) {
        this.onmessage?.({ data: JSON.stringify(msg) });
    }
    receiveRaw(data: string) {
        this.onmessage?.({ data });
    }

    send(data: string) {
        this.sent.push(data);
    }
    close() {
        this.readyState = FakeWebSocket.CLOSED;
        this.onclose?.({});
    }
}

beforeEach(() => {
    sockets.length = 0;
    (globalThis as any).WebSocket = FakeWebSocket;
    (FakeWebSocket as any).OPEN = 1;
});

afterEach(() => {
    sockets.forEach(s => (s.readyState = FakeWebSocket.CLOSED));
});

const lastSocket = () => sockets[sockets.length - 1];

describe('useWebSocket', () => {
    it('does not connect when sessionId is null', () => {
        renderHook(() => useWebSocket(null));
        expect(sockets).toHaveLength(0);
    });

    it('opens a WebSocket to the correct URL when sessionId is set', () => {
        renderHook(() => useWebSocket('abc123'));
        expect(sockets).toHaveLength(1);
        expect(lastSocket().url).toBe('ws://localhost:8080/ws/abc123');
    });

    it('sets isConnected=true after open', async () => {
        const { result } = renderHook(() => useWebSocket('s1'));
        expect(result.current.isConnected).toBe(false);
        act(() => lastSocket().open());
        await waitFor(() => expect(result.current.isConnected).toBe(true));
    });

    it('handles status_update messages', async () => {
        const { result } = renderHook(() => useWebSocket('s1'));
        act(() => lastSocket().open());
        act(() => lastSocket().receive({
            type: 'status_update',
            data: { status: 'thinking', detail: 'Step 3: Analyzing screen' }
        }));
        await waitFor(() => {
            expect(result.current.status).toBe('thinking');
            expect(result.current.statusDetail).toBe('Step 3: Analyzing screen');
        });
    });

    it('handles screenshot_update messages', async () => {
        const { result } = renderHook(() => useWebSocket('s1'));
        act(() => lastSocket().open());
        act(() => lastSocket().receive({
            type: 'screenshot_update',
            data: { screenshot: 'BASE64DATA', step: 7 }
        }));
        await waitFor(() => {
            expect(result.current.screenshot).toBe('BASE64DATA');
            expect(result.current.step).toBe(7);
        });
    });

    it('handles narration messages', async () => {
        const { result } = renderHook(() => useWebSocket('s1'));
        act(() => lastSocket().open());
        act(() => lastSocket().receive({ type: 'narration', data: { text: 'Hello.' } }));
        await waitFor(() => expect(result.current.narration).toBe('Hello.'));
    });

    it('handles action_preview messages', async () => {
        const { result } = renderHook(() => useWebSocket('s1'));
        act(() => lastSocket().open());
        act(() => lastSocket().receive({
            type: 'action_preview',
            data: { text: 'Click the search box' }
        }));
        await waitFor(() => expect(result.current.actionPreview).toBe('Click the search box'));
    });

    it('handles safety_confirm with request_id', async () => {
        const { result } = renderHook(() => useWebSocket('s1'));
        act(() => lastSocket().open());
        act(() => lastSocket().receive({
            type: 'safety_confirm',
            data: { request_id: 'req-42', action: { action: 'pay' } }
        }));
        await waitFor(() => {
            expect(result.current.safetyRequest?.request_id).toBe('req-42');
            expect(result.current.status).toBe('confirming');
        });
    });

    it('handles pause_prompt messages', async () => {
        const { result } = renderHook(() => useWebSocket('s1'));
        act(() => lastSocket().open());
        act(() => lastSocket().receive({
            type: 'pause_prompt',
            data: { reason: 'login', prompt: 'Sign in', needs_input: false }
        }));
        await waitFor(() => {
            expect(result.current.pausePrompt?.prompt).toBe('Sign in');
            expect(result.current.status).toBe('confirming');
        });
    });

    it('handles task_complete', async () => {
        const { result } = renderHook(() => useWebSocket('s1'));
        act(() => lastSocket().open());
        act(() => lastSocket().receive({
            type: 'task_complete',
            data: { summary: 'Booking confirmed' }
        }));
        await waitFor(() => {
            expect(result.current.status).toBe('completed');
            expect(result.current.taskSummary).toBe('Booking confirmed');
        });
    });

    it('handles error messages', async () => {
        const { result } = renderHook(() => useWebSocket('s1'));
        act(() => lastSocket().open());
        act(() => lastSocket().receive({
            type: 'error',
            data: { message: 'Boom' }
        }));
        await waitFor(() => {
            expect(result.current.status).toBe('error');
            expect(result.current.error).toBe('Boom');
        });
    });

    it('ignores malformed JSON without crashing', () => {
        const { result } = renderHook(() => useWebSocket('s1'));
        act(() => lastSocket().open());
        // Should not throw
        act(() => lastSocket().receiveRaw('not valid json'));
        expect(result.current.status).toBe('idle');
    });

    it('startTask sends the right message shape', async () => {
        const { result } = renderHook(() => useWebSocket('s1'));
        act(() => lastSocket().open());
        await waitFor(() => expect(result.current.isConnected).toBe(true));
        act(() => result.current.startTask('search cats', 'https://google.com', false, true, true));
        const sent = JSON.parse(lastSocket().sent[0]);
        expect(sent.type).toBe('task_start');
        expect(sent.data.task).toBe('search cats');
        expect(sent.data.start_url).toBe('https://google.com');
        expect(sent.data.grandparents_mode).toBe(true);
        expect(sent.data.narration_enabled).toBe(true);
    });

    it('startTask errors when socket is not open', () => {
        const { result } = renderHook(() => useWebSocket('s1'));
        // Don't open the socket
        act(() => result.current.startTask('test', '', false, false, false));
        expect(result.current.error).toMatch(/not connected/i);
    });

    it('sendSafetyResponse includes userInput when provided', async () => {
        const { result } = renderHook(() => useWebSocket('s1'));
        act(() => lastSocket().open());
        await waitFor(() => expect(result.current.isConnected).toBe(true));
        act(() => result.current.sendSafetyResponse('req-7', true, 'user-typed'));
        const sent = JSON.parse(lastSocket().sent[0]);
        expect(sent.type).toBe('safety_response');
        expect(sent.data.request_id).toBe('req-7');
        expect(sent.data.approved).toBe(true);
        expect(sent.data.user_input).toBe('user-typed');
    });

    it('sendSafetyResponse without userInput sends null', async () => {
        const { result } = renderHook(() => useWebSocket('s1'));
        act(() => lastSocket().open());
        await waitFor(() => expect(result.current.isConnected).toBe(true));
        act(() => result.current.sendSafetyResponse('req-8', false));
        const sent = JSON.parse(lastSocket().sent[0]);
        expect(sent.data.user_input).toBeNull();
    });

    it('cancelTask sends cancel_task and updates state', async () => {
        const { result } = renderHook(() => useWebSocket('s1'));
        act(() => lastSocket().open());
        await waitFor(() => expect(result.current.isConnected).toBe(true));
        act(() => result.current.cancelTask());
        const sent = JSON.parse(lastSocket().sent[0]);
        expect(sent.type).toBe('cancel_task');
        expect(result.current.status).toBe('cancelled');
    });

    it('cleans up socket on unmount', () => {
        const { unmount } = renderHook(() => useWebSocket('s1'));
        const sock = lastSocket();
        unmount();
        expect(sock.readyState).toBe(FakeWebSocket.CLOSED);
    });
});
