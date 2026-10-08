import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { RecordingPanel } from './RecordingPanel';

const limits = { min_duration_s: 3, max_duration_s: 30 };

describe('RecordingPanel', () => {
  it('renders the idle state with ECHO-0 ready line and a record control', () => {
    render(<RecordingPanel limits={limits} onProcessed={vi.fn()} onArchiveChanged={vi.fn()} />);
    expect(screen.getByText('I am ready to listen.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /start recording/i })).toBeEnabled();
    expect(screen.queryByRole('button', { name: /stop recording/i })).not.toBeInTheDocument();
    expect(screen.getByLabelText('recording timer')).toHaveTextContent('00:00.0');
  });

  it('reports an unavailable microphone API as a clearable error, never a contradictory state', async () => {
    // jsdom has no navigator.mediaDevices → PERMISSION_UNAVAILABLE path
    render(<RecordingPanel limits={limits} onProcessed={vi.fn()} onArchiveChanged={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /start recording/i }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('MIC_UNAVAILABLE');
    expect(screen.getByText('I cannot hear without permission.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /stop recording/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /clear/i }));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByText('I am ready to listen.')).toBeInTheDocument();
  });
});
