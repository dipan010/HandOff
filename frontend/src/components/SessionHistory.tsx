import { useEffect, useState } from 'react';
import { SessionInfo } from '../lib/types';
import { Archive, Clock } from 'lucide-react';

export function SessionHistory() {
    const [sessions, setSessions] = useState<SessionInfo[]>([]);
    const [loading, setLoading] = useState(true);
    const [fetchError, setFetchError] = useState<string | null>(null);

    useEffect(() => {
        const fetchSessions = async () => {
            try {
                const res = await fetch('http://localhost:8080/sessions');
                if (!res.ok) throw new Error(`Server returned ${res.status}`);
                const data = await res.json();
                setSessions(data.sessions || []);
            } catch (err) {
                console.error(err);
                setFetchError('Could not load session history.');
            } finally {
                setLoading(false);
            }
        };

        fetchSessions();
    }, []);

    return (
        <div className="glass-card" style={{ flex: '0 0 auto' }}>
            <div className="card-title">
                <Archive size={20} style={{ color: 'var(--text-muted)' }} />
                Mission Archives
            </div>

            <div className="scroll-area" style={{ maxHeight: '200px', marginTop: '0.5rem' }}>
                {loading ? (
                    <div style={{ color: 'var(--text-muted)', fontSize: '0.9rem', textAlign: 'center', padding: '1rem' }}>
                        Loading archives...
                    </div>
                ) : fetchError ? (
                    <div style={{ color: '#ef4444', fontSize: '0.9rem', textAlign: 'center', padding: '1rem' }}>
                        {fetchError}
                    </div>
                ) : sessions.length === 0 ? (
                    <div style={{ color: 'var(--text-muted)', fontSize: '0.9rem', textAlign: 'center', padding: '1rem' }}>
                        No past missions found.
                    </div>
                ) : (
                    sessions.map((session) => (
                        <div key={session.session_id} className="action-row" style={{ alignItems: 'center' }}>
                            <Clock size={16} color="var(--text-muted)" />
                            <div className="action-details" style={{ flex: 1, overflow: 'hidden' }}>
                                <p style={{ color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                    {session.task}
                                </p>
                                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginTop: '4px' }}>
                                    <div className={`dot ${session.status === 'completed' ? 'connected' : 'disconnected'}`} style={{ width: 6, height: 6 }} />
                                    <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                        {new Date(session.created_at).toLocaleDateString()}
                                    </span>
                                </div>
                            </div>
                        </div>
                    ))
                )}
            </div>
        </div>
    );
}
