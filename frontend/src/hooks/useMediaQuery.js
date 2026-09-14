import { useEffect, useState } from 'react';

/**
 * Reaktívne sleduje media query. Bočná lišta sa podľa nej rozhoduje, či je
 * railom s fly-outmi (desktop) alebo celoobrazovkovým overlayom (mobil) —
 * jednorazové matchMedia() pri štarte by po zmene veľkosti okna zostalo
 * zaseknuté na starej hodnote.
 */
export function useMediaQuery(query) {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);

  useEffect(() => {
    const mql = window.matchMedia(query);
    const update = (e) => setMatches(e.matches);

    setMatches(mql.matches);
    mql.addEventListener('change', update);
    return () => mql.removeEventListener('change', update);
  }, [query]);

  return matches;
}

export const DESKTOP_QUERY = '(min-width: 769px)';
