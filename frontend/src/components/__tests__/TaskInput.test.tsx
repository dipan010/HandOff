import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TaskInput } from '../TaskInput';

const MAX_TASK_LENGTH = 4000;

describe('TaskInput', () => {
    it('renders the task textarea and URL input', () => {
        render(<TaskInput onStart={() => {}} disabled={false} />);
        expect(screen.getByLabelText(/Agent Instructions/i)).toBeInTheDocument();
        expect(screen.getByLabelText(/Target URL/i)).toBeInTheDocument();
    });

    it('disables Execute button when task is empty', () => {
        render(<TaskInput onStart={() => {}} disabled={false} />);
        expect(screen.getByRole('button', { name: /Execute Mission/i })).toBeDisabled();
    });

    it('enables Execute button when a valid task is entered', async () => {
        const user = userEvent.setup();
        render(<TaskInput onStart={() => {}} disabled={false} />);
        await user.type(screen.getByLabelText(/Agent Instructions/i), 'search for cats');
        expect(screen.getByRole('button', { name: /Execute Mission/i })).toBeEnabled();
    });

    it('disables when the disabled prop is true', () => {
        render(<TaskInput onStart={() => {}} disabled />);
        expect(screen.getByLabelText(/Agent Instructions/i)).toBeDisabled();
        expect(screen.getByRole('button', { name: /Execute Mission/i })).toBeDisabled();
    });

    it('calls onStart with trimmed task and url', async () => {
        const onStart = vi.fn();
        const user = userEvent.setup();
        render(<TaskInput onStart={onStart} disabled={false} />);
        await user.type(screen.getByLabelText(/Agent Instructions/i), '  find news  ');
        await user.type(screen.getByLabelText(/Target URL/i), 'https://news.ycombinator.com');
        await user.click(screen.getByRole('button', { name: /Execute Mission/i }));
        expect(onStart).toHaveBeenCalledWith('find news', 'https://news.ycombinator.com', true);
    });

    it('shows character count warning when approaching the limit', () => {
        render(<TaskInput onStart={() => {}} disabled={false} />);
        const longText = 'a'.repeat(MAX_TASK_LENGTH - 200);
        fireEvent.change(screen.getByLabelText(/Agent Instructions/i), { target: { value: longText } });
        expect(screen.getByText(/characters remaining/i)).toBeInTheDocument();
    });

    it('does not show character count when well under the limit', () => {
        render(<TaskInput onStart={() => {}} disabled={false} />);
        expect(screen.queryByText(/characters remaining/i)).not.toBeInTheDocument();
    });

    it('shows URL scheme warning for bare domain', async () => {
        const user = userEvent.setup();
        render(<TaskInput onStart={() => {}} disabled={false} />);
        await user.type(screen.getByLabelText(/Target URL/i), 'google.com');
        expect(screen.getByText(/must start with http/i)).toBeInTheDocument();
    });

    it('shows URL scheme warning for javascript: scheme', async () => {
        const user = userEvent.setup();
        render(<TaskInput onStart={() => {}} disabled={false} />);
        await user.type(screen.getByLabelText(/Target URL/i), 'javascript:alert(1)');
        expect(screen.getByText(/must start with http/i)).toBeInTheDocument();
    });

    it('does not show URL warning for valid https URL', () => {
        render(<TaskInput onStart={() => {}} disabled={false} />);
        fireEvent.change(screen.getByLabelText(/Target URL/i), { target: { value: 'https://example.com' } });
        expect(screen.queryByText(/must start with http/i)).not.toBeInTheDocument();
    });

    it('disables Execute when URL scheme is invalid', async () => {
        const user = userEvent.setup();
        render(<TaskInput onStart={() => {}} disabled={false} />);
        await user.type(screen.getByLabelText(/Agent Instructions/i), 'test task');
        await user.type(screen.getByLabelText(/Target URL/i), 'file:///etc/passwd');
        expect(screen.getByRole('button', { name: /Execute Mission/i })).toBeDisabled();
    });

    it('does not call onStart when URL is invalid', async () => {
        const onStart = vi.fn();
        const user = userEvent.setup();
        render(<TaskInput onStart={onStart} disabled={false} />);
        await user.type(screen.getByLabelText(/Agent Instructions/i), 'task');
        await user.type(screen.getByLabelText(/Target URL/i), 'ftp://files.example.com');
        await user.click(screen.getByRole('button', { name: /Execute Mission/i }));
        expect(onStart).not.toHaveBeenCalled();
    });
});
