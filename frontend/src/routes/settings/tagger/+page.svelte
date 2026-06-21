<script lang="ts">
  import { SaveCheck } from '@lucide/svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import SettingsNoticeStack from '$lib/components/settings/SettingsNoticeStack.svelte';
  import { api } from '$lib/api/client';
  import { useUnsavedChanges } from '$lib/settings/dirty';
  import type { AnalysisProfile, SettingsResponse } from '$lib/types/api';
  import { onMount } from 'svelte';

  type TaggerDraft = {
    illustration_tagger_enabled: boolean;
    illustration_auto_approve_enabled: boolean;
    active_analysis_profile_id: string;
    general_tag_display_threshold: number;
    character_tag_display_threshold: number;
  };

  const defaultDraft: TaggerDraft = {
    illustration_tagger_enabled: false,
    illustration_auto_approve_enabled: false,
    active_analysis_profile_id: 'wd-swinv2-v3-default',
    general_tag_display_threshold: 0.15,
    character_tag_display_threshold: 0.35,
  };

  let settings = $state<SettingsResponse | null>(null);
  let draft = $state<TaggerDraft>({ ...defaultDraft });
  let savedDraft = $state<TaggerDraft | null>(null);
  let loading = $state(true);
  let saving = $state(false);
  let errorMessage = $state<string | null>(null);
  let message = $state<string | null>(null);

  let dirty = $derived(savedDraft !== null && !sameTaggerDraft(draft, savedDraft));
  const enabledProfiles = $derived(
    settings?.analysis_profiles.filter((profile) => profile.enabled) ?? []
  );
  const activeProfile = $derived(
    settings?.analysis_profiles.find(
      (profile) => profile.id === draft.active_analysis_profile_id
    ) ?? null
  );
  const generalThresholdPercent = $derived(
    Math.round(draft.general_tag_display_threshold * 100)
  );
  const characterThresholdPercent = $derived(
    Math.round(draft.character_tag_display_threshold * 100)
  );

  function toTaggerDraft(value: SettingsResponse): TaggerDraft {
    return {
      illustration_tagger_enabled: value.illustration_tagger_enabled,
      illustration_auto_approve_enabled: value.illustration_auto_approve_enabled,
      active_analysis_profile_id: value.active_analysis_profile_id,
      general_tag_display_threshold: value.general_tag_display_threshold,
      character_tag_display_threshold: value.character_tag_display_threshold,
    };
  }

  function sameTaggerDraft(a: TaggerDraft, b: TaggerDraft): boolean {
    return (
      a.illustration_tagger_enabled === b.illustration_tagger_enabled &&
      a.illustration_auto_approve_enabled === b.illustration_auto_approve_enabled &&
      a.active_analysis_profile_id === b.active_analysis_profile_id &&
      a.general_tag_display_threshold === b.general_tag_display_threshold &&
      a.character_tag_display_threshold === b.character_tag_display_threshold
    );
  }

  function applySettings(value: SettingsResponse) {
    settings = value;
    const nextDraft = toTaggerDraft(value);
    draft = { ...nextDraft };
    savedDraft = { ...nextDraft };
  }

  async function load() {
    loading = true;
    errorMessage = null;
    try {
      applySettings(await api.settings.get());
    } catch (e) {
      errorMessage = e instanceof Error ? e.message : 'Failed to load settings';
    } finally {
      loading = false;
    }
  }

  async function saveSettings() {
    if (!dirty) return;
    saving = true;
    errorMessage = null;
    message = null;
    try {
      applySettings(
        await api.settings.update({
          illustration_tagger_enabled: draft.illustration_tagger_enabled,
          illustration_auto_approve_enabled: draft.illustration_auto_approve_enabled,
          active_analysis_profile_id: draft.active_analysis_profile_id,
          general_tag_display_threshold: draft.general_tag_display_threshold,
          character_tag_display_threshold: draft.character_tag_display_threshold,
        })
      );
      message = 'Tagger settings saved';
    } catch (e) {
      errorMessage = e instanceof Error ? e.message : 'Failed to save settings';
    } finally {
      saving = false;
    }
  }

  function hasUnsavedChanges(): boolean {
    return dirty && !saving;
  }

  function percent(value: number): string {
    return `${Math.round(value * 100)}%`;
  }

  function shortModelName(value: string): string {
    return value.split('/').at(-1) ?? value;
  }

  function setGeneralDisplayThresholdPercent(value: string) {
    const percentValue = Number(value);
    if (!Number.isFinite(percentValue)) return;
    draft.general_tag_display_threshold = Math.min(1, Math.max(0, percentValue / 100));
  }

  function setCharacterDisplayThresholdPercent(value: string) {
    const percentValue = Number(value);
    if (!Number.isFinite(percentValue)) return;
    draft.character_tag_display_threshold = Math.min(
      1,
      Math.max(0, percentValue / 100)
    );
  }

  function profileLine(profile: AnalysisProfile): string {
    return `${profile.model_version} - ${profile.scoring_version} - approve ${percent(profile.auto_approve_threshold)}`;
  }

  useUnsavedChanges(hasUnsavedChanges);
  onMount(load);
