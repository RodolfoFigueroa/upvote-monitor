<script lang="ts">
  import { SaveCheck } from '@lucide/svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import SettingsNoticeStack from '$lib/components/settings/SettingsNoticeStack.svelte';
  import { api } from '$lib/api/client';
  import { useUnsavedChanges } from '$lib/settings/dirty';
  import type { ApprovalMode, SettingsResponse } from '$lib/types/api';
  import { onMount } from 'svelte';

  type GeneralDraft = {
    approval_mode: ApprovalMode;
    refresh_cron: string;
    refresh_enabled: boolean;
    download_base_dir: string;
    illustration_tagger_enabled: boolean;
    illustration_auto_approve_enabled: boolean;
    illustration_auto_approve_threshold: number;
    illustration_tag_persistence_threshold: number;
  };

  const defaultDraft: GeneralDraft = {
    approval_mode: 'manual',
    refresh_cron: '0 */6 * * *',
    refresh_enabled: true,
    download_base_dir: '/data/downloads',
    illustration_tagger_enabled: false,
    illustration_auto_approve_enabled: false,
    illustration_auto_approve_threshold: 0.9,
    illustration_tag_persistence_threshold: 0.15,
  };

  let settings = $state<SettingsResponse | null>(null);
  let draft = $state<GeneralDraft>({ ...defaultDraft });
  let savedDraft = $state<GeneralDraft | null>(null);
  let loading = $state(true);
  let saving = $state(false);
  let errorMessage = $state<string | null>(null);
  let message = $state<string | null>(null);

  let dirty = $derived(savedDraft !== null && !sameGeneralDraft(draft, savedDraft));

  function toGeneralDraft(value: SettingsResponse): GeneralDraft {
    return {
      approval_mode: value.approval_mode,
      refresh_cron: value.refresh_cron,
      refresh_enabled: value.refresh_enabled,
      download_base_dir: value.download_base_dir,
      illustration_tagger_enabled: value.illustration_tagger_enabled,
      illustration_auto_approve_enabled: value.illustration_auto_approve_enabled,
      illustration_auto_approve_threshold: value.illustration_auto_approve_threshold,
      illustration_tag_persistence_threshold: value.illustration_tag_persistence_threshold,
    };
  }

  function sameGeneralDraft(a: GeneralDraft, b: GeneralDraft): boolean {
    return (
      a.approval_mode === b.approval_mode &&
      a.refresh_cron === b.refresh_cron &&
      a.refresh_enabled === b.refresh_enabled &&
      a.download_base_dir === b.download_base_dir &&
      a.illustration_tagger_enabled === b.illustration_tagger_enabled &&
      a.illustration_auto_approve_enabled === b.illustration_auto_approve_enabled &&
      a.illustration_auto_approve_threshold === b.illustration_auto_approve_threshold &&
      a.illustration_tag_persistence_threshold === b.illustration_tag_persistence_threshold
    );
  }

  function applySettings(value: SettingsResponse) {
    settings = value;
    const nextDraft = toGeneralDraft(value);
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
          approval_mode: draft.approval_mode,
          refresh_cron: draft.refresh_cron,
          refresh_enabled: draft.refresh_enabled,
          download_base_dir: draft.download_base_dir,
          illustration_tagger_enabled: draft.illustration_tagger_enabled,
          illustration_auto_approve_enabled: draft.illustration_auto_approve_enabled,
          illustration_auto_approve_threshold: draft.illustration_auto_approve_threshold,
          illustration_tag_persistence_threshold: draft.illustration_tag_persistence_threshold,
        })
      );
      message = 'Settings saved';
    } catch (e) {
      errorMessage = e instanceof Error ? e.message : 'Failed to save settings';
    } finally {
      saving = false;
    }
  }

  function hasUnsavedChanges(): boolean {
    return dirty && !saving;
  }

  useUnsavedChanges(hasUnsavedChanges);
  onMount(load);
</script>

{#if loading}
  <section class="panel settings-form-page">
    <div class="panel-header"><h2>General</h2></div>
    <div class="form-grid">
      {#each Array.from({ length: 4 }) as _}
        <div class="skeleton" style="height: 58px;"></div>
      {/each}
    </div>
  </section>
{:else if errorMessage && !settings}
  <EmptyState title="Settings did not load" body={errorMessage} />
{:else}
  <div class="settings-form-page">
    <SettingsNoticeStack {errorMessage} {message} />

    <section class="panel">
      <div class="panel-header">
        <h2>General</h2>
        <span>{dirty ? 'unsaved changes' : 'saved'}</span>
      </div>
      <div class="form-grid">
        <div class="field">
          <span>Approval mode</span>
          <select class="select" bind:value={draft.approval_mode}>
            <option value="manual">Manual</option>
            <option value="auto">Auto</option>
          </select>
        </div>
        <div class="field">
          <span>Refresh CRON</span>
          <input class="input" bind:value={draft.refresh_cron} />
        </div>
        <div class="field" style="grid-column: 1 / -1;">
          <span>Download directory</span>
          <input class="input" bind:value={draft.download_base_dir} />
        </div>
        <label class="toggle-line">
          <input type="checkbox" bind:checked={draft.refresh_enabled} />
          Refresh enabled
        </label>
      </div>
    </section>

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
          <span>Auto-approve threshold</span>
          <input
            class="input"
            type="number"
            min="0"
            max="1"
            step="0.01"
            bind:value={draft.illustration_auto_approve_threshold}
            disabled={!draft.illustration_tagger_enabled}
          />
        </div>
        <div class="field">
          <span>Tag persistence threshold</span>
          <input
            class="input"
            type="number"
            min="0"
            max="1"
            step="0.01"
            bind:value={draft.illustration_tag_persistence_threshold}
            disabled={!draft.illustration_tagger_enabled}
          />
        </div>
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
