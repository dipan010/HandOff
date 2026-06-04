import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { SessionHistory } from '../SessionHistory';

const originalFetch = global.fetch;

beforeEach(() => {
    global.fetch = originalFetch;
});

describe('SessionHistory', () => {
    it('shows loading state initially', () => {
        global.fetch = vi.fn(() => new Promise(() => {})) as any; // never resolves
        render(<SessionHistory />);
        expect(screen.getByText(/Loading archives/i)).toBeInTheDocument();
    });

    it('shows empty state when no sessions returned', async () => {
        global.fetch = vi.fn(() =>
            Promise.resolve({ ok: true, json: () => Promise.resolve({ sessions: [] }) })
        ) as any;
        render(<SessionHistory />);
        await waitFor(() =>
            expect(screen.getByText(/No past missions found/i)).toBeInTheDocument()
        );
    });

    it('renders session list', async () => {
        global.fetch = vi.fn(() =>
            Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    sessions: [
                        {
                            session_id: 's1',
                            task: 'Book a flight to Paris',
                            start_url: '',
                            status: 'completed',
                            created_at: '2026-05-10T12:00:00Z',
                        },
                    ],
                }),
            })
        ) as any;
        render(<SessionHistory />);
        await waitFor(() => {
            expect(screen.getByText('Book a flight to Paris')).toBeInTheDocument();
        });
    });

    it('surfaces fetch errors to the user (M13 regression)', async () => {
        global.fetch = vi.fn(() =>
            Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) })
        ) as any;
        render(<SessionHistory />);
        await waitFor(() => {
            expect(screen.getByText(/Could not load session history/i)).toBeInTheDocument();
        });
    });

    it('surfaces network errors to the user', async () => {
        global.fetch = vi.fn(() => Promise.reject(new Error('network'))) as any;
        render(<SessionHistory />);
        await waitFor(() => {
            expect(screen.getByText(/Could not load session history/i)).toBeInTheDocument();
        });
    });
});
