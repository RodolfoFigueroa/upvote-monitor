<script lang="ts">
  import { page } from '$app/stores';
  import {
    Check,
    ChevronDown,
    CircleAlert,
    ExternalLink,
    Inbox,
    RefreshCw,
    Tags,
    X,
  } from '@lucide/svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import MediaAnalysisPanel from '$lib/components/MediaAnalysisPanel.svelte';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import { api } from '$lib/api/client';
  import { formatRelative, isVideoUrl, statusLabel } from '$lib/format';
  import { subscribeReviewQueueChanged } from '$lib/sse/store.svelte';
  import type {
    DownloadStatus,
    IllustrationLabel,
    MediaItem,
    ReviewQueueChangedEvent,
    SettingsResponse,
    SourceSettingsResponse,
  } from '$lib/types/api';
  import { onMount } from 'svelte';

  type SourceOption = {
    value: keyof SourceSettingsResponse;
    label: string;
  };
  type DecisionStatus = 'approved' | 'rejected';
  type UndoNotice = {
    media: MediaItem;
    status: DecisionStatus;
  };

  const SOURCE_CATALOG: SourceOption[] = [
    { value: 'reddit', label: 'Reddit' },
    { value: 'x', label: 'X' },
  ];

  const labelOptions: { value: IllustrationLabel; label: string }[] = [
    { value: 'yes', label: 'Yes' },
    { value: 'no', label: 'No' },
    { value: 'unsure', label: 'Unsure' },
  ];

  const VISIBLE_LIMIT = 100;
  const BUFFER_TARGET = 20;
  const BUFFER_REFILL_THRESHOLD = 5;
  const INITIAL_FETCH_LIMIT = VISIBLE_LIMIT + BUFFER_TARGET;
  const LABEL_DRAFT_STORAGE_KEY = 'upvote-monitor.triage-labels.v1';

  let media = $state<MediaItem[]>([]);
  let mediaBuffer = $state<MediaItem[]>([]);
  let nextCursor = $state<string | null>(null);
  let selectedId = $state<number | null>(null);
  let loading = $state(true);
  let refillingBuffer = $state(false);
  let queueChanged = $state(false);
  let errorMessage = $state<string | null>(null);
  let actionError = $state<string | null>(null);
  let pendingActions = $state<Record<number, string>>({});
  let draftLabels = $state<Record<number, IllustrationLabel>>({});
  let taggingActions = $state<Record<number, boolean>>({});
  let undoNotice = $state<UndoNotice | null>(null);
  let undoTimer: number | null = null;
  let decidedMediaIds = new Set<number>();

  let draftDownloadStatus = $state<DownloadStatus | ''>('');
  let appliedDownloadStatus = $state<DownloadStatus | ''>('');
  let draftIllustrationLabel = $state<IllustrationLabel | ''>('');
  let appliedIllustrationLabel = $state<IllustrationLabel | ''>('');
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
  let routeItemId = $state<string | null>(null);
  let routeMediaId = $state<number | null>(null);

  const selectedMedia = $derived(
    selectedId ? media.find((item) => item.id === selectedId) ?? null : null
  );
  const inFlightActionCount = $derived(
    Object.keys(pendingActions).length +
      Object.values(taggingActions).filter(Boolean).length +
      (refillingBuffer ? 1 : 0)
  );
  const queueSummary = $derived(
    mediaBuffer.length > 0
      ? `${media.length} visible, ${mediaBuffer.length} buffered`
      : `${media.length} pending`
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
        appliedIllustrationLabel ||
        appliedSelectedSources.length > 0 ||
        appliedCommunity ||
        appliedAuthor ||
        routeItemId ||
        routeMediaId
    )
  );
  const hasDraftFilters = $derived(
    Boolean(
      draftDownloadStatus ||
        draftIllustrationLabel ||
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

  function sourceLabel(value: MediaItem): string {
    return value.source.charAt(0).toUpperCase() + value.source.slice(1);
  }

  function communityLabel(value: MediaItem): string {
    return value.community_label ?? value.author_label ?? sourceLabel(value);
  }

  function mediaUrl(value: MediaItem): string {
    return value.preview_url ?? value.download_url;
  }

  function mediaType(value: MediaItem): string | undefined {
    return value.content_type ?? value.media_type;
  }

  function scorePercent(value: number | null | undefined): string {
    if (value === null || value === undefined) return 'unscored';
    return `${Math.round(value * 100)}%`;
  }

  function isIllustrationLabel(value: unknown): value is IllustrationLabel {
    return value === 'unlabeled' || value === 'yes' || value === 'no' || value === 'unsure';
  }

  function loadDraftLabels() {
    if (typeof window === 'undefined') return {};
    try {
      const raw = window.sessionStorage.getItem(LABEL_DRAFT_STORAGE_KEY);
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object') return {};

      const result: Record<number, IllustrationLabel> = {};
      for (const [id, value] of Object.entries(parsed)) {
        const mediaId = Number(id);
        if (Number.isInteger(mediaId) && isIllustrationLabel(value)) {
          result[mediaId] = value;
        }
      }
      return result;
    } catch {
      return {};
    }
  }

  function saveDraftLabels(nextDraftLabels: Record<number, IllustrationLabel>) {
    if (typeof window === 'undefined') return;
    if (Object.keys(nextDraftLabels).length === 0) {
      window.sessionStorage.removeItem(LABEL_DRAFT_STORAGE_KEY);
      return;
    }
    window.sessionStorage.setItem(
      LABEL_DRAFT_STORAGE_KEY,
      JSON.stringify(nextDraftLabels)
    );
  }

  function setDraftLabel(mediaId: number, label: IllustrationLabel) {
    const nextDraftLabels = { ...draftLabels, [mediaId]: label };
    draftLabels = nextDraftLabels;
    saveDraftLabels(nextDraftLabels);
  }

  function clearDraftLabel(mediaId: number) {
    const { [mediaId]: _, ...rest } = draftLabels;
    draftLabels = rest;
    saveDraftLabels(rest);
  }

  function loadRouteFilters() {
    const mediaParam = $page.url.searchParams.get('media_id');
    const parsedMediaId = mediaParam === null ? Number.NaN : Number(mediaParam);
    routeMediaId = Number.isInteger(parsedMediaId) ? parsedMediaId : null;
    routeItemId = $page.url.searchParams.get('item_id') || null;
  }

  function clearRouteFilters() {
    routeItemId = null;
    routeMediaId = null;
    if (typeof window !== 'undefined' && window.location.search) {
      window.history.replaceState({}, '', window.location.pathname);
    }
  }

  function clearUndoTimer() {
    if (undoTimer !== null) {
      clearTimeout(undoTimer);
      undoTimer = null;
    }
  }

  function dismissUndoNotice() {
    clearUndoTimer();
    undoNotice = null;
  }

  function showUndoNotice(mediaItem: MediaItem, status: DecisionStatus) {
    dismissUndoNotice();
    undoNotice = { media: mediaItem, status };
    if (typeof window !== 'undefined') {
      undoTimer = window.setTimeout(() => {
        undoNotice = null;
        undoTimer = null;
      }, 8000);
    }
  }

  async function undoLastDecision() {
    const notice = undoNotice;
    if (notice === null) return;

    dismissUndoNotice();
    actionError = null;
    pendingActions = { ...pendingActions, [notice.media.id]: 'undo' };

    try {
      await api.media.reopen(notice.media.id);
      decidedMediaIds = new Set(decidedMediaIds);
      decidedMediaIds.delete(notice.media.id);
      await load({ quiet: true });
    } catch (e) {
      actionError = e instanceof Error ? e.message : 'Undo failed';
    } finally {
      const { [notice.media.id]: _, ...rest } = pendingActions;
      pendingActions = rest;
    }
  }

  function localLabel(item: MediaItem): IllustrationLabel {
    return draftLabels[item.id] ?? item.illustration_label;
  }

  function applyDraftLabel(item: MediaItem): MediaItem {
    const label = draftLabels[item.id];
    return label === undefined ? item : { ...item, illustration_label: label };
  }

  function patchMediaInQueues(mediaId: number, patch: Partial<MediaItem>) {
    media = media.map((item) => (item.id === mediaId ? { ...item, ...patch } : item));
    mediaBuffer = mediaBuffer.map((item) =>
      item.id === mediaId ? { ...item, ...patch } : item
    );
  }

  function fetchedMedia(
    items: MediaItem[],
    knownIds = new Set<number>(),
  ): MediaItem[] {
    const result: MediaItem[] = [];
    for (const item of items) {
      if (
        knownIds.has(item.id) ||
        decidedMediaIds.has(item.id) ||
        pendingActions[item.id] !== undefined
      ) {
        continue;
      }
      knownIds.add(item.id);
      result.push(applyDraftLabel(item));
    }
    return result;
  }

  function listParams(limit: number, cursor?: string | null) {
    return {
      approval_status: 'under_review' as const,
      illustration_label: appliedIllustrationLabel || undefined,
      download_status: appliedDownloadStatus || undefined,
      item_id: routeItemId ?? undefined,
      media_id: routeMediaId ?? undefined,
      source: appliedSelectedSources.length > 0 ? appliedSelectedSources : undefined,
      community: appliedCommunity.trim() || undefined,
      author: appliedAuthor.trim() || undefined,
      limit,
      cursor: cursor ?? undefined,
    };
  }

  function selectAfterQueueChange(
    previousSelectedId: number | null,
    previousSelectedIndex: number,
  ) {
    if (
      previousSelectedId &&
      media.some((item) => item.id === previousSelectedId)
    ) {
      selectedId = previousSelectedId;
    } else if (previousSelectedIndex >= 0) {
      selectedId =
        media[
          Math.min(previousSelectedIndex, Math.max(media.length - 1, 0))
        ]?.id ?? null;
    } else {
      selectedId = media[0]?.id ?? null;
    }
  }

  function filtersChanged() {
    return (
      appliedDownloadStatus !== draftDownloadStatus ||
      appliedIllustrationLabel !== draftIllustrationLabel ||
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
      const previousSelectedId = selectedId;
      const previousSelectedIndex = previousSelectedId
        ? media.findIndex((item) => item.id === previousSelectedId)
        : -1;
      decidedMediaIds = new Set();

      const response = await api.media.list(listParams(INITIAL_FETCH_LIMIT));
      const availableMedia = fetchedMedia(response.media);
      media = availableMedia.slice(0, VISIBLE_LIMIT);
      mediaBuffer = availableMedia.slice(VISIBLE_LIMIT);
      nextCursor = response.next_cursor;
      queueChanged = false;
      selectAfterQueueChange(previousSelectedId, previousSelectedIndex);
    } catch (e) {
      errorMessage = e instanceof Error ? e.message : 'Failed to load triage queue';
    } finally {
      if (!options.quiet) {
        loading = false;
      }
    }
  }

  function commitFilters() {
    if (!filtersChanged()) return;
    appliedDownloadStatus = draftDownloadStatus;
    appliedIllustrationLabel = draftIllustrationLabel;
    appliedSelectedSources = [...draftSelectedSources];
    appliedCommunity = draftCommunity;
    appliedAuthor = draftAuthor;
    void load();
  }

  function clearFilters() {
    draftDownloadStatus = '';
    draftIllustrationLabel = '';
    draftSelectedSources = [];
    draftCommunity = '';
    draftAuthor = '';
    appliedDownloadStatus = '';
    appliedIllustrationLabel = '';
    appliedSelectedSources = [];
    appliedCommunity = '';
    appliedAuthor = '';
    clearRouteFilters();
    sourceMenuOpen = false;
    void load();
  }

  function manualRefresh() {
    void load();
  }

  function changeDownloadStatus(event: Event) {
    draftDownloadStatus = (event.currentTarget as HTMLSelectElement).value as
      | DownloadStatus
      | '';
    commitFilters();
  }

  function changeIllustrationLabel(event: Event) {
    draftIllustrationLabel = (event.currentTarget as HTMLSelectElement).value as
      | IllustrationLabel
      | '';
    commitFilters();
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

  function selectMedia(mediaId: number) {
    selectedId = mediaId;
  }

  function itemBusy(mediaId: number): boolean {
    return decisionBusy(mediaId) || taggingActions[mediaId] === true;
  }

  function decisionBusy(mediaId: number): boolean {
    return pendingActions[mediaId] !== undefined;
  }

  function labelTarget(item: MediaItem, label: IllustrationLabel): IllustrationLabel {
    return item.illustration_label === label ? 'unlabeled' : label;
  }

  function promoteFromBuffer() {
    const slots = VISIBLE_LIMIT - media.length;
    if (slots <= 0 || mediaBuffer.length === 0) return;
    media = [...media, ...mediaBuffer.slice(0, slots)];
    mediaBuffer = mediaBuffer.slice(slots);
  }

  function removeFromQueue(mediaId: number) {
    const index = media.findIndex((item) => item.id === mediaId);
    media = media.filter((item) => item.id !== mediaId);
    promoteFromBuffer();
    if (selectedId === mediaId) {
      selectedId = media[index]?.id ?? media[index - 1]?.id ?? null;
    }
  }

  function knownQueueIds() {
    return new Set([
      ...media.map((item) => item.id),
      ...mediaBuffer.map((item) => item.id),
      ...decidedMediaIds,
    ]);
  }

  async function refillBufferIfNeeded() {
    if (
      refillingBuffer ||
      nextCursor === null ||
      mediaBuffer.length > BUFFER_REFILL_THRESHOLD
    ) {
      return;
    }

    refillingBuffer = true;
    try {
      let cursor: string | null = nextCursor;
      let nextBuffer = mediaBuffer;
      const knownIds = knownQueueIds();
      let pagesRead = 0;

      while (cursor && nextBuffer.length < BUFFER_TARGET && pagesRead < 5) {
        const response = await api.media.list(listParams(BUFFER_TARGET, cursor));
        cursor = response.next_cursor;
        nextBuffer = [...nextBuffer, ...fetchedMedia(response.media, knownIds)];
        pagesRead += 1;
      }

      mediaBuffer = nextBuffer;
      nextCursor = cursor;
      promoteFromBuffer();
      if (!selectedId && media.length > 0) {
        selectedId = media[0].id;
      }
    } catch (e) {
      actionError = e instanceof Error ? e.message : 'Failed to refill triage queue';
    } finally {
      refillingBuffer = false;
    }
  }

  async function decideMedia(mediaId: number, status: 'approved' | 'rejected') {
    const target = media.find((item) => item.id === mediaId);
    if (!target) return;

    const previousMedia = media;
    const previousBuffer = mediaBuffer;
    const previousSelected = selectedId;
    const previousCursor = nextCursor;
    const previousDecidedIds = new Set(decidedMediaIds);
    const persistedLabel = localLabel(target);

    actionError = null;
    pendingActions = { ...pendingActions, [mediaId]: status };
    decidedMediaIds = new Set(decidedMediaIds);
    decidedMediaIds.add(mediaId);
    removeFromQueue(mediaId);

    try {
      await api.media.update(mediaId, {
        approval_status: status,
        illustration_label: persistedLabel,
      });
      showUndoNotice(
        { ...target, approval_status: status, illustration_label: persistedLabel },
        status
      );
      clearDraftLabel(mediaId);
      if (media.length === 0 && mediaBuffer.length === 0) {
        void load({ quiet: true });
      } else {
        void refillBufferIfNeeded();
      }
    } catch (e) {
      media = previousMedia;
      mediaBuffer = previousBuffer;
      selectedId = previousSelected;
      nextCursor = previousCursor;
      decidedMediaIds = previousDecidedIds;
      actionError = e instanceof Error ? e.message : 'Action failed';
    } finally {
      const { [mediaId]: _, ...rest } = pendingActions;
      pendingActions = rest;
    }
  }

  async function labelMedia(mediaId: number, label: IllustrationLabel) {
    const current = media.find((item) => item.id === mediaId);
    if (!current || pendingActions[mediaId] !== undefined) return;

    const nextLabel = labelTarget(current, label);
    actionError = null;
    setDraftLabel(mediaId, nextLabel);
    patchMediaInQueues(mediaId, { illustration_label: nextLabel });
  }

  async function analyzeMedia(mediaId: number) {
    actionError = null;
    taggingActions = { ...taggingActions, [mediaId]: true };
    try {
      const updated = applyDraftLabel(await api.media.analyze(mediaId));
      if (updated.approval_status !== 'under_review') {
        decidedMediaIds = new Set(decidedMediaIds);
        decidedMediaIds.add(mediaId);
        removeFromQueue(mediaId);
        clearDraftLabel(mediaId);
        void refillBufferIfNeeded();
      } else {
        patchMediaInQueues(mediaId, updated);
      }
    } catch (e) {
      actionError = e instanceof Error ? e.message : 'Tagging failed';
    } finally {
      const { [mediaId]: _, ...rest } = taggingActions;
      taggingActions = rest;
    }
  }

  function moveSelection(delta: number) {
    if (media.length === 0) return;
    const currentIndex = selectedId
      ? media.findIndex((item) => item.id === selectedId)
      : -1;
    const nextIndex = Math.min(
      media.length - 1,
      Math.max(0, (currentIndex === -1 ? 0 : currentIndex) + delta)
    );
    selectMedia(media[nextIndex].id);
  }

  function handleKeyboard(event: KeyboardEvent) {
    if (
      event.target instanceof HTMLInputElement ||
      event.target instanceof HTMLSelectElement ||
      event.target instanceof HTMLTextAreaElement
    ) {
      return;
    }
    if (!selectedMedia) return;

    if (event.key === 'k' || event.key === 'K') {
      if (itemBusy(selectedMedia.id)) return;
      event.preventDefault();
      void decideMedia(selectedMedia.id, 'approved');
    } else if (event.key === 'r' || event.key === 'R') {
      if (itemBusy(selectedMedia.id)) return;
      event.preventDefault();
      void decideMedia(selectedMedia.id, 'rejected');
    } else if (event.key === '1') {
      if (decisionBusy(selectedMedia.id)) return;
      event.preventDefault();
      void labelMedia(selectedMedia.id, 'yes');
    } else if (event.key === '2') {
      if (decisionBusy(selectedMedia.id)) return;
      event.preventDefault();
      void labelMedia(selectedMedia.id, 'no');
    } else if (event.key === '3') {
      if (decisionBusy(selectedMedia.id)) return;
      event.preventDefault();
      void labelMedia(selectedMedia.id, 'unsure');
    } else if (event.key === 'ArrowDown' || event.key === 'j') {
      event.preventDefault();
      moveSelection(1);
    } else if (event.key === 'ArrowUp' || event.key === 'p') {
      event.preventDefault();
      moveSelection(-1);
    }
  }

  function handleQueueChanged(event: ReviewQueueChangedEvent) {
    if (
      event.reason === 'media_decision' &&
      event.media_id !== undefined &&
      decidedMediaIds.has(event.media_id)
    ) {
      return;
    }
    queueChanged = true;
  }

  onMount(() => {
    void (async () => {
      loadRouteFilters();
      draftLabels = loadDraftLabels();
      await loadSourceOptions();
      await load();
    })();
    document.addEventListener('click', closeSourceMenuOnOutsideClick);
    document.addEventListener('keydown', handleKeyboard);
    const unsubscribeReviewQueueChanged = subscribeReviewQueueChanged(handleQueueChanged);
    return () => {
      document.removeEventListener('click', closeSourceMenuOnOutsideClick);
      document.removeEventListener('keydown', handleKeyboard);
      clearUndoTimer();
      unsubscribeReviewQueueChanged();
    };
  });
</script>

<div class="review-page">
  <div class="page-header">
    <div>
      <p class="eyebrow">Triage</p>
      <h1>Review extracted media</h1>
      <p>Keep, reject, label, and tag individual media before download.</p>
    </div>
    <div class="metric-strip">
      <div class="metric">
        <strong>{media.length}</strong>
        <span>visible media</span>
      </div>
      <div class="metric">
        <strong>{inFlightActionCount}</strong>
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
    <div class="field">
      <span>Illustration</span>
      <select class="select" value={draftIllustrationLabel} onchange={changeIllustrationLabel}>
        <option value="">Any</option>
        <option value="unlabeled">Unlabeled</option>
        <option value="yes">Yes</option>
        <option value="no">No</option>
        <option value="unsure">Unsure</option>
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
      {#if appliedIllustrationLabel}<span class="chip">illustration: {statusLabel(appliedIllustrationLabel)}</span>{/if}
      {#if routeMediaId}<span class="chip">media: {routeMediaId}</span>{/if}
      {#if routeItemId}<span class="chip">item: {routeItemId}</span>{/if}
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

  {#if undoNotice}
    <div class="notice" data-tone="positive">
      <Check size={16} />
      <span>{statusLabel(undoNotice.status)} media {undoNotice.media.sort_index + 1}</span>
      <button class="button" data-tone="quiet" onclick={undoLastDecision}>
        <RefreshCw size={16} />
        Undo
      </button>
    </div>
  {/if}

  {#if queueChanged}
    <div class="notice">
      <CircleAlert size={16} />
      <span>Queue changed in the background.</span>
      <button class="button" data-tone="quiet" onclick={manualRefresh}>
        <RefreshCw size={16} />
        Refresh
      </button>
    </div>
  {/if}

  {#if loading}
    <div class="triage-grid">
      <section class="panel queue-panel">
        <div class="panel-header">
          <h2>Media</h2>
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
      <section class="panel media-workbench">
        <div class="skeleton" style="height: 520px;"></div>
      </section>
    </div>
  {:else if errorMessage}
    <EmptyState title="Triage queue did not load" body={errorMessage} />
  {:else if media.length === 0}
    <EmptyState
      title="Nothing needs triage"
      body="New under-review media will appear here after the next refresh."
    >
      <Inbox size={22} />
    </EmptyState>
  {:else}
    <div class="triage-grid">
      <section class="panel queue-panel">
        <div class="panel-header">
          <h2>Media</h2>
          <span>{queueSummary}</span>
        </div>
        <div class="queue-list">
          {#each media as item (item.id)}
            <button
              class="queue-item"
              data-active={selectedId === item.id}
              onclick={() => selectMedia(item.id)}
            >
              <div class="media-thumb">
                {#if isVideoUrl(mediaUrl(item), mediaType(item))}
                  <!-- svelte-ignore a11y_media_has_caption -->
                  <video class="media-item" muted preload="metadata">
                    <source src={mediaUrl(item)} type={mediaType(item)} />
                  </video>
                {:else}
                  <img
                    class="media-item"
                    src={mediaUrl(item)}
                    alt={item.item_title}
                    loading="lazy"
                    referrerpolicy="no-referrer"
                  />
                {/if}
              </div>
              <div>
                <h2 class="queue-title">{item.item_title}</h2>
                <div class="meta-line">
                  <span>media {item.sort_index + 1}</span>
                  <span class="dot-separator"></span>
                  <span>{communityLabel(item)}</span>
                </div>
                <div class="meta-line" style="margin-top: 8px;">
                  <StatusBadge value={item.illustration_label} />
                  <span>{scorePercent(item.analysis?.illustration_score)}</span>
                </div>
              </div>
            </button>
          {/each}
        </div>
      </section>

      {#if selectedMedia}
        <section class="panel media-workbench">
          <div class="selected-media-stage">
            {#if isVideoUrl(mediaUrl(selectedMedia), mediaType(selectedMedia))}
              <!-- svelte-ignore a11y_media_has_caption -->
              <video class="media-item" controls preload="metadata">
                <source src={mediaUrl(selectedMedia)} type={mediaType(selectedMedia)} />
              </video>
            {:else}
              <img
                class="media-item"
                src={mediaUrl(selectedMedia)}
                alt={selectedMedia.item_title}
                referrerpolicy="no-referrer"
              />
            {/if}
          </div>
          <aside class="side-panel">
            <h2>{selectedMedia.item_title}</h2>
            <p>
              {communityLabel(selectedMedia)} · media {selectedMedia.sort_index + 1} · found {formatRelative(selectedMedia.discovered_at)}
            </p>
            <div class="actions-row">
              <StatusBadge value={selectedMedia.approval_status} />
              <StatusBadge value={selectedMedia.item_download_status} />
            </div>

            <div class="actions-row">
              <button
                class="button"
                data-tone="primary"
                disabled={itemBusy(selectedMedia.id)}
                onclick={() => decideMedia(selectedMedia.id, 'approved')}
              >
                <Check size={16} />
                Keep
              </button>
              <button
                class="button"
                data-tone="danger"
                disabled={itemBusy(selectedMedia.id)}
                onclick={() => decideMedia(selectedMedia.id, 'rejected')}
              >
                <X size={16} />
                Reject
              </button>
              <button
                class="button"
                data-tone="quiet"
                disabled={taggingActions[selectedMedia.id]}
                onclick={() => analyzeMedia(selectedMedia.id)}
              >
                <Tags size={16} />
                {taggingActions[selectedMedia.id] ? 'Tagging' : 'Tag'}
              </button>
            </div>

            <div class="triage-section">
              <strong>Illustration label</strong>
              <div class="segmented-control">
                {#each labelOptions as option}
                  <button
                    class="button"
                    data-tone={selectedMedia.illustration_label === option.value ? 'primary' : 'quiet'}
                    aria-pressed={selectedMedia.illustration_label === option.value}
                    disabled={decisionBusy(selectedMedia.id)}
                    onclick={() => labelMedia(selectedMedia.id, option.value)}
                  >
                    {option.label}
                  </button>
                {/each}
              </div>
            </div>

            <MediaAnalysisPanel
              analysis={selectedMedia.analysis}
              analyses={selectedMedia.analyses}
            />

            <div class="actions-row">
              <a
                class="button"
                data-tone="quiet"
                href={selectedMedia.source_url}
                target="_blank"
                rel="noreferrer"
              >
                <ExternalLink size={16} />
                {sourceLabel(selectedMedia)}
              </a>
              <a class="button" data-tone="quiet" href="/items/{selectedMedia.item_id}">
                Source detail
              </a>
            </div>
          </aside>
        </section>
      {/if}
    </div>
  {/if}
</div>
