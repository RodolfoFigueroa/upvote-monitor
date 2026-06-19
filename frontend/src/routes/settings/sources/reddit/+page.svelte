<script lang="ts">
  import { SaveCheck, Trash2 } from '@lucide/svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import SettingsNoticeStack from '$lib/components/settings/SettingsNoticeStack.svelte';
  import { api } from '$lib/api/client';
  import { useUnsavedChanges } from '$lib/settings/dirty';
  import { secretPlaceholder } from '$lib/settings/secrets';
  import { sourceSettingsErrorDetail } from '$lib/settings/source-errors';
  import type { SettingsResponse } from '$lib/types/api';
  import { onMount } from 'svelte';

  type RedditDraft = {
    enabled: boolean;
    username: string;
    page_limit: number;
    user_agent: string;
    session_cookie: string;
  };

  type RedditSavedDraft = Omit<RedditDraft, 'session_cookie'>;

  const defaultDraft: RedditDraft = {
    enabled: true,
    username: '',
    page_limit: 10,
    user_agent: 'MyPersonalArchiveScript/1.0',
    session_cookie: '',
  };

  let settings = $state<SettingsResponse | null>(null);
  let draft = $state<RedditDraft>({ ...defaultDraft });
  let savedDraft = $state<RedditSavedDraft | null>(null);
  let sessionCookieConfigured = $state(false);
  let sessionCookiePrefix = $state<string | null>(null);
  let sessionCookieSuffix = $state<string | null>(null);
  let secretsAvailable = $state(false);
  let loading = $state(true);
  let saving = $state(false);
  let clearing = $state(false);
  let invalidFields = $state<string[]>([]);
  let errorMessage = $state<string | null>(null);
  let message = $state<string | null>(null);

  let dirty = $derived(
    savedDraft !== null &&
      (!sameRedditDraft(draft, savedDraft) || draft.session_cookie.length > 0)
  );

  function toSavedDraft(value: SettingsResponse): RedditSavedDraft {
    return {
      enabled: value.sources.reddit.enabled,
      username: value.sources.reddit.username,
      page_limit: value.sources.reddit.page_limit,
      user_agent: value.sources.reddit.user_agent,
    };
  }

  function sameRedditDraft(a: RedditDraft, b: RedditSavedDraft): boolean {
    return (
      a.enabled === b.enabled &&
      a.username === b.username &&
      Number(a.page_limit) === b.page_limit &&
      a.user_agent === b.user_agent
    );
  }

  function applySettings(value: SettingsResponse) {
    settings = value;
    const nextDraft = toSavedDraft(value);
    draft = {
      ...nextDraft,
      session_cookie: '',
    };
    savedDraft = { ...nextDraft };
    sessionCookieConfigured = value.sources.reddit.session_cookie_configured;
    sessionCookiePrefix = value.sources.reddit.session_cookie_prefix;
    sessionCookieSuffix = value.sources.reddit.session_cookie_suffix;
    secretsAvailable = value.sources.reddit.secrets_available;
    invalidFields = [];
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
    if (!validateCredentialsBeforeSave()) return;
    saving = true;
    errorMessage = null;
    message = null;
    const redditUpdate = {
      enabled: draft.enabled,
      username: draft.username,
      page_limit: Number(draft.page_limit),
      user_agent: draft.user_agent,
      session_cookie: undefined as string | undefined,
    };

    if (draft.session_cookie) {
      redditUpdate.session_cookie = draft.session_cookie;
    }

    try {
      applySettings(
        await api.settings.update({
          sources: {
            reddit: redditUpdate,
          },
        })
      );
      message = 'Reddit settings saved';
    } catch (e) {
      handleSourceError(e, 'Failed to save settings');
    } finally {
      saving = false;
    }
  }

  async function clearTokens() {
    if (!sessionCookieConfigured || !secretsAvailable || dirty) return;
    clearing = true;
    errorMessage = null;
    message = null;

    try {
      applySettings(
        await api.settings.update({
          sources: {
            reddit: {
              enabled: false,
              session_cookie: '',
            },
          },
        })
      );
      message = 'Reddit tokens cleared and source disabled';
    } catch (e) {
      handleSourceError(e, 'Failed to clear tokens');
    } finally {
      clearing = false;
    }
  }

  function missingCredentialFields(): string[] {
    if (!draft.enabled) return [];
    const missing = [];
    if (!draft.username.trim()) missing.push('username');
    if (!sessionCookieConfigured && !draft.session_cookie.trim()) {
      missing.push('session_cookie');
    }
    return missing;
  }

  function validateCredentialsBeforeSave(): boolean {
    const missing = missingCredentialFields();
    if (missing.length === 0) return true;
    invalidFields = missing;
    message = null;
    errorMessage = 'Missing required Reddit credentials';
    return false;
  }

  function handleSourceError(error: unknown, fallback: string) {
    const detail = sourceSettingsErrorDetail(error, 'reddit');
    if (detail?.fields?.length) invalidFields = detail.fields;
    errorMessage = detail?.message ?? (error instanceof Error ? error.message : fallback);
  }

  function isInvalid(field: string): boolean {
    return invalidFields.includes(field);
  }

  function clearInvalidField(field: string) {
    invalidFields = invalidFields.filter((value) => value !== field);
  }

  function hasUnsavedChanges(): boolean {
    return dirty && !saving && !clearing;
  }

  useUnsavedChanges(hasUnsavedChanges);
  onMount(load);
