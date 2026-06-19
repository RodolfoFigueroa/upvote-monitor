<script lang="ts">
  import { Check, CircleAlert, Copy } from '@lucide/svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import { api } from '$lib/api/client';
  import { formatDate, formatRelative } from '$lib/format';
  import type { RefreshRunResponse } from '$lib/types/api';
  import { onMount } from 'svelte';

  let runs = $state<RefreshRunResponse[]>([]);
  let loading = $state(true);
  let errorMessage = $state<string | null>(null);
  let copiedRunId = $state<string | null>(null);
  let copyFailedRunId = $state<string | null>(null);
  let copyResetTimer: ReturnType<typeof setTimeout> | null = null;

  async function load() {
    loading = true;
    errorMessage = null;
    try {
      runs = await api.refresh.runs(20, 0);
    } catch (e) {
      errorMessage = e instanceof Error ? e.message : 'Failed to load refresh history';
    } finally {
      loading = false;
    }
  }

  function finishedLabel(run: RefreshRunResponse): string {
    return run.finished_at ? formatDate(run.finished_at) : 'Not finished';
  }

  function runErrorText(error: string | null): string {
    return error || 'No error details were recorded';
  }

  function clearCopyResetTimer() {
    if (copyResetTimer !== null) {
      clearTimeout(copyResetTimer);
      copyResetTimer = null;
    }
  }

  async function copyRunError(run: RefreshRunResponse) {
    copyFailedRunId = null;
    try {
      await navigator.clipboard.writeText(runErrorText(run.error));
      copiedRunId = run.id;
      clearCopyResetTimer();
      copyResetTimer = setTimeout(() => {
        copiedRunId = null;
        copyResetTimer = null;
      }, 1600);
    } catch {
      copiedRunId = null;
      copyFailedRunId = run.id;
    }
  }

  onMount(() => {
    void load();
    return clearCopyResetTimer;
  });
</script>

{#if loading}
  <section class="panel settings-form-page">
    <div class="panel-header"><h2>Refresh history</h2></div>
    <div class="refresh-run-list">
      {#each Array.from({ length: 6 }) as _}
        <div class="refresh-run-row">
          <div class="skeleton" style="height: 24px;"></div>
          <div class="skeleton" style="height: 34px;"></div>
          <div class="skeleton" style="height: 34px;"></div>
          <div class="skeleton" style="height: 34px;"></div>
        </div>
      {/each}
    </div>
  </section>
{:else if errorMessage}
  <EmptyState title="Refresh history did not load" body={errorMessage} />
{:else if runs.length === 0}
  <EmptyState
    title="No refresh runs yet"
    body="Refresh activity will appear here after the first run starts."
  />
{:else}
  <section class="panel settings-form-page refresh-runs-panel">
    <div class="panel-header">
      <h2>Refresh history</h2>
      <span>{runs.length} recent run{runs.length === 1 ? '' : 's'}</span>
    </div>
    <div class="refresh-run-list">
      <div class="refresh-run-row" data-head="true">
        <span>Status</span>
        <span>Started</span>
        <span>Items</span>
        <span>Downloads</span>
      </div>
      {#each runs as run (run.id)}
        <div class="refresh-run-entry">
          <div class="refresh-run-row">
            <div>
              <StatusBadge value={run.status} />
              <div class="meta-line refresh-run-id">Run {run.id}</div>
            </div>
            <div>
              <strong>{formatDate(run.started_at)}</strong>
              <div class="meta-line">
                <span>{formatRelative(run.started_at)}</span>
                <span class="dot-separator"></span>
                <span>finished {finishedLabel(run)}</span>
              </div>
            </div>
            <div>
              <strong>{run.new_items} new</strong>
              <div class="meta-line">{run.skipped} skipped</div>
            </div>
            <div>
              <strong>{run.downloads_triggered} triggered</strong>
              <div class="meta-line">{run.downloads_failed} failed</div>
            </div>
          </div>
          {#if run.status === 'failed'}
            <div class="refresh-run-error">
              <CircleAlert size={16} />
              <span class="refresh-run-error__message">{runErrorText(run.error)}</span>
              <button
                type="button"
                class="button"
                data-tone="quiet"
                onclick={() => copyRunError(run)}
              >
                {#if copiedRunId === run.id}
                  <Check size={16} />
                  Copied
                {:else}
                  <Copy size={16} />
                  {copyFailedRunId === run.id ? 'Copy failed' : 'Copy'}
                {/if}
              </button>
            </div>
          {/if}
        </div>
      {/each}
    </div>
  </section>
{/if}
