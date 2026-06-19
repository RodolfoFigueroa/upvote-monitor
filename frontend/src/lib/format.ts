import type { ItemDetail, ItemFile, ItemSummary, RefreshRunResponse } from '$lib/types/api';

export function statusLabel(value: string): string {
  return value.replaceAll('_', ' ');
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return 'Not yet';
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(value));
}

export function formatRelative(value: string | null | undefined): string {
  if (!value) return 'Not yet';
  const then = new Date(value).getTime();
  const deltaSeconds = Math.round((then - Date.now()) / 1000);
  const abs = Math.abs(deltaSeconds);

  if (abs < 60) return 'Just now';
  if (abs < 3600) return `${Math.round(abs / 60)}m ago`;
  if (abs < 86400) return `${Math.round(abs / 3600)}h ago`;
  if (abs < 604800) return `${Math.round(abs / 86400)}d ago`;
  return formatDate(value);
}

export function sourceLabel(item: ItemSummary | ItemDetail): string {
  return item.source.charAt(0).toUpperCase() + item.source.slice(1);
}

export function communityLabel(item: ItemSummary | ItemDetail): string {
  return item.community_label ?? item.author_label ?? sourceLabel(item);
}

export function isVideoUrl(value: string, mediaType?: string): boolean {
  if (mediaType?.startsWith('video/')) return true;
  return /\.(mp4|webm|mov)(\?|$)/i.test(value);
}

export function mediaUrls(
  item: ItemSummary | ItemDetail,
  files: ItemFile[] = [],
  options: { preferSourceVideo?: boolean } = {}
): {
  url: string;
  label: string;
  mediaType?: string;
}[] {
  if (files.length > 0) {
    return files.map((file) => ({
      url: file.url,
      label: file.filename,
      mediaType: file.media_type,
    }));
  }

  const sourceItems =
    'media' in item
      ? item.media.map((media) => ({
          url: media.download_url,
          mediaType: media.content_type ?? media.media_type,
        }))
      : [];
  const sourceUrls = 'source_urls' in item ? item.source_urls : [];
  const prefersSourceVideo = ['hosted:video', 'x_video', 'x_gif', 'x_mixed'].includes(
    item.item_kind
  );
  const items: { url: string; mediaType?: string }[] =
    options.preferSourceVideo && prefersSourceVideo && sourceItems.length > 0
      ? sourceItems
      : item.preview_urls.length > 0
        ? item.preview_urls.map((url) => ({ url }))
        : sourceItems.length > 0
          ? sourceItems
          : sourceUrls.map((url) => ({ url }));

  return items.map((mediaItem) => ({
    url: mediaItem.url,
    label: item.title,
    mediaType: mediaItem.mediaType,
  }));
}

export function refreshSummary(run: RefreshRunResponse | null): string {
  if (!run) return 'No refresh runs yet';
  const started = formatRelative(run.started_at);
  if (run.status === 'failed') return `Last refresh failed ${started}`;
  if (run.status === 'completed') {
    return `${run.new_items} new, ${run.downloads_triggered} downloads, ${started}`;
  }
  return `${statusLabel(run.status)} since ${started}`;
}
