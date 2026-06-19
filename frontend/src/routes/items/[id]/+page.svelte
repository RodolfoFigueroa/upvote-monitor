<script lang="ts">
  import { page } from '$app/stores';
  import {
    Check,
    CircleAlert,
    Download,
    ExternalLink,
    RotateCcw,
    X,
  } from '@lucide/svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import MediaPreview from '$lib/components/MediaPreview.svelte';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import { api } from '$lib/api/client';
  import { communityLabel, formatDate, sourceLabel } from '$lib/format';
  import { subscribeItemUpdated } from '$lib/sse/store.svelte';
  import type { DownloadStatus, ItemDetail, ItemFile } from '$lib/types/api';
  import { onMount } from 'svelte';

  let item = $state<ItemDetail | null>(null);
  let files = $state<ItemFile[]>([]);
  let loading = $state(true);
  let actionLoading = $state(false);
  let errorMessage = $state<string | null>(null);

  const itemId = $derived($page.params.id ?? '');
  const terminalDownloadStatuses = new Set<DownloadStatus>(['completed', 'failed']);
  const canRetry = $derived(
    item?.approval_status === 'approved' &&
      (item.download_status === 'failed' || item.download_status === 'pending')
  );

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

  async function approve() {
    actionLoading = true;
    errorMessage = null;
    try {
      item = await api.items.approve(itemId);
      files = [];
    } catch (e) {
      errorMessage = e instanceof Error ? e.message : 'Approve failed';
    } finally {
      actionLoading = false;
    }
  }

  async function reject() {
    actionLoading = true;
    errorMessage = null;
    try {
      item = await api.items.reject(itemId);
      files = [];
    } catch (e) {
      errorMessage = e instanceof Error ? e.message : 'Reject failed';
    } finally {
      actionLoading = false;
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
      <p class="eyebrow">Item detail</p>
      <h1>Loading item</h1>
    </div>
  </div>
  <section class="panel decision-panel">
    <div class="decision-layout">
      <div class="media-stage">
        <div class="skeleton" style="height: 520px;"></div>
      </div>
      <aside class="side-panel">
        <div class="skeleton" style="height: 24px; margin-bottom: 12px;"></div>
        <div class="skeleton" style="height: 14px; margin-bottom: 18px;"></div>
        <div class="skeleton" style="height: 36px;"></div>
      </aside>
    </div>
  </section>
{:else if errorMessage && !item}
  <EmptyState title="Item did not load" body={errorMessage} />
{:else if item}
  <div class="page-header">
    <div>
      <p class="eyebrow">Item detail</p>
      <h1>{item.title}</h1>
      <p>{communityLabel(item)} · {item.item_kind} · {item.media_count} file{item.media_count === 1 ? '' : 's'}</p>
    </div>
    <div class="metric-strip">
      <div class="metric">
        <strong>{files.length}</strong>
        <span>downloaded files</span>
      </div>
      <div class="metric">
        <strong>{formatDate(item.created_at)}</strong>
        <span>created</span>
      </div>
    </div>
  </div>

  {#if errorMessage}
    <div class="notice" data-tone="danger">
      <CircleAlert size={16} />
      {errorMessage}
    </div>
  {/if}

  <section class="panel decision-panel">
    <div class="decision-layout">
      <div class="media-stage">
        <MediaPreview {item} {files} />
      </div>
      <aside class="side-panel">
        <h2>Status</h2>
        <div class="actions-row">
          <StatusBadge value={item.approval_status} />
          <StatusBadge value={item.download_status} />
        </div>

        <div class="actions-row">
          <button
            class="button"
            data-tone="primary"
            onclick={approve}
            disabled={actionLoading}
          >
            <Check size={16} />
            Approve
          </button>
          <button
            class="button"
            data-tone="danger"
            onclick={reject}
            disabled={actionLoading}
          >
            <X size={16} />
            Reject
          </button>
          {#if canRetry}
            <button class="button" onclick={retryDownload} disabled={actionLoading}>
              <RotateCcw size={16} />
              Retry
            </button>
          {/if}
        </div>

        <div class="actions-row">
          <a
            class="button"
            data-tone="quiet"
            href={item.source_url}
            target="_blank"
            rel="noreferrer"
          >
            <ExternalLink size={16} />
            {sourceLabel(item)}
          </a>
        </div>

        <div class="notice" style="margin-top: 16px;">
          <Download size={16} />
          Downloaded {formatDate(item.downloaded_at)}
        </div>

        {#if item.download_error}
          <div class="notice" data-tone="danger" style="margin-top: 10px;">
            <CircleAlert size={16} />
            {item.download_error}
          </div>
        {/if}
      </aside>
    </div>
  </section>
{/if}
