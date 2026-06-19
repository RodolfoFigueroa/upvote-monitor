<script lang="ts">
  import {
    ChevronDown,
    ChevronLeft,
    ChevronRight,
    CircleAlert,
    X,
  } from '@lucide/svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import { api } from '$lib/api/client';
  import { communityLabel, formatDate, formatRelative, statusLabel } from '$lib/format';
  import { subscribeReviewQueueChanged } from '$lib/sse/store.svelte';
  import type {
    ApprovalStatus,
    DownloadStatus,
    ItemSummary,
    SettingsResponse,
    SourceSettingsResponse,
  } from '$lib/types/api';
  import { onMount } from 'svelte';

  type SourceOption = {
    value: keyof SourceSettingsResponse;
    label: string;
  };

  const SOURCE_CATALOG: SourceOption[] = [
    { value: 'reddit', label: 'Reddit' },
    { value: 'x', label: 'X' },
  ];

  let items = $state<ItemSummary[]>([]);
  let total = $state(0);
  let loading = $state(true);
  let errorMessage = $state<string | null>(null);

  let draftApprovalStatus = $state<ApprovalStatus | ''>('');
  let draftDownloadStatus = $state<DownloadStatus | ''>('');
  let appliedApprovalStatus = $state<ApprovalStatus | ''>('');
  let appliedDownloadStatus = $state<DownloadStatus | ''>('');
  let sourceOptions = $state<SourceOption[]>([]);
  let sourceOptionsLoaded = $state(false);
  let draftSelectedSources = $state<string[]>([]);
  let appliedSelectedSources = $state<string[]>([]);
  let sourceMenuOpen = $state(false);
  let sourceMenuElement = $state<HTMLElement | null>(null);
  let draftCommunity = $state('');
  let draftAuthor = $state('');
  let appliedCommunity = $state('');
  let appliedAuthor = $state('');
  let offset = $state(0);
  const limit = 20;

  const pageStart = $derived(total === 0 ? 0 : offset + 1);
  const pageEnd = $derived(Math.min(offset + limit, total));
  const draftSelectedSourceLabels = $derived(draftSelectedSources.map(sourceDisplayLabel));
  const appliedSelectedSourceLabels = $derived(appliedSelectedSources.map(sourceDisplayLabel));
  const sourceButtonLabel = $derived(
    !sourceOptionsLoaded
      ? 'Loading'
      : sourceOptions.length === 0
        ? 'No enabled sources'
        : draftSelectedSources.length === 0
          ? 'Any'
          : draftSelectedSourceLabels.join(', ')
  );
  const hasAppliedFilters = $derived(
    Boolean(
      appliedApprovalStatus ||
        appliedDownloadStatus ||
        appliedSelectedSources.length > 0 ||
        appliedCommunity ||
        appliedAuthor
    )
  );
  const hasDraftFilters = $derived(
    Boolean(
      draftApprovalStatus ||
        draftDownloadStatus ||
        draftSelectedSources.length > 0 ||
        draftCommunity ||
        draftAuthor
    )
  );

  function enabledSourceOptions(settings: SettingsResponse): SourceOption[] {
    return SOURCE_CATALOG.filter((option) => settings.sources[option.value].enabled);
  }

  function sourceDisplayLabel(value: string): string {
    return (
      sourceOptions.find((option) => option.value === value)?.label ??
      value.charAt(0).toUpperCase() + value.slice(1)
    );
  }

  function filtersChanged() {
    return (
      appliedApprovalStatus !== draftApprovalStatus ||
      appliedDownloadStatus !== draftDownloadStatus ||
      appliedCommunity !== draftCommunity ||
      appliedAuthor !== draftAuthor ||
      appliedSelectedSources.length !== draftSelectedSources.length ||
      appliedSelectedSources.some((source, index) => source !== draftSelectedSources[index])
    );
  }

  async function loadSourceOptions() {
    try {
      sourceOptions = enabledSourceOptions(await api.settings.get());
      draftSelectedSources = draftSelectedSources.filter((sourceValue) =>
        sourceOptions.some((option) => option.value === sourceValue)
      );
      appliedSelectedSources = appliedSelectedSources.filter((sourceValue) =>
        sourceOptions.some((option) => option.value === sourceValue)
      );
    } catch {
      sourceOptions = [];
      draftSelectedSources = [];
      appliedSelectedSources = [];
    } finally {
      sourceOptionsLoaded = true;
    }
  }

  async function load(options: { quiet?: boolean } = {}) {
    if (!options.quiet) {
      loading = true;
    }
    errorMessage = null;
    try {
      const response = await api.items.list({
        approval_status: appliedApprovalStatus || undefined,
        download_status: appliedDownloadStatus || undefined,
        source: appliedSelectedSources.length > 0 ? appliedSelectedSources : undefined,
        community: appliedCommunity.trim() || undefined,
        author: appliedAuthor.trim() || undefined,
        limit,
        offset,
      });
      items = response.items;
      total = response.total;
    } catch (e) {
      errorMessage = e instanceof Error ? e.message : 'Failed to load items';
    } finally {
      if (!options.quiet) {
        loading = false;
      }
    }
  }

  function commitFilters() {
    if (!filtersChanged()) return;
    appliedApprovalStatus = draftApprovalStatus;
    appliedDownloadStatus = draftDownloadStatus;
    appliedSelectedSources = [...draftSelectedSources];
    appliedCommunity = draftCommunity;
    appliedAuthor = draftAuthor;
    offset = 0;
    void load();
  }

  function changeApprovalStatus(event: Event) {
    draftApprovalStatus = (event.currentTarget as HTMLSelectElement).value as
      | ApprovalStatus
      | '';
    commitFilters();
  }

  function changeDownloadStatus(event: Event) {
    draftDownloadStatus = (event.currentTarget as HTMLSelectElement).value as
      | DownloadStatus
      | '';
    commitFilters();
  }

  function clearFilters() {
    draftApprovalStatus = '';
    draftDownloadStatus = '';
    draftSelectedSources = [];
    draftCommunity = '';
    draftAuthor = '';
    appliedApprovalStatus = '';
    appliedDownloadStatus = '';
    appliedSelectedSources = [];
    appliedCommunity = '';
    appliedAuthor = '';
    sourceMenuOpen = false;
    offset = 0;
    void load();
  }

  function nextPage() {
    offset += limit;
    void load();
  }

  function previousPage() {
    offset = Math.max(0, offset - limit);
    void load();
  }

  function toggleSourceMenu() {
    if (!sourceOptionsLoaded || sourceOptions.length === 0) return;
    if (sourceMenuOpen) {
      sourceMenuOpen = false;
      commitFilters();
      return;
    }
    sourceMenuOpen = true;
  }

  function toggleSource(sourceValue: string) {
    if (draftSelectedSources.includes(sourceValue)) {
      draftSelectedSources = draftSelectedSources.filter((value) => value !== sourceValue);
    } else {
      draftSelectedSources = [...draftSelectedSources, sourceValue];
    }
  }

  function closeSourceMenuOnOutsideClick(event: MouseEvent) {
    if (
      sourceMenuElement &&
      event.target instanceof Node &&
      sourceMenuElement.contains(event.target)
    ) {
      return;
    }
    if (sourceMenuOpen) {
      sourceMenuOpen = false;
      commitFilters();
    }
  }

  onMount(() => {
    void (async () => {
      await loadSourceOptions();
      await load();
    })();
    document.addEventListener('click', closeSourceMenuOnOutsideClick);
    const unsubscribeReviewQueueChanged = subscribeReviewQueueChanged(() => {
      void load({ quiet: true });
    });
    return () => {
      document.removeEventListener('click', closeSourceMenuOnOutsideClick);
      unsubscribeReviewQueueChanged();
    };
  });
