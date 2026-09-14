import { useSyncExternalStore } from 'react';
import { getTheme, subscribeTheme } from '../theme';

/** Aktuálna voľba vzhľadu ('system' | 'light' | 'dark'), reaktívne. */
export function useTheme() {
  return useSyncExternalStore(subscribeTheme, getTheme);
}
