import type {
  ItemUpdatedEvent,
  RefreshRunResponse,
  RefreshStatusResponse,
  ReviewQueueChangedEvent,
} from '$lib/types/api';
import { createEventClient } from '$lib/sse/events';

export const sseState = $state({
  refreshRunning: false,
  latestRun: null as RefreshRunResponse | null,
});

const itemUpdatedHandlers = new Set<(data: ItemUpdatedEvent) => void>();
const reviewQueueHandlers = new Set<(data: ReviewQueueChangedEvent) => void>();

let eventSource: EventSource | null = null;
let connectionCount = 0;

function handleRefreshStatus(data: RefreshStatusResponse) {
  sseState.refreshRunning = data.is_running;
  sseState.latestRun = data.latest_run;
}

function handleItemUpdated(data: ItemUpdatedEvent) {
  for (const handler of itemUpdatedHandlers) {
    handler(data);
  }
}

function handleReviewQueueChanged(data: ReviewQueueChangedEvent) {
  for (const handler of reviewQueueHandlers) {
    handler(data);
  }
}

export function connectEventStream(): () => void {
  connectionCount += 1;
  if (eventSource === null) {
    eventSource = createEventClient({
      onRefreshStatus: handleRefreshStatus,
      onItemUpdated: handleItemUpdated,
      onReviewQueueChanged: handleReviewQueueChanged,
    });
  }
  return disconnectEventStream;
}

export function disconnectEventStream(): void {
  connectionCount = Math.max(0, connectionCount - 1);
  if (connectionCount === 0 && eventSource !== null) {
    eventSource.close();
    eventSource = null;
  }
}

export function subscribeItemUpdated(
  handler: (data: ItemUpdatedEvent) => void
): () => void {
  itemUpdatedHandlers.add(handler);
  return () => itemUpdatedHandlers.delete(handler);
}

export function subscribeReviewQueueChanged(
  handler: (data: ReviewQueueChangedEvent) => void
): () => void {
  reviewQueueHandlers.add(handler);
  return () => reviewQueueHandlers.delete(handler);
}
