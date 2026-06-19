<script lang="ts">
  import { statusLabel } from '$lib/format';

  let { value }: { value: string } = $props();

  const tone = $derived(
    (
      {
        approved: 'positive',
        completed: 'positive',
        rejected: 'danger',
        failed: 'danger',
        under_review: 'review',
        in_progress: 'active',
        pending: 'neutral',
      } as Record<string, string>
    )[value] ?? 'neutral'
  );
</script>

<span class="status-badge" data-tone={tone}>
  <span class="status-badge__dot"></span>
  {statusLabel(value)}
</span>
