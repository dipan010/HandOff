import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PausePromptModal } from '../PausePromptModal';

describe('PausePromptModal', () => {
    it('renders the prompt text and reason', () => {
        render(
            <PausePromptModal
                prompt={{ reason: 'login', prompt: 'Please sign in', needs_input: false }}
                onRespond={() => {}}
            />
        );
        expect(screen.getByText('Please sign in')).toBeInTheDocument();
        expect(screen.getByText(/Reason: login/i)).toBeInTheDocument();
    });

    it('shows the Continue button when no input needed', () => {
        render(
            <PausePromptModal
                prompt={{ reason: '', prompt: 'Click when ready', needs_input: false }}
                onRespond={() => {}}
            />
        );
        expect(screen.getByRole('button', { name: /Continue/i })).toBeEnabled();
    });

    it('shows an input field when needs_input is true', () => {
        render(
            <PausePromptModal
                prompt={{ reason: '', prompt: 'Enter your code', needs_input: true }}
                onRespond={() => {}}
            />
        );
        expect(screen.getByPlaceholderText(/Type your response/i)).toBeInTheDocument();
    });

    it('disables Submit when input is required but empty (H10 supporting behaviour)', () => {
        render(
            <PausePromptModal
                prompt={{ reason: '', prompt: 'Enter code', needs_input: true }}
                onRespond={() => {}}
            />
        );
        const submit = screen.getByRole('button', { name: /Submit & Continue/i });
        expect(submit).toBeDisabled();
    });

    it('forwards typed input on submit (H10 regression)', async () => {
        const onRespond = vi.fn();
        const user = userEvent.setup();
        render(
            <PausePromptModal
                prompt={{ reason: '', prompt: 'Enter code', needs_input: true }}
                onRespond={onRespond}
            />
        );
        await user.type(screen.getByPlaceholderText(/Type your response/i), 'abc123');
        await user.click(screen.getByRole('button', { name: /Submit & Continue/i }));
        expect(onRespond).toHaveBeenCalledWith('pause_gate', true, 'abc123');
    });

    it('forwards approved=false on Cancel', async () => {
        const onRespond = vi.fn();
        const user = userEvent.setup();
        render(
            <PausePromptModal
                prompt={{ reason: '', prompt: 'Sign in', needs_input: false }}
                onRespond={onRespond}
            />
        );
        await user.click(screen.getByRole('button', { name: /Cancel Task/i }));
        expect(onRespond).toHaveBeenCalledWith('pause_gate', false);
    });

    it('hides reason line when reason is empty', () => {
        render(
            <PausePromptModal
                prompt={{ reason: '', prompt: 'Just go', needs_input: false }}
                onRespond={() => {}}
            />
        );
        expect(screen.queryByText(/Reason:/i)).not.toBeInTheDocument();
    });
});
