<script lang="ts">
  import {
    CircleAlert,
    Download,
    ExternalLink,
    Tags,
  } from '@lucide/svelte';
  import type { Snippet } from 'svelte';
  import { formatDate, sourceLabel } from '$lib/format';
  import type { ItemDetail, ItemFile, ItemSummary } from '$lib/types/api';
  import MediaPreview from './MediaPreview.svelte';
  import StatusBadge from './StatusBadge.svelte';

  let {
    item,
    detail = null,
    files = [],
    heading,
    meta,
    loadingMessage = null,
    showDownloaded = false,
    showDownloadError = false,
    actions,
  }: {
    item: ItemSummary | ItemDetail;
    detail?: ItemDetail | null;
    files?: ItemFile[];
    heading?: string;
    meta?: string;
    loadingMessage?: string | null;
    showDownloaded?: boolean;
    showDownloadError?: boolean;
    actions?: Snippet;
  } = $props();

  const compactTagLimit = 8;

  let showAllTags = $state(false);
  let currentItemId = $state<string | null>(null);

  const panelHeading = $derived(heading ?? item.title);
  const tagDetail = $derived(detail ?? ('media' in item ? item : null));
  const downloadError = $derived(
    showDownloadError
      ? detail?.download_error ?? ('download_error' in item ? item.download_error : null)
      : null
  );

  $effect(() => {
    if (item.id !== currentItemId) {
      currentItemId = item.id;
      showAllTags = false;
    }
  });

  function scorePercent(value: number | null | undefined): string {
    if (value === null || value === undefined) return 'unscored';
    return `${Math.round(value * 100)}%`;
  }

  function analysisStatusLabel(value: string | null): string {
    if (value === 'completed') return 'analyzed';
    if (value === 'failed') return 'failed';
    if (value === 'skipped') return 'skipped';
    return 'not analyzed';
  }

  function allAnalysisTags(value: ItemDetail | null): [string, number][] {
    return (
      value?.media
        .flatMap((media) => Object.entries(media.analysis?.tags ?? {}))
        .sort((a, b) => b[1] - a[1]) ?? []
    );
  }

  function visibleAnalysisTags(value: ItemDetail | null): [string, number][] {
    const tags = allAnalysisTags(value);
    return showAllTags ? tags : tags.slice(0, compactTagLimit);
  }

  function hasHiddenAnalysisTags(value: ItemDetail | null): boolean {
    return allAnalysisTags(value).length > compactTagLimit;
  }
</script>

<div class="decision-layout">
  <div class="media-stage">
    <MediaPreview {item} {files} />
  </div>
  <aside class="side-panel">
    <h2>{panelHeading}</h2>
    {#if meta}
      <p>{meta}</p>
    {/if}

    <div class="actions-row">
      <StatusBadge value={item.approval_status} />
      <StatusBadge value={item.download_status} />
    </div>

    {#if loadingMessage}
      <div class="notice" style="margin-top: 14px;">{loadingMessage}</div>
    {/if}

    {#if actions}
      <div class="actions-row">
        {@render actions()}
      </div>
    {/if}

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

    {#if showDownloaded}
      <div class="notice" style="margin-top: 16px;">
        <Download size={16} />
        Downloaded {formatDate(item.downloaded_at)}
      </div>
    {/if}

    {#if item.analysis_status || item.illustration_score !== null}
      <div class="notice" style="align-items: flex-start; margin-top: 10px;">
        <Tags size={16} />
        <div>
          <strong>Illustration {scorePercent(item.illustration_score)}</strong>
          <p>{analysisStatusLabel(item.analysis_status)}</p>
        </div>
      </div>
    {/if}

    {#if visibleAnalysisTags(tagDetail).length > 0}
      <div class="chip-row" style="margin-top: 10px;">
        {#each visibleAnalysisTags(tagDetail) as [tag, score]}
          <span class="chip">{tag}: {scorePercent(score)}</span>
        {/each}
      </div>
      {#if hasHiddenAnalysisTags(tagDetail)}
        <div class="actions-row" style="margin-top: 8px;">
          <button
            class="button"
            data-tone="quiet"
            onclick={() => {
              showAllTags = !showAllTags;
            }}
          >
            {showAllTags ? 'Show fewer tags' : `Show all ${allAnalysisTags(tagDetail).length} tags`}
          </button>
        </div>
      {/if}
    {/if}

    {#if downloadError}
      <div class="notice" data-tone="danger" style="margin-top: 10px;">
        <CircleAlert size={16} />
        {downloadError}
      </div>
    {/if}
  </aside>
</div>
