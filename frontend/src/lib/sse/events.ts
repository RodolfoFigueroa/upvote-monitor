import type {
  ItemUpdatedEvent,
  RefreshStatusResponse,
  ReviewQueueChangedEvent,
} from '$lib/types/api';

export type RefreshStatusHandler = (data: RefreshStatusResponse) => void;
export type ItemUpdatedHandler = (data: ItemUpdatedEvent) => void;
export type ReviewQueueChangedHandler = (data: ReviewQueueChangedEvent) => void;

export function createEventClient(handlers: {
  onRefreshStatus?: RefreshStatusHandler;
  onItemUpdated?: ItemUpdatedHandler;
  onReviewQueueChanged?: ReviewQueueChangedHandler;
}): EventSource {
  const source = new EventSource('/api/events');

  source.addEventListener('refresh_status', (event) => {
    const data = JSON.parse((event as MessageEvent).data) as RefreshStatusResponse;
    handlers.onRefreshStatus?.(data);
  });

  source.addEventListener('item_updated', (event) => {
    const data = JSON.parse((event as MessageEvent).data) as ItemUpdatedEvent;
    handlers.onItemUpdated?.(data);
  });

  source.addEventListener('review_queue_changed', (event) => {
    const data = JSON.parse((event as MessageEvent).data) as ReviewQueueChangedEvent;
    handlers.onReviewQueueChanged?.(data);
  });

  return source;
}
