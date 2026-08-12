import { describe, expect, it } from 'vitest';

import { isVideoUrl, statusLabel } from './format';

describe('format helpers', () => {
  it('formats machine-readable statuses for display', () => {
    expect(statusLabel('under_review')).toBe('under review');
  });

  it('recognizes videos by media type or URL extension', () => {
    expect(isVideoUrl('/media/file', 'video/mp4')).toBe(true);
    expect(isVideoUrl('https://example.test/clip.webm?download=1')).toBe(true);
    expect(isVideoUrl('https://example.test/image.webp', 'image/webp')).toBe(false);
  });
});
