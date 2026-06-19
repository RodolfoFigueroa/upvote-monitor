<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';

  onMount(() => {
    void goto('/settings/general', { replaceState: true });
  });
</script>

<section class="panel settings-form-page">
  <div class="panel-header"><h2>Loading settings</h2></div>
  <div class="list-editor">
    <div class="skeleton" style="height: 42px;"></div>
  </div>
</section>
