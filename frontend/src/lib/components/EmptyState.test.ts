import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import EmptyState from './EmptyState.svelte';

describe('EmptyState', () => {
  it('renders its title and optional body', () => {
    render(EmptyState, { title: 'Nothing queued', body: 'Refresh a source to find items.' });

    expect(screen.getByRole('heading', { name: 'Nothing queued' })).toBeInTheDocument();
    expect(screen.getByText('Refresh a source to find items.')).toBeInTheDocument();
  });

  it('omits body content when none is provided', () => {
    render(EmptyState, { title: 'Nothing queued' });

    expect(screen.queryByRole('paragraph')).not.toBeInTheDocument();
  });
});