</script>

<div class="page-header">
  <div>
    <p class="eyebrow">Items</p>
    <h1>Browse the archive</h1>
    <p>Scan all discovered media by review and download state.</p>
  </div>
  <div class="metric-strip">
    <div class="metric">
      <strong>{total}</strong>
      <span>matching items</span>
    </div>
    <div class="metric">
      <strong>{pageStart}-{pageEnd}</strong>
      <span>visible range</span>
    </div>
  </div>
</div>

<div class="filter-bar">
  <div class="field">
    <span>Approval</span>
    <select class="select" value={draftApprovalStatus} onchange={changeApprovalStatus}>
      <option value="">Any</option>
      <option value="under_review">Under review</option>
      <option value="approved">Approved</option>
      <option value="rejected">Rejected</option>
    </select>
  </div>
  <div class="field">
    <span>Download</span>
    <select class="select" value={draftDownloadStatus} onchange={changeDownloadStatus}>
      <option value="">Any</option>
      <option value="pending">Pending</option>
      <option value="in_progress">In progress</option>
      <option value="completed">Completed</option>
      <option value="failed">Failed</option>
    </select>
  </div>
  <div class="field source-field">
    <span>Source</span>
    <div class="multi-select" bind:this={sourceMenuElement}>
      <button
        type="button"
        class="multi-select__button"
        aria-haspopup="listbox"
        aria-expanded={sourceMenuOpen}
        disabled={!sourceOptionsLoaded || sourceOptions.length === 0}
        onclick={toggleSourceMenu}
      >
        <span>{sourceButtonLabel}</span>
        <ChevronDown size={16} aria-hidden="true" />
      </button>
      {#if sourceMenuOpen}
        <div class="multi-select__menu" role="listbox" aria-multiselectable="true">
          {#each sourceOptions as option}
            <label class="multi-select__option">
              <input
                class="multi-select__checkbox"
                type="checkbox"
                checked={draftSelectedSources.includes(option.value)}
                onchange={() => toggleSource(option.value)}
              />
              <span>{option.label}</span>
            </label>
          {/each}
        </div>
      {/if}
    </div>
  </div>
  <div class="field">
    <span>Community</span>
    <input
      class="input"
      bind:value={draftCommunity}
      placeholder="pics"
      onblur={commitFilters}
      onkeydown={(event) => {
        if (event.key === 'Enter') commitFilters();
      }}
    />
  </div>
  <div class="field">
    <span>Author</span>
    <input
      class="input"
      bind:value={draftAuthor}
      placeholder="@handle"
      onblur={commitFilters}
      onkeydown={(event) => {
        if (event.key === 'Enter') commitFilters();
      }}
    />
  </div>
  <button
    class="button"
    data-tone="quiet"
    onclick={clearFilters}
    disabled={!hasAppliedFilters && !hasDraftFilters}
  >
    <X size={16} />
    Clear
  </button>
</div>

{#if hasAppliedFilters}
  <div class="chip-row">
    {#if appliedApprovalStatus}<span class="chip">approval: {statusLabel(appliedApprovalStatus)}</span>{/if}
    {#if appliedDownloadStatus}<span class="chip">download: {statusLabel(appliedDownloadStatus)}</span>{/if}
    {#if appliedSelectedSources.length > 0}
      <span class="chip">source: {appliedSelectedSourceLabels.join(', ')}</span>
    {/if}
    {#if appliedCommunity}<span class="chip">community: {appliedCommunity}</span>{/if}
    {#if appliedAuthor}<span class="chip">author: {appliedAuthor}</span>{/if}
  </div>
{/if}

{#if loading}
  <section class="panel item-table">
    <div class="item-row" data-head="true">
      <span>Item</span><span>Community</span><span>Approval</span><span>Download</span><span>Created</span>
    </div>
    {#each Array.from({ length: 8 }) as _}
      <div class="item-row">
        <div>
          <div class="skeleton" style="height: 18px; margin-bottom: 10px;"></div>
          <div class="skeleton" style="width: 60%; height: 13px;"></div>
        </div>
        <div class="skeleton" style="height: 18px;"></div>
        <div class="skeleton" style="height: 24px;"></div>
        <div class="skeleton" style="height: 24px;"></div>
        <div class="skeleton" style="height: 18px;"></div>
      </div>
    {/each}
  </section>
{:else if errorMessage}
  <div class="notice" data-tone="danger">
    <CircleAlert size={16} />
    {errorMessage}
  </div>
{:else if items.length === 0}
  <EmptyState
    title="No items match"
    body="Change the filters or run a refresh to discover more items."
  />
{:else}
  <section class="panel item-table">
    <div class="item-row" data-head="true">
      <span>Item</span>
      <span>Community</span>
      <span>Approval</span>
      <span>Download</span>
      <span>Created</span>
    </div>
    {#each items as item (item.id)}
      <div class="item-row">
        <div>
          <h2><a class="link" href="/items/{item.id}">{item.title}</a></h2>
          <div class="meta-line">
            <span>{item.source}</span>
            <span class="dot-separator"></span>
            <span>{item.item_kind}</span>
            <span class="dot-separator"></span>
            <span>{item.media_count} file{item.media_count === 1 ? '' : 's'}</span>
            <span class="dot-separator"></span>
            <span>found {formatRelative(item.discovered_at)}</span>
          </div>
        </div>
        <div class="meta-line">{communityLabel(item)}</div>
        <div><StatusBadge value={item.approval_status} /></div>
        <div><StatusBadge value={item.download_status} /></div>
        <div class="meta-line">{formatDate(item.created_at)}</div>
      </div>
    {/each}
  </section>

  <div class="pagination">
    <span>Showing {pageStart}-{pageEnd} of {total}</span>
    <div class="actions-row" style="margin-top: 0;">
      <button class="button" disabled={offset === 0} onclick={previousPage}>
        <ChevronLeft size={16} />
        Previous
      </button>
      <button class="button" disabled={offset + limit >= total} onclick={nextPage}>
        Next
        <ChevronRight size={16} />
      </button>
    </div>
  </div>
{/if}
