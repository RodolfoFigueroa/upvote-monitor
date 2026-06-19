<script lang="ts">
  import {
    Ban,
    Check,
    ChevronDown,
    CircleAlert,
    ExternalLink,
    Inbox,
    X,
  } from '@lucide/svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import MediaPreview from '$lib/components/MediaPreview.svelte';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import { api } from '$lib/api/client';
  import { communityLabel, formatRelative, sourceLabel, statusLabel } from '$lib/format';
  import { subscribeReviewQueueChanged } from '$lib/sse/store.svelte';
  import type {
    DownloadStatus,
    ItemDetail,
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
  let details = $state<Record<string, ItemDetail>>({});
  let detailLoading = $state<Record<string, boolean>>({});
  let pendingActions = $state<Record<string, string>>({});
  let selectedId = $state<string | null>(null);
  let loading = $state(true);
  let errorMessage = $state<string | null>(null);
  let actionError = $state<string | null>(null);
  let draftDownloadStatus = $state<DownloadStatus | ''>('');
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

  const selectedSummary = $derived(
    selectedId ? items.find((item) => item.id === selectedId) ?? null : null
  );
  const selectedItem = $derived(
    selectedId ? details[selectedId] ?? selectedSummary : null
  );
  const selectedIsLoading = $derived(
    selectedId ? detailLoading[selectedId] === true : false
  );
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
      appliedDownloadStatus ||
        appliedSelectedSources.length > 0 ||
        appliedCommunity ||
        appliedAuthor
    )
  );
  const hasDraftFilters = $derived(
    Boolean(
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
        approval_status: 'under_review',
        download_status: appliedDownloadStatus || undefined,
        source: appliedSelectedSources.length > 0 ? appliedSelectedSources : undefined,
        community: appliedCommunity.trim() || undefined,
        author: appliedAuthor.trim() || undefined,
        limit: 50,
      });
      const availableItems = response.items.filter(
        (item) => pendingActions[item.id] === undefined
      );
      items = availableItems;
      if (!selectedId || !availableItems.some((item) => item.id === selectedId)) {
        selectedId = availableItems[0]?.id ?? null;
      }
      if (selectedId) {
        void hydrateDetail(selectedId);
      }
    } catch (e) {
      errorMessage = e instanceof Error ? e.message : 'Failed to load review queue';
    } finally {
      if (!options.quiet) {
        loading = false;
      }
    }
  }

  async function hydrateDetail(itemId: string) {
    if (details[itemId] || detailLoading[itemId]) return;
    detailLoading = { ...detailLoading, [itemId]: true };
    try {
      const detail = await api.items.get(itemId);
      details = { ...details, [itemId]: detail };
    } catch {
      // The summary remains usable if detail hydration fails.
    } finally {
      detailLoading = { ...detailLoading, [itemId]: false };
    }
  }

  function commitFilters() {
    if (!filtersChanged()) return;
    appliedDownloadStatus = draftDownloadStatus;
    appliedSelectedSources = [...draftSelectedSources];
    appliedCommunity = draftCommunity;
    appliedAuthor = draftAuthor;
    void load();
  }

  function changeDownloadStatus(event: Event) {
    draftDownloadStatus = (event.currentTarget as HTMLSelectElement).value as
      | DownloadStatus
      | '';
    commitFilters();
  }

  function clearFilters() {
    draftDownloadStatus = '';
    draftSelectedSources = [];
    draftCommunity = '';
    draftAuthor = '';
    appliedDownloadStatus = '';
    appliedSelectedSources = [];
    appliedCommunity = '';
    appliedAuthor = '';
    sourceMenuOpen = false;
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

  function selectItem(itemId: string) {
    selectedId = itemId;
    void hydrateDetail(itemId);
  }

  function removeOptimistically(itemId: string) {
    const index = items.findIndex((item) => item.id === itemId);
    items = items.filter((item) => item.id !== itemId);
    if (selectedId === itemId) {
      selectedId = items[index]?.id ?? items[index - 1]?.id ?? null;
      if (selectedId) {
        void hydrateDetail(selectedId);
      }
    }
  }

  function communityBlacklistRuleForItem(item: ItemSummary | ItemDetail | undefined) {
    if (item?.community_name) {
      return {
        source: item.source,
        target_type: 'community' as const,
        target_value: item.community_name,
      };
    }
    return null;
  }

  function authorBlacklistRuleForItem(item: ItemSummary | ItemDetail | undefined) {
    if (item?.author_name) {
      return {
        source: item.source,
        target_type: 'author' as const,
        target_value: item.author_name,
      };
    }
    return null;
  }

  async function actOnItem(
    itemId: string,
    action: 'approve' | 'reject' | 'reject_blacklist_community' | 'reject_blacklist_author'
  ) {
    const previousItems = items;
    const previousSelected = selectedId;
    actionError = null;
    pendingActions = { ...pendingActions, [itemId]: action };
    removeOptimistically(itemId);

    try {
      if (action === 'approve') {
        await api.items.approve(itemId);
      } else {
        await api.items.reject(itemId);
        if (action === 'reject_blacklist_community' || action === 'reject_blacklist_author') {
          const item = previousItems.find((candidate) => candidate.id === itemId);
          const rule =
            action === 'reject_blacklist_community'
              ? communityBlacklistRuleForItem(item)
              : authorBlacklistRuleForItem(item);
          if (rule) {
            await api.rules.addBlacklist(rule);
          }
        }
      }
      await load({ quiet: true });
    } catch (e) {
      items = previousItems;
      selectedId = previousSelected;
      actionError = e instanceof Error ? e.message : 'Action failed';
    } finally {
      const { [itemId]: _, ...rest } = pendingActions;
      pendingActions = rest;
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

<div class="review-page">
<div class="page-header">
  <div>
    <p class="eyebrow">Review queue</p>
    <h1>Decide what gets downloaded</h1>
    <p>Fast summaries first, richer media only when an item is selected.</p>
  </div>
  <div class="metric-strip">
    <div class="metric">
      <strong>{items.length}</strong>
      <span>awaiting decision</span>
    </div>
    <div class="metric">
      <strong>{Object.keys(pendingActions).length}</strong>
      <span>in flight</span>
    </div>
  </div>
</div>

<div class="filter-bar">
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
    {#if appliedDownloadStatus}<span class="chip">download: {statusLabel(appliedDownloadStatus)}</span>{/if}
    {#if appliedSelectedSources.length > 0}
      <span class="chip">source: {appliedSelectedSourceLabels.join(', ')}</span>
    {/if}
    {#if appliedCommunity}<span class="chip">community: {appliedCommunity}</span>{/if}
    {#if appliedAuthor}<span class="chip">author: {appliedAuthor}</span>{/if}
  </div>
{/if}

{#if actionError}
  <div class="notice" data-tone="danger">
    <CircleAlert size={16} />
    {actionError}
  </div>
{/if}

{#if loading}
  <div class="work-grid">
    <section class="panel queue-panel">
      <div class="panel-header">
        <h2>Queue</h2>
        <span>Loading</span>
      </div>
      <div class="queue-list">
        {#each Array.from({ length: 6 }) as _}
          <div class="queue-item">
            <div class="skeleton" style="width: 76px; height: 64px;"></div>
            <div>
              <div class="skeleton" style="height: 18px; margin-bottom: 10px;"></div>
              <div class="skeleton" style="width: 70%; height: 14px;"></div>
            </div>
          </div>
        {/each}
      </div>
    </section>
    <section class="panel decision-panel">
      <div class="media-stage">
        <div class="skeleton" style="height: 420px;"></div>
      </div>
    </section>
  </div>
{:else if errorMessage}
  <EmptyState title="Review queue did not load" body={errorMessage} />
{:else if items.length === 0}
  <EmptyState
    title="Nothing needs review"
    body="New under-review items will appear here after the next refresh."
  >
    <Inbox size={22} />
  </EmptyState>
{:else}
  <div class="work-grid">
    <section class="panel queue-panel">
      <div class="panel-header">
        <h2>Queue</h2>
        <span>{items.length} pending</span>
      </div>
      <div class="queue-list">
        {#each items as item (item.id)}
          <button
            class="queue-item"
            data-active={selectedId === item.id}
            onclick={() => selectItem(item.id)}
          >
            <MediaPreview {item} compact />
            <div>
              <h2 class="queue-title">{item.title}</h2>
              <div class="meta-line">
                <span>{communityLabel(item)}</span>
                <span class="dot-separator"></span>
                <span>{item.media_count} file{item.media_count === 1 ? '' : 's'}</span>
              </div>
              <div class="meta-line" style="margin-top: 8px;">
                <StatusBadge value={item.download_status} />
              </div>
            </div>
          </button>
        {/each}
      </div>
    </section>

    <section class="panel decision-panel">
      {#if selectedItem}
        <div class="decision-layout">
          <div class="media-stage">
            <MediaPreview item={selectedItem} />
          </div>
          <aside class="side-panel">
            <h2>{selectedItem.title}</h2>
            <p>
              {communityLabel(selectedItem)} · {selectedItem.item_kind} · discovered
              {formatRelative(selectedItem.discovered_at)}
            </p>
            <div class="actions-row">
              <StatusBadge value={selectedItem.approval_status} />
              <StatusBadge value={selectedItem.download_status} />
            </div>
            {#if selectedIsLoading}
              <div class="notice" style="margin-top: 14px;">Loading full item data</div>
            {/if}
            <div class="actions-row">
              <button
                class="button"
                data-tone="primary"
                disabled={pendingActions[selectedItem.id] !== undefined}
                onclick={() => actOnItem(selectedItem.id, 'approve')}
              >
                <Check size={16} />
                Approve
              </button>
              <button
                class="button"
                data-tone="danger"
                disabled={pendingActions[selectedItem.id] !== undefined}
                onclick={() => actOnItem(selectedItem.id, 'reject')}
              >
                <X size={16} />
                Reject
              </button>
              {#if selectedItem.community_name}
                <button
                  class="button"
                  data-tone="warning"
                  disabled={pendingActions[selectedItem.id] !== undefined}
                  onclick={() => actOnItem(selectedItem.id, 'reject_blacklist_community')}
                >
                  <Ban size={16} />
                  Blacklist Community
                </button>
              {/if}
              {#if selectedItem.author_name}
                <button
                  class="button"
                  data-tone="warning"
                  disabled={pendingActions[selectedItem.id] !== undefined}
                  onclick={() => actOnItem(selectedItem.id, 'reject_blacklist_author')}
                >
                  <Ban size={16} />
                  Blacklist Author
                </button>
              {/if}
            </div>
            <div class="actions-row">
              <a
                class="button"
                data-tone="quiet"
                href={selectedItem.source_url}
                target="_blank"
                rel="noreferrer"
              >
                <ExternalLink size={16} />
                {sourceLabel(selectedItem)}
              </a>
            </div>
          </aside>
        </div>
      {/if}
    </section>
  </div>
{/if}
</div>
