import { beforeNavigate } from '$app/navigation';
import { onMount } from 'svelte';

const DEFAULT_MESSAGE = 'Discard unsaved settings changes?';

export function useUnsavedChanges(
  hasUnsavedChanges: () => boolean,
  message = DEFAULT_MESSAGE
) {
  beforeNavigate((navigation) => {
    if (!hasUnsavedChanges()) return;
    if (window.confirm(message)) return;
    navigation.cancel();
  });

  onMount(() => {
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!hasUnsavedChanges()) return;
      event.preventDefault();
      event.returnValue = '';
    };

    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  });
}
