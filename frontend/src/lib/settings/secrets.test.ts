import { describe, expect, it } from 'vitest';

import { secretPlaceholder } from './secrets';

describe('secretPlaceholder', () => {
  it('does not expose unavailable or unconfigured secrets', () => {
    expect(secretPlaceholder(false, { configured: true, prefix: 'abc', suffix: 'xyz' })).toBe(
      'secrets unavailable'
    );
    expect(secretPlaceholder(true, { configured: false, prefix: null, suffix: null })).toBe(
      'not configured'
    );
  });

  it('formats the safe portions of a configured secret', () => {
    expect(secretPlaceholder(true, { configured: true, prefix: 'abc', suffix: 'xyz' })).toBe(
      'abc...xyz'
    );
    expect(secretPlaceholder(true, { configured: true, prefix: null, suffix: null })).toBe(
      'configured'
    );
  });
});
