<script lang="ts">
  import { CircleAlert, Plus, SaveCheck, Trash2 } from '@lucide/svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import { api } from '$lib/api/client';
  import { useUnsavedChanges } from '$lib/settings/dirty';
  import type { RuleEntry, RuleTargetType } from '$lib/types/api';
  import { onMount } from 'svelte';

  let whitelist = $state<RuleEntry[]>([]);
  let blacklist = $state<RuleEntry[]>([]);
  let loading = $state(true);
  let addingWhitelist = $state(false);
  let addingBlacklist = $state(false);
  let removingWhitelist = $state<string | null>(null);
  let removingBlacklist = $state<string | null>(null);
  let errorMessage = $state<string | null>(null);
  let message = $state<string | null>(null);

  let newWhitelist = $state('');
  let newBlacklist = $state('');
  let newWhitelistSource = $state('reddit');
  let newBlacklistSource = $state('reddit');
  let newWhitelistTargetType = $state<RuleTargetType>('community');
  let newBlacklistTargetType = $state<RuleTargetType>('community');

  let dirty = $derived(newWhitelist.trim().length > 0 || newBlacklist.trim().length > 0);

  function syncDefaultTarget(source: string, current: RuleTargetType): RuleTargetType {
    if (source === 'x') return 'author';
    if (source === 'reddit') return 'community';
    return current;
  }

  function rulePlaceholder(targetType: RuleTargetType) {
    return targetType === 'author' ? '@handle' : 'community name';
  }

  async function load() {
    loading = true;
    errorMessage = null;
    try {
      const lists = await api.rules.get();
      whitelist = lists.whitelist;
      blacklist = lists.blacklist;
    } catch (e) {
      errorMessage = e instanceof Error ? e.message : 'Failed to load rules';
    } finally {
      loading = false;
    }
  }

  async function addWhitelist() {
    const targetValue = newWhitelist.trim();
    if (!targetValue) return;
    addingWhitelist = true;
    errorMessage = null;
    message = null;
    try {
      const lists = await api.rules.addWhitelist({
        source: newWhitelistSource,
        target_type: newWhitelistTargetType,
        target_value: targetValue,
      });
      whitelist = lists.whitelist;
      newWhitelist = '';
      message = `Added ${targetValue} to whitelist`;
    } catch (e) {
      errorMessage = e instanceof Error ? e.message : 'Failed to add whitelist entry';
    } finally {
      addingWhitelist = false;
    }
  }

  async function addBlacklist() {
    const targetValue = newBlacklist.trim();
    if (!targetValue) return;
    addingBlacklist = true;
    errorMessage = null;
    message = null;
    try {
      const lists = await api.rules.addBlacklist({
        source: newBlacklistSource,
        target_type: newBlacklistTargetType,
        target_value: targetValue,
      });
      blacklist = lists.blacklist;
      newBlacklist = '';
      message = `Added ${targetValue} to blacklist`;
    } catch (e) {
      errorMessage = e instanceof Error ? e.message : 'Failed to add blacklist entry';
    } finally {
      addingBlacklist = false;
    }
  }

  async function removeWhitelist(entry: RuleEntry) {
    removingWhitelist = entry.target_value;
    errorMessage = null;
    message = null;
    try {
      const lists = await api.rules.removeWhitelist(entry);
      whitelist = lists.whitelist;
    } catch (e) {
      errorMessage = e instanceof Error ? e.message : 'Failed to remove whitelist entry';
    } finally {
      removingWhitelist = null;
    }
  }

  async function removeBlacklist(entry: RuleEntry) {
    removingBlacklist = entry.target_value;
    errorMessage = null;
    message = null;
    try {
      const lists = await api.rules.removeBlacklist(entry);
      blacklist = lists.blacklist;
    } catch (e) {
      errorMessage = e instanceof Error ? e.message : 'Failed to remove blacklist entry';
    } finally {
      removingBlacklist = null;
    }
  }

  function hasUnsavedChanges(): boolean {
    return dirty && !addingWhitelist && !addingBlacklist;
  }

  useUnsavedChanges(hasUnsavedChanges);
  onMount(load);
