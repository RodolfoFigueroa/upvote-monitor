import { ApiError } from '$lib/api/client';

export type SourceSettingsErrorDetail = {
  code?: string;
  source?: string;
  fields?: string[];
  message?: string;
};

export function sourceSettingsErrorDetail(
  error: unknown,
  source: string
): SourceSettingsErrorDetail | null {
  if (!(error instanceof ApiError)) return null;
  const { detail } = error;
  if (!detail || typeof detail !== 'object') return null;
  if (!('source' in detail) || detail.source !== source) return null;
  return detail as SourceSettingsErrorDetail;
}