</script>

{#if loading}
  <section class="panel settings-form-page">
    <div class="panel-header"><h2>Tagger</h2></div>
    <div class="form-grid">
      {#each Array.from({ length: 4 }) as _}
        <div class="skeleton" style="height: 58px;"></div>
      {/each}
    </div>
  </section>
{:else if errorMessage && !settings}
  <EmptyState title="Tagger settings did not load" body={errorMessage} />
{:else}
  <div class="settings-form-page">
    <SettingsNoticeStack {errorMessage} {message} />

    <section class="panel">
      <div class="panel-header">
        <h2>Illustration Tagger</h2>
        <span>{dirty ? 'unsaved changes' : 'saved'}</span>
      </div>
      <div class="form-grid">
        <label class="toggle-line">
          <input type="checkbox" bind:checked={draft.illustration_tagger_enabled} />
          Tag illustrations
        </label>
        <label class="toggle-line">
          <input
            type="checkbox"
            bind:checked={draft.illustration_auto_approve_enabled}
            disabled={!draft.illustration_tagger_enabled}
          />
          Auto-approve matching images
        </label>
        <div class="field">
          <span>Analysis profile</span>
          <select class="select" bind:value={draft.active_analysis_profile_id}>
            {#each enabledProfiles as profile}
              <option value={profile.id}>{profile.name}</option>
            {/each}
          </select>
        </div>
        {#if activeProfile}
          <div class="notice" style="grid-column: 1 / -1; align-items: flex-start;">
            <div>
              <strong>{activeProfile.model_name}</strong>
              <p>{profileLine(activeProfile)}</p>
            </div>
          </div>
        {/if}
      </div>
    </section>

    <section class="panel">
      <div class="panel-header">
        <h2>Tag Display</h2>
        <span>{dirty ? 'unsaved changes' : 'saved'}</span>
      </div>
      <p class="panel-copy">
        These settings only hide low-confidence tags in the UI. Stored tag data,
        model analysis, and auto-approval behavior stay unchanged.
      </p>
      <div class="form-grid">
        <div class="field threshold-field">
          <span>General tag display threshold</span>
          <div class="threshold-control">
            <input
              class="range-input"
              type="range"
              min="0"
              max="100"
              step="1"
              value={generalThresholdPercent}
              oninput={(event) =>
                setGeneralDisplayThresholdPercent(event.currentTarget.value)}
            />
            <input
              class="input threshold-number"
              type="number"
              min="0"
              max="100"
              step="1"
              value={generalThresholdPercent}
              oninput={(event) =>
                setGeneralDisplayThresholdPercent(event.currentTarget.value)}
            />
            <span class="threshold-unit">%</span>
          </div>
        </div>
        <div class="field threshold-field">
          <span>Character tag display threshold</span>
          <div class="threshold-control">
            <input
              class="range-input"
              type="range"
              min="0"
              max="100"
              step="1"
              value={characterThresholdPercent}
              oninput={(event) =>
                setCharacterDisplayThresholdPercent(event.currentTarget.value)}
            />
            <input
              class="input threshold-number"
              type="number"
              min="0"
              max="100"
              step="1"
              value={characterThresholdPercent}
              oninput={(event) =>
                setCharacterDisplayThresholdPercent(event.currentTarget.value)}
            />
            <span class="threshold-unit">%</span>
          </div>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-header">
        <h2>Model Profiles</h2>
        <span>{enabledProfiles.length} enabled</span>
      </div>
      <div class="list-editor">
        {#each enabledProfiles as profile}
          <div
            class="analysis-row"
            data-active={profile.id === draft.active_analysis_profile_id}
          >
            <div>
              <strong>{profile.name}</strong>
              <p>{shortModelName(profile.model_name)} - {profileLine(profile)}</p>
            </div>
          </div>
        {/each}
      </div>
    </section>

    <div class="actions-row settings-actions">
      <button
        class="button"
        data-tone="primary"
        onclick={saveSettings}
        disabled={saving || !dirty}
      >
        <SaveCheck size={16} />
        {saving ? 'Saving' : 'Save'}
      </button>
    </div>
  </div>
{/if}
