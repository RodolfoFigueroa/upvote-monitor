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

  type XDraft = {
    enabled: boolean;
    page_limit: number;
    page_size: number;
    user_agent: string;
    auth_token: string;
    ct0: string;
    twid: string;
    bearer_token: string;
  };

  type XSavedDraft = Omit<XDraft, 'auth_token' | 'ct0' | 'twid' | 'bearer_token'>;

  const defaultDraft: XDraft = {
    enabled: false,
    page_limit: 5,
    page_size: 20,
    user_agent:
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    auth_token: '',
    ct0: '',
    twid: '',
    bearer_token: '',
  };

  let settings = $state<SettingsResponse | null>(null);
  let draft = $state<XDraft>({ ...defaultDraft });
  let savedDraft = $state<XSavedDraft | null>(null);
  let authTokenConfigured = $state(false);
  let authTokenPrefix = $state<string | null>(null);
  let authTokenSuffix = $state<string | null>(null);
  let ct0Configured = $state(false);
  let ct0Prefix = $state<string | null>(null);
  let ct0Suffix = $state<string | null>(null);
  let twidConfigured = $state(false);
  let twidPrefix = $state<string | null>(null);
  let twidSuffix = $state<string | null>(null);
  let bearerTokenConfigured = $state(false);
  let bearerTokenPrefix = $state<string | null>(null);
  let bearerTokenSuffix = $state<string | null>(null);
  let secretsAvailable = $state(false);
  let loading = $state(true);
  let saving = $state(false);
  let clearing = $state(false);
  let invalidFields = $state<string[]>([]);
  let errorMessage = $state<string | null>(null);
  let message = $state<string | null>(null);

  let dirty = $derived(
    savedDraft !== null &&
      (!sameXDraft(draft, savedDraft) ||
        draft.auth_token.length > 0 ||
        draft.ct0.length > 0 ||
        draft.twid.length > 0 ||
        draft.bearer_token.length > 0)
  );
  let tokensConfigured = $derived(
    authTokenConfigured || ct0Configured || twidConfigured || bearerTokenConfigured
  );

  function toSavedDraft(value: SettingsResponse): XSavedDraft {
    return {
      enabled: value.sources.x.enabled,
      page_limit: value.sources.x.page_limit,
      page_size: value.sources.x.page_size,
      user_agent: value.sources.x.user_agent,
    };
  }

  function sameXDraft(a: XDraft, b: XSavedDraft): boolean {
    return (
      a.enabled === b.enabled &&
      Number(a.page_limit) === b.page_limit &&
      Number(a.page_size) === b.page_size &&
      a.user_agent === b.user_agent
    );
  }

  function applySettings(value: SettingsResponse) {
    settings = value;
    const nextDraft = toSavedDraft(value);
    draft = {
      ...nextDraft,
      auth_token: '',
      ct0: '',
      twid: '',
      bearer_token: '',
    };
    savedDraft = { ...nextDraft };
    authTokenConfigured = value.sources.x.auth_token_configured;
    authTokenPrefix = value.sources.x.auth_token_prefix;
    authTokenSuffix = value.sources.x.auth_token_suffix;
    ct0Configured = value.sources.x.ct0_configured;
    ct0Prefix = value.sources.x.ct0_prefix;
    ct0Suffix = value.sources.x.ct0_suffix;
    twidConfigured = value.sources.x.twid_configured;
    twidPrefix = value.sources.x.twid_prefix;
    twidSuffix = value.sources.x.twid_suffix;
    bearerTokenConfigured = value.sources.x.bearer_token_configured;
    bearerTokenPrefix = value.sources.x.bearer_token_prefix;
    bearerTokenSuffix = value.sources.x.bearer_token_suffix;
    secretsAvailable = value.sources.x.secrets_available;
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
    const xUpdate = {
      enabled: draft.enabled,
      page_limit: Number(draft.page_limit),
      page_size: Number(draft.page_size),
      user_agent: draft.user_agent,
      auth_token: undefined as string | undefined,
      ct0: undefined as string | undefined,
      twid: undefined as string | undefined,
      bearer_token: undefined as string | undefined,
    };

    if (draft.auth_token) {
      xUpdate.auth_token = draft.auth_token;
    }
    if (draft.ct0) {
      xUpdate.ct0 = draft.ct0;
    }
    if (draft.twid) {
      xUpdate.twid = draft.twid;
    }
    if (draft.bearer_token) {
      xUpdate.bearer_token = draft.bearer_token;
    }

    try {
      applySettings(
        await api.settings.update({
          sources: {
            x: xUpdate,
          },
        })
      );
      message = 'X settings saved';
    } catch (e) {
      handleSourceError(e, 'Failed to save settings');
    } finally {
      saving = false;
    }
  }

  async function clearTokens() {
    if (!tokensConfigured || !secretsAvailable || dirty) return;
    clearing = true;
    errorMessage = null;
    message = null;

    try {
      applySettings(
        await api.settings.update({
          sources: {
            x: {
              enabled: false,
              auth_token: '',
              ct0: '',
              twid: '',
              bearer_token: '',
            },
          },
        })
      );
      message = 'X tokens cleared and source disabled';
    } catch (e) {
      handleSourceError(e, 'Failed to clear tokens');
    } finally {
      clearing = false;
    }
  }

  function missingCredentialFields(): string[] {
    if (!draft.enabled) return [];
    const missing = [];
    if (!authTokenConfigured && !draft.auth_token.trim()) missing.push('auth_token');
    if (!ct0Configured && !draft.ct0.trim()) missing.push('ct0');
    if (!twidConfigured && !draft.twid.trim()) missing.push('twid');
    return missing;
  }

  function validateCredentialsBeforeSave(): boolean {
    const missing = missingCredentialFields();
    if (missing.length === 0) return true;
    invalidFields = missing;
    message = null;
    errorMessage = 'Missing required X credentials';
    return false;
  }

  function handleSourceError(error: unknown, fallback: string) {
    const detail = sourceSettingsErrorDetail(error, 'x');
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
    <div class="panel-header"><h2>X Source</h2></div>
    <div class="form-grid">
      {#each Array.from({ length: 8 }) as _}
        <div class="skeleton" style="height: 58px;"></div>
      {/each}
    </div>
  </section>
{:else if errorMessage && !settings}
  <EmptyState title="X settings did not load" body={errorMessage} />
{:else}
  <div class="settings-form-page">
    <SettingsNoticeStack
      {errorMessage}
      {message}
      secretsUnavailable={!secretsAvailable}
    />

    <section class="panel">
      <div class="panel-header">
        <h2>X Source</h2>
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
          <span>Page limit</span>
          <input class="input" type="number" min="1" max="10" bind:value={draft.page_limit} />
        </div>
        <div class="field">
          <span>Page size</span>
          <input class="input" type="number" min="1" max="100" bind:value={draft.page_size} />
        </div>
        <div class="field" style="grid-column: 1 / -1;">
          <span>User agent</span>
          <input class="input" bind:value={draft.user_agent} />
        </div>
        <div class="field">
          <span>auth_token</span>
          <input
            class="input"
            type="password"
            bind:value={draft.auth_token}
            data-invalid={isInvalid('auth_token')}
            aria-invalid={isInvalid('auth_token')}
            placeholder={secretPlaceholder(secretsAvailable, {
              configured: authTokenConfigured,
              prefix: authTokenPrefix,
              suffix: authTokenSuffix,
            })}
            disabled={!secretsAvailable}
            oninput={() => clearInvalidField('auth_token')}
          />
        </div>
        <div class="field">
          <span>ct0</span>
          <input
            class="input"
            type="password"
            bind:value={draft.ct0}
            data-invalid={isInvalid('ct0')}
            aria-invalid={isInvalid('ct0')}
            placeholder={secretPlaceholder(secretsAvailable, {
              configured: ct0Configured,
              prefix: ct0Prefix,
              suffix: ct0Suffix,
            })}
            disabled={!secretsAvailable}
            oninput={() => clearInvalidField('ct0')}
          />
        </div>
        <div class="field">
          <span>twid</span>
          <input
            class="input"
            type="password"
            bind:value={draft.twid}
            data-invalid={isInvalid('twid')}
            aria-invalid={isInvalid('twid')}
            placeholder={secretPlaceholder(secretsAvailable, {
              configured: twidConfigured,
              prefix: twidPrefix,
              suffix: twidSuffix,
            })}
            disabled={!secretsAvailable}
            oninput={() => clearInvalidField('twid')}
          />
        </div>
        <div class="field">
          <span>Bearer override</span>
          <input
            class="input"
            type="password"
            bind:value={draft.bearer_token}
            placeholder={secretPlaceholder(
              secretsAvailable,
              {
                configured: bearerTokenConfigured,
                prefix: bearerTokenPrefix,
                suffix: bearerTokenSuffix,
              }
            )}
            disabled={!secretsAvailable}
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
          disabled={saving || clearing || dirty || !tokensConfigured || !secretsAvailable}
        >
          <Trash2 size={16} />
          {clearing ? 'Clearing' : 'Clear tokens'}
        </button>
      </div>
    </section>
  </div>
{/if}
