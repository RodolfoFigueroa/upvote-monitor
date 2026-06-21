<script lang="ts">
  import { ChevronDown, ChevronUp, Tags } from '@lucide/svelte';
  import type { MediaAnalysis } from '$lib/types/api';

  let {
    analysis = null,
    analyses = [],
  }: {
    analysis?: MediaAnalysis | null;
    analyses?: MediaAnalysis[];
  } = $props();

  let showAnalysisDetails = $state(false);
  let currentSignature = $state('');

  const signature = $derived(
    `${analysis?.analysis_profile_id ?? 'none'}:${analyses
      .map((entry) => `${entry.analysis_profile_id}:${entry.analyzed_at ?? ''}`)
      .join('|')}`
  );

  $effect(() => {
    if (signature !== currentSignature) {
      currentSignature = signature;
      showAnalysisDetails = false;
    }
  });

  function scorePercent(value: number | null | undefined): string {
    if (value === null || value === undefined) return 'unscored';
    return `${Math.round(value * 100)}%`;
  }

  function sortedScores(scores: Record<string, number> | undefined): [string, number][] {
    return Object.entries(scores ?? {}).sort((a, b) => b[1] - a[1]);
  }

  function shortModelName(value: string): string {
    return value.split('/').at(-1) ?? value;
  }
</script>

<div class="triage-section">
  <strong>Analysis</strong>
  <div class="notice" style="align-items: flex-start;">
    <Tags size={16} />
    <div>
      <strong>Illustration {scorePercent(analysis?.illustration_score)}</strong>
      <p>{analysis?.status ?? 'not analyzed'}</p>
    </div>
  </div>
</div>

{#if sortedScores(analysis?.ratings).length > 0}
  <div class="tag-group">
    <strong>Ratings</strong>
    <div class="chip-row">
      {#each sortedScores(analysis?.ratings) as [tag, score]}
        <span class="chip">{tag}: {scorePercent(score)}</span>
      {/each}
    </div>
  </div>
{/if}

{#if sortedScores(analysis?.character_tags).length > 0}
  <div class="tag-group">
    <strong>Character</strong>
    <div class="chip-row">
      {#each sortedScores(analysis?.character_tags).slice(0, 10) as [tag, score]}
        <span class="chip">{tag}: {scorePercent(score)}</span>
      {/each}
    </div>
  </div>
{/if}

{#if sortedScores(analysis?.general_tags).length > 0}
  <div class="tag-group">
    <strong>General</strong>
    <div class="chip-row">
      {#each sortedScores(analysis?.general_tags).slice(0, 18) as [tag, score]}
        <span class="chip">{tag}: {scorePercent(score)}</span>
      {/each}
    </div>
  </div>
{/if}

{#if analyses.length > 0}
  <div class="actions-row">
    <button
      class="button"
      data-tone="quiet"
      onclick={() => {
        showAnalysisDetails = !showAnalysisDetails;
      }}
    >
      {#if showAnalysisDetails}
        <ChevronUp size={16} />
      {:else}
        <ChevronDown size={16} />
      {/if}
      {showAnalysisDetails ? 'Hide analyses' : `Show ${analyses.length} analyses`}
    </button>
  </div>
  {#if showAnalysisDetails}
    <div class="analysis-stack">
      {#each analyses as entry}
        <div
          class="analysis-row"
          data-active={entry.analysis_profile_id === analysis?.analysis_profile_id}
        >
          <div>
            <strong>{shortModelName(entry.model_name)}</strong>
            <p>{entry.model_version} - {entry.scoring_version}</p>
          </div>
          <span>{scorePercent(entry.illustration_score)}</span>
          <p>
            stored {entry.stored_general_tag_count} general - {entry.stored_character_tag_count} character
          </p>
        </div>
      {/each}
    </div>
  {/if}
{/if}
