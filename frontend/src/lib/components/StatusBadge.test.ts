import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import StatusBadge from './StatusBadge.svelte';

describe('StatusBadge', () => {
  it('renders a friendly label and known tone', () => {
    render(StatusBadge, { value: 'under_review' });

    expect(screen.getByText('under review')).toHaveAttribute('data-tone', 'review');
  });

  it('uses the neutral tone for an unknown status', () => {
    render(StatusBadge, { value: 'queued_elsewhere' });

    expect(screen.getByText('queued elsewhere')).toHaveAttribute('data-tone', 'neutral');
  });
});
