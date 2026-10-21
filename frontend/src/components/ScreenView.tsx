interface ScreenViewProps {
    screenshot: string | null;
    step: number;
}

import { pictureSrc } from '../lib/picture';
import { MonitorPlay, EyeOff } from 'lucide-react';

export function ScreenView({ screenshot, step }: ScreenViewProps) {
    return (
        <div className="glass-card" style={{ flex: 1, height: '100%', padding: '1.5rem', display: 'flex', flexDirection: 'column' }}>
            <div className="card-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    <MonitorPlay size={20} style={{ color: 'var(--accent-cyan)' }} />
                    Live Viewport
                </div>
                {step > 0 && (
                    <div className="action-step-badge" style={{ background: 'rgba(34, 211, 238, 0.1)', color: 'var(--accent-cyan)' }}>
                        Frame {step}
                    </div>
                )}
            </div>

            <div className="screen-container">
                {screenshot ? (
                    <img
                        src={pictureSrc(screenshot)}
                        alt={`Browser screenshot at step ${step}`}
                    />
                ) : (
                    <div className="screen-placeholder">
                        <EyeOff size={48} />
                        <p>Awaiting Visual Telemetry...</p>
                    </div>
                )}
            </div>
        </div>
    );
}
