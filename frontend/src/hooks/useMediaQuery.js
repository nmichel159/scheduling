import { useCallback, useSyncExternalStore } from 'react';

/**
 * Reaktívne sleduje media query. Bočná lišta sa podľa nej rozhoduje, či je
 * railom s fly-outmi (desktop) alebo celoobrazovkovým overlayom (mobil) —
 * jednorazové matchMedia() pri štarte by po zmene veľkosti okna zostalo
 * zaseknuté na starej hodnote.
 */
export function useMediaQuery(query) {
  const subscribe = useCallback(
    (onChange) => {
      const mql = window.matchMedia(query);
      mql.addEventListener('change', onChange);
      return () => mql.removeEventListener('change', onChange);
    },
    [query],
  );

  return useSyncExternalStore(subscribe, () => window.matchMedia(query).matches);
}

export const DESKTOP_QUERY = '(min-width: 769px)';
