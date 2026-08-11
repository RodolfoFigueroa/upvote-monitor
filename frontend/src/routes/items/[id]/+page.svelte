<script lang="ts">
  import { page } from '$app/stores';
  import {
    CircleAlert,
    ExternalLink,
    RotateCcw,
    Tags,
  } from '@lucide/svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import MediaAnalysisPanel from '$lib/components/MediaAnalysisPanel.svelte';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import { api, ApiError } from '$lib/api/client';
  import { communityLabel, formatDate, isVideoUrl } from '$lib/format';
  import { subscribeItemUpdated } from '$lib/sse/store.svelte';
  import type {
    DownloadStatus,
    IllustrationLabel,
    ItemDetail,
    ItemFile,
    MediaAttachment,
  } from '$lib/types/api';
  import { onMount } from 'svelte';

  let item = $state<ItemDetail | null>(null);
  let files = $state<ItemFile[]>([]);
  let loading = $state(true);
  let actionLoading = $state(false);
  let mediaActions = $state<Record<number, string>>({});
  let errorMessage = $state<string | null>(null);

  const itemId = $derived($page.params.id ?? '');
  const terminalDownloadStatuses = new Set<DownloadStatus>(['completed', 'failed']);
  const labelOptions: { value: IllustrationLabel; label: string }[] = [
    { value: 'yes', label: 'Yes' },
    { value: 'no', label: 'No' },
    { value: 'unsure', label: 'Unsure' },
    { value: 'unlabeled', label: 'Unlabeled' },
  ];
  const canChangeApproval = $derived(
    item?.download_status === 'pending' || item?.download_status === 'failed'
  );
  const canRetry = $derived(
    item?.approval_status === 'approved' &&
      (item.download_status === 'failed' || item.download_status === 'pending')
  );
  const rejectedMediaCount = $derived(
    item?.media.filter((media) => media.approval_status === 'rejected').length ?? 0
  );
  const pendingMediaCount = $derived(
    item?.media.filter((media) => media.approval_status === 'under_review').length ?? 0
  );

  function scorePercent(value: number | null | undefined): string {
    if (value === null || value === undefined) return 'unscored';
    return `${Math.round(value * 100)}%`;
  }

  function mediaType(media: MediaAttachment): string | undefined {
    return media.content_type ?? media.media_type;
  }

  function downloadedFile(media: MediaAttachment): ItemFile | null {
    const prefix = String(media.sort_index).padStart(2, '0');
    return files.find((file) => file.filename.startsWith(prefix)) ?? null;
  }

  function mediaUrl(media: MediaAttachment): string {
    return downloadedFile(media)?.url ?? media.preview_url ?? media.download_url;
  }

  function mediaBusy(mediaId: number): boolean {
    return mediaActions[mediaId] !== undefined;
  }

  function reviewItemHref(): string {
    return `/?item_id=${encodeURIComponent(itemId)}`;
  }

  function reviewMediaHref(media: MediaAttachment): string {
    return `/?media_id=${media.id}`;
  }

  async function load(options: { quiet?: boolean } = {}) {
    if (!options.quiet) {
      loading = true;
    }
    errorMessage = null;
    try {
      item = await api.items.get(itemId);
      if (item.download_status === 'completed') {
        try {
          const response = await api.items.files(itemId);
          files = response.files;
        } catch {
          files = [];
        }
      } else {
        files = [];
      }
    } catch (e) {
      errorMessage = e instanceof Error ? e.message : 'Failed to load item';
    } finally {
      if (!options.quiet) {
        loading = false;
      }
    }
  }

  async function retryDownload() {
    actionLoading = true;
    errorMessage = null;
    try {
      item = await api.items.retryDownload(itemId);
      files = [];
    } catch (e) {
      errorMessage = e instanceof Error ? e.message : 'Retry failed';
    } finally {
      actionLoading = false;
    }
  }

  async function analyzeItem() {
    actionLoading = true;
    errorMessage = null;
    try {
      item = await api.items.analyze(itemId);
    } catch (e) {
      errorMessage = e instanceof Error ? e.message : 'Tagging failed';
    } finally {
      actionLoading = false;
    }
  }

  async function analyzeMedia(media: MediaAttachment) {
    mediaActions = { ...mediaActions, [media.id]: 'tagging' };
    errorMessage = null;
    try {
      await api.media.analyze(media.id);
      await load({ quiet: true });
    } catch (e) {
      errorMessage = e instanceof Error ? e.message : 'Tagging failed';
    } finally {
      const { [media.id]: _, ...rest } = mediaActions;
      mediaActions = rest;
    }
  }

  async function reopenRejectedMedia(media: MediaAttachment) {
    mediaActions = { ...mediaActions, [media.id]: 'reopening' };
    errorMessage = null;
    try {
      await api.media.reopen(media.id);
      await load({ quiet: true });
    } catch (e) {
      errorMessage = e instanceof Error ? e.message : 'Reopen failed';
      if (e instanceof ApiError && e.status === 409) {
        await load({ quiet: true });
      }
    } finally {
      const { [media.id]: _, ...rest } = mediaActions;
      mediaActions = rest;
    }
  }

  async function reopenRejectedItemMedia() {
    actionLoading = true;
    errorMessage = null;
    try {
      item = await api.items.reopenRejected(itemId);
      files = [];
    } catch (e) {
      errorMessage = e instanceof Error ? e.message : 'Reopen failed';
      if (e instanceof ApiError && e.status === 409) {
        await load({ quiet: true });
      }
    } finally {
      actionLoading = false;
    }
  }

  async function labelMedia(media: MediaAttachment, label: IllustrationLabel) {
    mediaActions = { ...mediaActions, [media.id]: 'labeling' };
    errorMessage = null;
    try {
      await api.media.update(media.id, { illustration_label: label });
      await load({ quiet: true });
    } catch (e) {
      errorMessage = e instanceof Error ? e.message : 'Label update failed';
    } finally {
      const { [media.id]: _, ...rest } = mediaActions;
      mediaActions = rest;
    }
  }

  onMount(() => {
    void load();
    return subscribeItemUpdated((event) => {
      if (event.item_id !== itemId || !item) return;
      item = {
        ...item,
        download_status: event.download_status,
        approval_status: event.approval_status,
      };
      if (terminalDownloadStatuses.has(event.download_status)) {
        void load({ quiet: true });
      }
    });
  });
