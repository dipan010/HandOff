import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SafetyConfirmModal } from '../SafetyConfirmModal';
import { SafetyConfirmRequest } from '../../lib/types';

const sampleRequest: SafetyConfirmRequest = {
    request_id: 'req-abc-123',
    action: {
        action: 'navigate',
        args: { url: 'https://pay.example.com' },
        original_call_id: 'fc-different-id',
    },
};

describe('SafetyConfirmModal', () => {
    it('renders the action JSON payload', () => {
        render(<SafetyConfirmModal request={sampleRequest} onRespond={() => {}} />);
        expect(screen.getByText(/Intercepted Payload/i)).toBeInTheDocument();
        expect(screen.getByText(/pay\.example\.com/)).toBeInTheDocument();
    });

    it('forwards request.request_id on approve (H9 regression)', async () => {
        const onRespond = vi.fn();
        const user = userEvent.setup();
        render(<SafetyConfirmModal request={sampleRequest} onRespond={onRespond} />);

        await user.click(screen.getByRole('button', { name: /Authorize Proceed/i }));
        expect(onRespond).toHaveBeenCalledWith('req-abc-123', true);
        // Critically, NOT the action.original_call_id
        expect(onRespond).not.toHaveBeenCalledWith('fc-different-id', expect.anything());
    });

    it('forwards request.request_id on deny', async () => {
        const onRespond = vi.fn();
        const user = userEvent.setup();
        render(<SafetyConfirmModal request={sampleRequest} onRespond={onRespond} />);

        await user.click(screen.getByRole('button', { name: /Deny Access/i }));
        expect(onRespond).toHaveBeenCalledWith('req-abc-123', false);
    });

    it('shows the alert title', () => {
        render(<SafetyConfirmModal request={sampleRequest} onRespond={() => {}} />);
        expect(screen.getByText(/Action Requires Clearance/i)).toBeInTheDocument();
    });
});
