import { SafetyConfirmRequest } from '../lib/types';
import { ShieldAlert, CheckCircle, XCircle } from 'lucide-react';

interface SafetyConfirmModalProps {
    request: SafetyConfirmRequest;
    onRespond: (actionId: string, approved: boolean) => void;
}

export function SafetyConfirmModal({ request, onRespond }: SafetyConfirmModalProps) {
    return (
        <div className="fixed inset-0 bg-slate-900/80 backdrop-blur-sm z-[1000] flex items-center justify-center animate-[fadeIn_0.2s_ease]">
            <div className="bg-white dark:bg-slate-900 border border-primary/40 rounded-3xl p-8 w-[90%] max-w-[500px] shadow-[0_0_50px_rgba(67,135,244,0.15)]">
                <div className="flex items-center gap-4 text-primary mb-4">
                    <ShieldAlert size={32} />
                    <h2 className="text-2xl font-black tracking-tight">Action Requires Clearance</h2>
                </div>

                <p className="text-slate-500 text-sm mb-6">
                    The autonomous agent has requested to perform a highly sensitive operation.
                    Please review the telemetry data below and explicitly authorize this action.
                </p>

                <div className="bg-slate-950 border border-slate-800 rounded-xl p-4 font-mono text-sm text-cyan-400 overflow-x-auto mb-8">
                    <div className="text-slate-500 mb-2">// Intercepted Payload</div>
                    <pre className="whitespace-pre-wrap break-words">
                        {JSON.stringify(request.action, null, 2)}
                    </pre>
                </div>

                <div className="flex gap-4">
                    <button
                        className="flex-1 px-4 py-4 rounded-xl border-2 border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors font-bold flex items-center justify-center gap-2"
                        onClick={() => onRespond(request.request_id, false)}
                    >
                        <XCircle size={18} />
                        Deny Access
                    </button>

                    <button
                        className="flex-1 px-4 py-4 rounded-xl bg-primary text-white hover:bg-primary/90 transition-all shadow-lg active:scale-95 font-bold flex items-center justify-center gap-2"
                        onClick={() => onRespond(request.request_id, true)}
                    >
                        <CheckCircle size={18} />
                        Authorize Proceed
                    </button>
                </div>
            </div>
        </div>
    );
}