</script>

{#if loading}
  <section class="panel settings-form-page">
    <div class="panel-header"><h2>Reddit Source</h2></div>
    <div class="form-grid">
      {#each Array.from({ length: 6 }) as _}
        <div class="skeleton" style="height: 58px;"></div>
      {/each}
    </div>
  </section>
{:else if errorMessage && !settings}
  <EmptyState title="Reddit settings did not load" body={errorMessage} />
{:else}
  <div class="settings-form-page">
    <SettingsNoticeStack
      {errorMessage}
      {message}
      secretsUnavailable={!secretsAvailable}
    />

    <section class="panel">
      <div class="panel-header">
        <h2>Reddit Source</h2>
        <span>{dirty ? 'unsaved changes' : draft.enabled ? 'enabled' : 'disabled'}</span>
      </div>
      <div class="form-grid">
        <label class="toggle-line">
          <input
            type="checkbox"
            bind:checked={draft.enabled}
            onchange={() => {
              if (!draft.enabled) invalidFields = [];
            }}
          />
          Source enabled
        </label>
        <div class="field">
          <span>Username</span>
          <input
            class="input"
            bind:value={draft.username}
            data-invalid={isInvalid('username')}
            aria-invalid={isInvalid('username')}
            oninput={() => clearInvalidField('username')}
          />
        </div>
        <div class="field">
          <span>Page limit</span>
          <input
            class="input"
            type="number"
            min="1"
            max="10"
            bind:value={draft.page_limit}
          />
        </div>
        <div class="field">
          <span>User agent</span>
          <input class="input" bind:value={draft.user_agent} />
        </div>
        <div class="field" style="grid-column: 1 / -1;">
          <span>Session cookie</span>
          <input
            class="input"
            type="password"
            bind:value={draft.session_cookie}
            data-invalid={isInvalid('session_cookie')}
            aria-invalid={isInvalid('session_cookie')}
            placeholder={secretPlaceholder(
              secretsAvailable,
              {
                configured: sessionCookieConfigured,
                prefix: sessionCookiePrefix,
                suffix: sessionCookieSuffix,
              }
            )}
            disabled={!secretsAvailable}
            oninput={() => clearInvalidField('session_cookie')}
          />
        </div>
      </div>
      <div class="actions-row settings-actions">
        <button
          class="button"
          data-tone="primary"
          onclick={saveSettings}
          disabled={saving || clearing || !dirty}
        >
          <SaveCheck size={16} />
          {saving ? 'Saving' : 'Save'}
        </button>
        <button
          class="button"
          data-tone="danger"
          onclick={clearTokens}
          disabled={saving || clearing || dirty || !sessionCookieConfigured || !secretsAvailable}
        >
          <Trash2 size={16} />
          {clearing ? 'Clearing' : 'Clear tokens'}
        </button>
      </div>
    </section>
  </div>
{/if}
