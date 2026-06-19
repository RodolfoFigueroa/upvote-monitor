<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    title,
    body,
    children,
  }: {
    title: string;
    body?: string;
    children?: Snippet;
  } = $props();
</script>

<section class="empty-state">
  <div>
    <h2>{title}</h2>
    {#if body}
      <p>{body}</p>
    {/if}
  </div>
  {#if children}
    <div class="empty-state__actions">
      {@render children()}
    </div>
  {/if}
</section>
