import { AgentStatus } from '../lib/types';
import { Activity, XCircle, TerminalSquare } from 'lucide-react';

interface AgentStatusProps {
    status: AgentStatus;
    detail: string;
    step: number;
    narration: string;
    onCancel: () => void;
    canCancel: boolean;
}

export function AgentStatusDisplay({
    status,
    detail,
    step,
    narration,
    onCancel,
    canCancel
}: AgentStatusProps) {

    const getStatusDisplay = () => {
        switch (status) {
            case 'idle': return 'Awaiting Directives';
            case 'started': return 'Agent Initializing';
            case 'navigating': return 'Establishing Connection';
            case 'thinking': return 'Analyzing Visual Data';
            case 'waiting': return 'Waiting a Moment';
            case 'executing': return 'Executing Operation';
            case 'confirming': return 'Require User Override';
            case 'completed': return 'Mission Accomplished';
            case 'error': return 'System Error';
            case 'timeout': return 'Operation Timeout';
            case 'cancelled': return 'Operation Aborted';
            default: return status;
        }
    };

    return (
        <div className="glass-card" style={{ flex: 1, minHeight: '300px', display: 'flex', flexDirection: 'column' }}>
            <div className="card-title" style={{ justifyContent: 'space-between', borderBottom: 'none', paddingBottom: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    <Activity size={20} className="text-accent-purple" />
                    Mission Status
                </div>
                {canCancel && (
                    <button
                        className="btn-primary btn-danger"
                        style={{ padding: '8px 16px', fontSize: '0.85rem', width: 'auto', borderRadius: '8px' }}
                        onClick={onCancel}
                    >
                        <XCircle size={16} />
                        Abort
                    </button>
                )}
            </div>

            <div className={`status-box status-${status}`} style={{ margin: '1rem 0' }}>
                <div className="status-indicator"></div>
                <div className="status-icon">
                    {status === 'idle' ? '💤' :
                        status === 'started' ? '🚀' :
                            status === 'confirming' ? '⚠️' :
                                status === 'completed' ? '✅' :
                                    status === 'error' ? '❌' : '⚡'}
                </div>
                <div className="status-text">
                    <h3>{getStatusDisplay()}</h3>
                    <p>{detail || (status === 'idle' ? 'System ready and standing by.' : 'Processing data...')}</p>
                </div>
            </div>

            {step > 0 && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', background: 'rgba(0,0,0,0.2)', padding: '1rem', borderRadius: '12px' }}>
                    <div style={{ fontSize: '2rem', fontWeight: 800, fontFamily: 'var(--font-display)', color: 'var(--accent-cyan)' }}>
                        {step}
                    </div>
                    <div style={{ fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.1em', color: 'var(--text-secondary)' }}>
                        Actions<br />Executed
                    </div>
                </div>
            )}

            {narration && (
                <div className="narration-stream" style={{ flex: 1, marginTop: '1rem' }}>
                    <TerminalSquare size={20} />
                    <div>
                        <div style={{ fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--accent-purple)', marginBottom: '0.25rem', fontWeight: 600 }}>
                            Live Neural Feed
                        </div>
                        {narration}
                    </div>
                </div>
            )}
        </div>
    );
}