</script>

{#if loading}
  <div class="page-header">
    <div>
      <p class="eyebrow">Source detail</p>
      <h1>Loading item</h1>
    </div>
  </div>
  <section class="panel">
    <div class="skeleton" style="height: 520px;"></div>
  </section>
{:else if errorMessage && !item}
  <EmptyState title="Item did not load" body={errorMessage} />
{:else if item}
  <div class="page-header">
    <div>
      <p class="eyebrow">Source detail</p>
      <h1>{item.title}</h1>
      <p>{communityLabel(item)} · {item.item_kind} · {item.media_count} file{item.media_count === 1 ? '' : 's'}</p>
    </div>
    <div class="metric-strip">
      <div class="metric">
        <strong>{item.media_approved_count}</strong>
        <span>kept</span>
      </div>
      <div class="metric">
        <strong>{item.media_under_review_count}</strong>
        <span>pending</span>
      </div>
      <div class="metric">
        <strong>{files.length}</strong>
        <span>downloaded files</span>
      </div>
    </div>
  </div>

  {#if errorMessage}
    <div class="notice" data-tone="danger">
      <CircleAlert size={16} />
      {errorMessage}
    </div>
  {/if}

  <section class="panel">
    <div class="panel-header">
      <h2>Provenance</h2>
      <span>{formatDate(item.created_at)}</span>
    </div>
    <dl class="detail-grid">
      <div>
        <dt>Source</dt>
        <dd><a class="link" href={item.source_url} target="_blank" rel="noreferrer">{item.source_url}</a></dd>
      </div>
      <div>
        <dt>Community</dt>
        <dd>{communityLabel(item)}</dd>
      </div>
      <div>
        <dt>Author</dt>
        <dd>{item.author_label ?? item.author_name ?? 'Unknown'}</dd>
      </div>
      <div>
        <dt>Status</dt>
        <dd>
          <span class="actions-row" style="margin-top: 0;">
            <StatusBadge value={item.approval_status} />
            <StatusBadge value={item.download_status} />
          </span>
        </dd>
      </div>
    </dl>
    <div class="actions-row settings-actions">
      {#if rejectedMediaCount > 0 && canChangeApproval}
        <button class="button" onclick={reopenRejectedItemMedia} disabled={actionLoading}>
          <RotateCcw size={16} />
          Reopen rejected
        </button>
      {/if}
      {#if pendingMediaCount > 0}
        <a class="button" data-tone="quiet" href={reviewItemHref()}>
          Review pending
        </a>
      {/if}
      {#if canRetry}
        <button class="button" onclick={retryDownload} disabled={actionLoading}>
          <RotateCcw size={16} />
          Retry download
        </button>
      {/if}
      <button class="button" data-tone="quiet" onclick={analyzeItem} disabled={actionLoading}>
        <Tags size={16} />
        Tag all
      </button>
      <a class="button" data-tone="quiet" href={item.source_url} target="_blank" rel="noreferrer">
        <ExternalLink size={16} />
        Open source
      </a>
    </div>
  </section>

  <section class="media-detail-grid">
    {#each item.media as media (media.id)}
      <article class="panel media-detail-card">
        <div class="media-detail-preview">
          {#if isVideoUrl(mediaUrl(media), mediaType(media))}
            <!-- svelte-ignore a11y_media_has_caption -->
            <video class="media-item" controls preload="metadata">
              <source src={mediaUrl(media)} type={mediaType(media)} />
            </video>
          {:else}
            <img
              class="media-item"
              src={mediaUrl(media)}
              alt={`${item.title} media ${media.sort_index + 1}`}
              loading="lazy"
              referrerpolicy="no-referrer"
            />
          {/if}
        </div>
        <div class="media-detail-body">
          <div class="panel-header">
            <h2>Media {media.sort_index + 1}</h2>
            <span>{media.width && media.height ? `${media.width}×${media.height}` : media.media_type}</span>
          </div>
          <div class="media-detail-content">
            <div class="actions-row" style="margin-top: 0;">
              <StatusBadge value={media.approval_status} />
              <StatusBadge value={media.illustration_label} />
              <span class="chip">score {scorePercent(media.analysis?.illustration_score)}</span>
            </div>
            <div class="actions-row">
              {#if media.approval_status === 'rejected' && canChangeApproval}
                <button
                  class="button"
                  disabled={mediaBusy(media.id)}
                  onclick={() => reopenRejectedMedia(media)}
                >
                  <RotateCcw size={16} />
                  Reopen
                </button>
              {/if}
              {#if media.approval_status === 'under_review' && canChangeApproval}
                <a class="button" data-tone="quiet" href={reviewMediaHref(media)}>
                  Review
                </a>
              {/if}
              <button
                class="button"
                data-tone="quiet"
                disabled={mediaBusy(media.id)}
                onclick={() => analyzeMedia(media)}
              >
                <Tags size={16} />
                {mediaActions[media.id] === 'tagging' ? 'Tagging' : 'Tag'}
              </button>
            </div>
            <div class="triage-section">
              <strong>Illustration label</strong>
              <div class="segmented-control">
                {#each labelOptions as option}
                  <button
                    class="button"
                    data-tone={media.illustration_label === option.value ? 'primary' : 'quiet'}
                    aria-pressed={media.illustration_label === option.value}
                    disabled={mediaBusy(media.id)}
                    onclick={() => labelMedia(media, option.value)}
                  >
                    {option.label}
                  </button>
                {/each}
              </div>
            </div>
            <MediaAnalysisPanel analysis={media.analysis} analyses={media.analyses} />
            <div class="detail-grid" style="padding: 0; grid-template-columns: 1fr;">
              <div>
                <dt>Download URL</dt>
                <dd><a class="link" href={media.download_url} target="_blank" rel="noreferrer">{media.download_url}</a></dd>
              </div>
            </div>
          </div>
        </div>
      </article>
    {/each}
  </section>
{/if}