</script>

{#if loading}
  <div class="settings-grid">
    <section class="panel">
      <div class="panel-header"><h2>Whitelist</h2></div>
      <div class="list-editor">
        {#each Array.from({ length: 4 }) as _}
          <div class="skeleton" style="height: 38px;"></div>
        {/each}
      </div>
    </section>
    <section class="panel">
      <div class="panel-header"><h2>Blacklist</h2></div>
      <div class="list-editor">
        {#each Array.from({ length: 4 }) as _}
          <div class="skeleton" style="height: 38px;"></div>
        {/each}
      </div>
    </section>
  </div>
{:else if errorMessage && whitelist.length === 0 && blacklist.length === 0}
  <EmptyState title="Rules did not load" body={errorMessage} />
{:else}
  <div class="settings-stack">
    {#if errorMessage}
      <div class="notice" data-tone="danger">
        <CircleAlert size={16} />
        {errorMessage}
      </div>
    {/if}
    {#if message}
      <div class="notice" data-tone="positive">
        <SaveCheck size={16} />
        {message}
      </div>
    {/if}

    <div class="settings-grid">
      <section class="panel">
        <div class="panel-header">
          <h2>Whitelist</h2>
          <span>{whitelist.length}</span>
        </div>
        <div class="list-editor">
          <div class="actions-row" style="margin-top: 0;">
            <select
              class="select"
              bind:value={newWhitelistSource}
              onchange={() => {
                newWhitelistTargetType = syncDefaultTarget(
                  newWhitelistSource,
                  newWhitelistTargetType
                );
              }}
            >
              <option value="reddit">Reddit</option>
              <option value="x">X</option>
            </select>
            <select class="select" bind:value={newWhitelistTargetType}>
              <option value="community">Community</option>
              <option value="author">Author</option>
            </select>
            <input
              class="input"
              bind:value={newWhitelist}
              placeholder={rulePlaceholder(newWhitelistTargetType)}
              onkeydown={(event) => {
                if (event.key === 'Enter') void addWhitelist();
              }}
            />
            <button class="button" onclick={addWhitelist} disabled={addingWhitelist}>
              <Plus size={16} />
              Add
            </button>
          </div>
          {#each whitelist as entry}
            <div class="list-item">
              <span>{entry.target_label}</span>
              <button
                class="icon-button"
                title="Remove"
                onclick={() => removeWhitelist(entry)}
                disabled={removingWhitelist === entry.target_value}
              >
                <Trash2 size={15} />
              </button>
            </div>
          {/each}
        </div>
      </section>

      <section class="panel">
        <div class="panel-header">
          <h2>Blacklist</h2>
          <span>{blacklist.length}</span>
        </div>
        <div class="list-editor">
          <div class="actions-row" style="margin-top: 0;">
            <select
              class="select"
              bind:value={newBlacklistSource}
              onchange={() => {
                newBlacklistTargetType = syncDefaultTarget(
                  newBlacklistSource,
                  newBlacklistTargetType
                );
              }}
            >
              <option value="reddit">Reddit</option>
              <option value="x">X</option>
            </select>
            <select class="select" bind:value={newBlacklistTargetType}>
              <option value="community">Community</option>
              <option value="author">Author</option>
            </select>
            <input
              class="input"
              bind:value={newBlacklist}
              placeholder={rulePlaceholder(newBlacklistTargetType)}
              onkeydown={(event) => {
                if (event.key === 'Enter') void addBlacklist();
              }}
            />
            <button class="button" onclick={addBlacklist} disabled={addingBlacklist}>
              <Plus size={16} />
              Add
            </button>
          </div>
          {#each blacklist as entry}
            <div class="list-item">
              <span>{entry.target_label}</span>
              <button
                class="icon-button"
                title="Remove"
                onclick={() => removeBlacklist(entry)}
                disabled={removingBlacklist === entry.target_value}
              >
                <Trash2 size={15} />
              </button>
            </div>
          {/each}
        </div>
      </section>
    </div>
  </div>
{/if}
