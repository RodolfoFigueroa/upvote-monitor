<script lang="ts">
  import { page } from '$app/stores';
  import {
    Check,
    CircleAlert,
    RotateCcw,
    Tags,
    X,
  } from '@lucide/svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import ItemDecisionPanel from '$lib/components/ItemDecisionPanel.svelte';
  import { api } from '$lib/api/client';
  import { communityLabel, formatDate } from '$lib/format';
  import { subscribeItemUpdated } from '$lib/sse/store.svelte';
  import type { DownloadStatus, ItemDetail, ItemFile } from '$lib/types/api';
  import { onMount } from 'svelte';

  let item = $state<ItemDetail | null>(null);
  let files = $state<ItemFile[]>([]);
  let loading = $state(true);
  let actionLoading = $state(false);
  let taggingLoading = $state(false);
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

  async function analyze() {
    taggingLoading = true;
    errorMessage = null;
    try {
      item = await api.items.analyze(itemId);
    } catch (e) {
      errorMessage = e instanceof Error ? e.message : 'Tagging failed';
    } finally {
      taggingLoading = false;
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
    <ItemDecisionPanel
      {item}
      detail={item}
      {files}
      heading="Status"
      showDownloaded
      showDownloadError
    >
      {#snippet actions()}
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
        <button
          class="button"
          data-tone="quiet"
          onclick={analyze}
          disabled={taggingLoading}
        >
          <Tags size={16} />
          {taggingLoading ? 'Tagging' : 'Tag'}
        </button>
      {/snippet}
    </ItemDecisionPanel>
  </section>
{/if}
