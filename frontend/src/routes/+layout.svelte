<script lang="ts">
  import { page } from '$app/stores';
  import type { Snippet } from 'svelte';
  import {
    Check,
    CircleAlert,
    Copy,
    Images,
    LayoutPanelLeft,
    ListChecks,
    RefreshCw,
    Settings,
    X,
  } from '@lucide/svelte';
  import '../app.css';
  import { api } from '$lib/api/client';
  import { formatDate, refreshSummary } from '$lib/format';
  import { connectEventStream, sseState } from '$lib/sse/store.svelte';
  import { onMount } from 'svelte';

  let { children }: { children: Snippet } = $props();

  let refreshLoading = $state(false);
  let refreshError = $state<string | null>(null);
  let showRefreshErrorDetails = $state(false);
  let copiedRefreshError = $state(false);
  let refreshErrorCopyFailed = $state(false);
  let copyResetTimer: ReturnType<typeof setTimeout> | null = null;

  const failedRun = $derived(
    sseState.latestRun?.status === 'failed' ? sseState.latestRun : null
  );

  async function startRefresh() {
    refreshLoading = true;
    refreshError = null;
    try {
      await api.refresh.start();
    } catch (e) {
      refreshError = e instanceof Error ? e.message : 'Refresh failed';
    } finally {
      refreshLoading = false;
    }
  }

  function closeRefreshErrorDetails() {
    showRefreshErrorDetails = false;
  }

  function refreshErrorText(error: string | null): string {
    return error || 'No error details were recorded';
  }

  function clearCopyResetTimer() {
    if (copyResetTimer !== null) {
      clearTimeout(copyResetTimer);
      copyResetTimer = null;
    }
  }

  async function copyFailedRunError() {
    if (!failedRun) return;
    refreshErrorCopyFailed = false;
    try {
      await navigator.clipboard.writeText(refreshErrorText(failedRun.error));
      copiedRefreshError = true;
      clearCopyResetTimer();
      copyResetTimer = setTimeout(() => {
        copiedRefreshError = false;
        copyResetTimer = null;
      }, 1600);
    } catch {
      copiedRefreshError = false;
      refreshErrorCopyFailed = true;
    }
  }

  onMount(() => {
    const disconnect = connectEventStream();
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        closeRefreshErrorDetails();
      }
    }
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('keydown', closeOnEscape);
      clearCopyResetTimer();
      disconnect();
    };
  });

  function isActive(href: string): boolean {
    const path = $page.url.pathname;
    return href === '/' ? path === '/' : path.startsWith(href);
  }
</script>

<div class="app-shell">
  <aside class="sidebar">
    <a class="brand" href="/">
      <span class="brand-mark"><LayoutPanelLeft size={17} /></span>
      <span>Upvote Monitor</span>
    </a>

    <nav class="nav-list" aria-label="Primary">
      <a class="nav-item" href="/" data-active={isActive('/')} title="Review">
        <ListChecks size={18} />
        <span>Review</span>
      </a>
      <a class="nav-item" href="/items" data-active={isActive('/items')} title="Items">
        <Images size={18} />
        <span>Items</span>
      </a>
      <a
        class="nav-item"
        href="/settings"
        data-active={isActive('/settings')}
        title="Settings"
      >
        <Settings size={18} />
        <span>Settings</span>
      </a>
    </nav>
  </aside>

  <div class="app-main">
    <header class="status-strip">
      <div class="status-stack">
        <span class="refresh-pill" data-running={sseState.refreshRunning}>
          <RefreshCw size={15} class={sseState.refreshRunning ? 'spin' : ''} />
          {sseState.refreshRunning ? 'Refreshing' : 'Ready'}
        </span>
        <span class="status-summary">{refreshSummary(sseState.latestRun)}</span>
        {#if failedRun}
          <button
            type="button"
            class="status-error-button"
            onclick={() => {
              showRefreshErrorDetails = true;
            }}
          >
            <CircleAlert size={14} />
            View error
          </button>
        {/if}
      </div>

      <div class="status-stack">
        {#if refreshError}
          <span class="status-error">
            <CircleAlert size={14} />
            {refreshError}
          </span>
        {/if}
        <button
          class="button"
          data-tone="primary"
          onclick={startRefresh}
          disabled={refreshLoading || sseState.refreshRunning}
          title="Start refresh"
        >
          <RefreshCw size={16} class={refreshLoading ? 'spin' : ''} />
          <span>{refreshLoading ? 'Starting' : 'Refresh'}</span>
        </button>
      </div>
    </header>

    <main class="content-shell" data-route={$page.url.pathname === '/' ? 'review' : 'standard'}>
      {@render children()}
    </main>
  </div>
</div>

{#if showRefreshErrorDetails && failedRun}
  <div class="modal-layer">
    <button
      type="button"
      class="modal-backdrop"
      aria-label="Close refresh error details"
      onclick={closeRefreshErrorDetails}
    ></button>
    <div
      class="modal-panel refresh-error-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="refresh-error-title"
    >
      <div class="modal-header">
        <div>
          <p class="eyebrow">Refresh</p>
          <h2 id="refresh-error-title">Last refresh failed</h2>
        </div>
        <div class="modal-actions">
          <button
            type="button"
            class="button"
            data-tone="quiet"
            onclick={copyFailedRunError}
          >
            {#if copiedRefreshError}
              <Check size={16} />
              <span>Copied</span>
            {:else}
              <Copy size={16} />
              <span>{refreshErrorCopyFailed ? 'Copy failed' : 'Copy'}</span>
            {/if}
          </button>
          <button
            type="button"
            class="icon-button"
            title="Close"
            onclick={closeRefreshErrorDetails}
          >
            <X size={16} />
          </button>
        </div>
      </div>
      <dl class="detail-grid">
        <div>
          <dt>Status</dt>
          <dd>{failedRun.status}</dd>
        </div>
        <div>
          <dt>Started</dt>
          <dd>{formatDate(failedRun.started_at)}</dd>
        </div>
        <div>
          <dt>Finished</dt>
          <dd>{formatDate(failedRun.finished_at)}</dd>
        </div>
        <div>
          <dt>Run id</dt>
          <dd>{failedRun.id}</dd>
        </div>
      </dl>
      <div class="error-block">
        {refreshErrorText(failedRun.error)}
      </div>
    </div>
  </div>
{/if}
