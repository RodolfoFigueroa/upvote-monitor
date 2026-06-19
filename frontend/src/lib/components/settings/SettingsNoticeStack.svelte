<script lang="ts">
  import { CircleAlert, SaveCheck } from '@lucide/svelte';

  let {
    errorMessage = null,
    message = null,
    secretsUnavailable = false,
  }: {
    errorMessage?: string | null;
    message?: string | null;
    secretsUnavailable?: boolean;
  } = $props();
</script>

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

{#if secretsUnavailable}
  <div class="notice" data-tone="danger">
    <CircleAlert size={16} />
    UPVOTE_MONITOR_SECRET_KEY is not configured. Source credentials cannot be saved or used.
  </div>
{/if}
