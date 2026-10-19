import { PlanStep } from '../lib/types';

const STATE_STYLE: Record<PlanStep['state'], { icon: string; color: string; label: string }> = {
    waiting: { icon: 'radio_button_unchecked', color: 'text-slate-400', label: 'Waiting' },
    working: { icon: 'progress_activity', color: 'text-primary animate-spin', label: 'Working on it' },
    retrying: { icon: 'replay', color: 'text-amber-500', label: 'Trying again' },
    done: { icon: 'check_circle', color: 'text-green-600', label: 'Done' },
    failed: { icon: 'cancel', color: 'text-red-500', label: 'Could not finish' },
};

export function PlanSteps({ steps }: { steps: PlanStep[] }) {
    return (
        <section aria-label="Steps" className="mt-3 p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-[0.15em] mb-2">Steps</p>
            <ol className="flex flex-col gap-2">
                {steps.map((s) => {
                    const style = STATE_STYLE[s.state] ?? STATE_STYLE.waiting;
                    return (
                        <li key={`${s.number}-${s.title}`} className="flex items-start gap-2">
                            <span className={`material-symbols-outlined text-[18px] shrink-0 ${style.color}`} aria-label={style.label}>
                                {style.icon}
                            </span>
                            <div className="min-w-0">
                                <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                                    {s.number}. {s.title}
                                </p>
                                {s.detail && s.state !== 'waiting' && (
                                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{s.detail}</p>
                                )}
                            </div>
                        </li>
                    );
                })}
            </ol>
        </section>
    );
}
