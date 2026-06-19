<script lang="ts">
  import { Images } from '@lucide/svelte';
  import { isVideoUrl, mediaUrls } from '$lib/format';
  import type { ItemDetail, ItemFile, ItemSummary } from '$lib/types/api';

  let {
    item,
    files = [],
    compact = false,
  }: {
    item: ItemSummary | ItemDetail;
    files?: ItemFile[];
    compact?: boolean;
  } = $props();

  const mediaItems = $derived(mediaUrls(item, files, { preferSourceVideo: !compact }));
  const visibleItems = $derived(compact ? mediaItems.slice(0, 1) : mediaItems);
</script>

{#if visibleItems.length === 0}
  <div class:media-empty={!compact} class:media-thumb-empty={compact}>
    <Images size={compact ? 18 : 28} />
    <span>No media preview</span>
  </div>
{:else}
  <div class:media-grid={!compact} class:media-thumb={compact}>
    {#each visibleItems as item (item.url)}
      {#if isVideoUrl(item.url, item.mediaType)}
        <!-- svelte-ignore a11y_media_has_caption -->
        <video
          class="media-item"
          controls={!compact}
          muted={compact}
          preload="metadata"
        >
          <source
            src={item.url}
            type={item.mediaType?.includes('/') ? item.mediaType : undefined}
          />
        </video>
      {:else}
        <img
          class="media-item"
          src={item.url}
          alt={item.label}
          loading="lazy"
          referrerpolicy="no-referrer"
        />
      {/if}
    {/each}
  </div>
{/if}
