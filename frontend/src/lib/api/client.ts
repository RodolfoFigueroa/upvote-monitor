import type {
  ItemDetail,
  ItemFilesResponse,
  ItemListParams,
  ItemListResponse,
  RefreshRunResponse,
  RefreshStartResponse,
  RefreshStatusResponse,
  RuleEntry,
  RuleEntryRequest,
  RuleListsResponse,
  SettingsResponse,
  SettingsUpdate,
} from '$lib/types/api';

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let message = response.statusText;
    let detail: unknown;
    try {
      const body = await response.json();
      detail = body.detail;
      if (typeof detail === 'string') {
        message = detail;
      } else if (
        detail &&
        typeof detail === 'object' &&
        'message' in detail &&
        typeof detail.message === 'string'
      ) {
        message = detail.message;
      } else if (typeof body.detail === 'string') {
        message = body.detail;
      }
    } catch {
      // ignore
    }
    throw new ApiError(response.status, message, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

function queryString(params: object): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item !== undefined && item !== null && item !== '') {
          search.append(key, String(item));
        }
      }
    } else if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `?${qs}` : '';
}

export const api = {
  items: {
    list: (params: ItemListParams = {}) =>
      request<ItemListResponse>(`/api/items${queryString(params)}`),
    get: (id: string) => request<ItemDetail>(`/api/items/${id}`),
    approve: (id: string) =>
      request<ItemDetail>(`/api/items/${id}/approve`, { method: 'POST' }),
    analyze: (id: string) =>
      request<ItemDetail>(`/api/items/${id}/analyze`, { method: 'POST' }),
    reject: (id: string) =>
      request<ItemDetail>(`/api/items/${id}/reject`, { method: 'POST' }),
    retryDownload: (id: string) =>
      request<ItemDetail>(`/api/items/${id}/retry-download`, { method: 'POST' }),
    files: (id: string) => request<ItemFilesResponse>(`/api/items/${id}/files`),
  },
  settings: {
    get: () => request<SettingsResponse>('/api/settings'),
    update: (body: SettingsUpdate) =>
      request<SettingsResponse>('/api/settings', {
        method: 'PATCH',
        body: JSON.stringify(body),
      }),
  },
  rules: {
    get: () => request<RuleListsResponse>('/api/rules'),
    addWhitelist: (body: RuleEntryRequest) =>
      request<RuleListsResponse>('/api/rules/whitelist', {
        method: 'POST',
        body: JSON.stringify({ source: 'reddit', target_type: 'community', ...body }),
      }),
    removeWhitelist: (entry: RuleEntry) =>
      request<RuleListsResponse>(
        `/api/rules/whitelist/${encodeURIComponent(entry.source)}/${encodeURIComponent(entry.target_type)}/${encodeURIComponent(entry.target_value)}`,
        { method: 'DELETE' }
      ),
    addBlacklist: (body: RuleEntryRequest) =>
      request<RuleListsResponse>('/api/rules/blacklist', {
        method: 'POST',
        body: JSON.stringify({ source: 'reddit', target_type: 'community', ...body }),
      }),
    removeBlacklist: (entry: RuleEntry) =>
      request<RuleListsResponse>(
        `/api/rules/blacklist/${encodeURIComponent(entry.source)}/${encodeURIComponent(entry.target_type)}/${encodeURIComponent(entry.target_value)}`,
        { method: 'DELETE' }
      ),
  },
  refresh: {
    start: () =>
      request<RefreshStartResponse>('/api/refresh', { method: 'POST' }),
    status: () => request<RefreshStatusResponse>('/api/refresh/status'),
    runs: (limit = 20, offset = 0) =>
      request<RefreshRunResponse[]>(
        `/api/refresh/runs${queryString({ limit, offset })}`
      ),
  },
};
