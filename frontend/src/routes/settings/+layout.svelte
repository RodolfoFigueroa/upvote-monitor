<script lang="ts">
  import { page } from '$app/stores';
  import type { Snippet } from 'svelte';
  import {
    AtSign,
    ListChecks,
    MessageCircle,
    RefreshCw,
    Settings,
  } from '@lucide/svelte';

  let { children }: { children: Snippet } = $props();

  function isActive(href: string): boolean {
    const path = $page.url.pathname;
    return path === href || path.startsWith(`${href}/`);
  }
</script>

<div class="settings-layout">
  <div class="page-header">
    <div>
      <p class="eyebrow">Settings</p>
      <h1>Control review behavior</h1>
      <p>Adjust automation, source connections, and community rules.</p>
    </div>
  </div>

  <nav class="settings-tabs" aria-label="Settings sections">
    <a
      class="settings-tab"
      href="/settings/general"
      data-active={isActive('/settings/general')}
      title="General"
    >
      <Settings size={16} />
      <span>General</span>
    </a>
    <a
      class="settings-tab"
      href="/settings/sources/reddit"
      data-active={isActive('/settings/sources/reddit')}
      title="Reddit"
    >
      <MessageCircle size={16} />
      <span>Reddit</span>
    </a>
    <a
      class="settings-tab"
      href="/settings/sources/x"
      data-active={isActive('/settings/sources/x')}
      title="X"
    >
      <AtSign size={16} />
      <span>X</span>
    </a>
    <a
      class="settings-tab"
      href="/settings/rules"
      data-active={isActive('/settings/rules')}
      title="Rules"
    >
      <ListChecks size={16} />
      <span>Rules</span>
    </a>
    <a
      class="settings-tab"
      href="/settings/refresh"
      data-active={isActive('/settings/refresh')}
      title="Refresh"
    >
      <RefreshCw size={16} />
      <span>Refresh</span>
    </a>
  </nav>

  <div class="settings-route">
    {@render children()}
  </div>
</div>
