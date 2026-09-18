import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { fetchMyManagedAmbulances } from '../services/competenceService';
import { useRoles } from './useRoles';
import { WorkplaceContext } from './workplaceContext';

/**
 * The workplace (ambulance) a scheduler is currently working on.
 *
 * Every scheduler screen used to keep its own copy of this: its own
 * GET /ambulances/me/managed, its own selected id defaulting to the first
 * row, and its own list widget in the page body. That meant three widgets
 * that looked different, three requests per navigation, and a choice that
 * was silently reset on every page change. The choice belongs to the
 * session, not to a page, so it lives here and is offered once — in the
 * header, via WorkplaceSwitcher.
 */

const STORAGE_KEY = 'activeWorkplaceId';

export function WorkplaceProvider({ children }) {
  const { hasManager } = useRoles();

  const [workplaces, setWorkplaces] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [loading, setLoading] = useState(hasManager);
  const [error, setError] = useState(false);
  const [forbidden, setForbidden] = useState(false);

  // Set by the screen currently on show while it holds unsaved edits; the
  // switcher asks it before changing the workplace under the editor.
  const guardRef = useRef(null);

  useEffect(() => {
    if (!hasManager) {
      setWorkplaces([]);
      setActiveId(null);
      setLoading(false);
      setForbidden(false);
      return undefined;
    }

    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const list = await fetchMyManagedAmbulances();
        if (cancelled) return;
        setWorkplaces(list);
        // A remembered id is only usable while it is still one of mine --
        // memberships change, and a stale id would 403 every request.
        const stored = Number(localStorage.getItem(STORAGE_KEY));
        const remembered = list.some((w) => w.id === stored) ? stored : null;
        setActiveId(remembered ?? list[0]?.id ?? null);
        setError(false);
        setForbidden(false);
      } catch (err) {
        if (cancelled) return;
        setError(true);
        setForbidden(err?.response?.status === 403);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [hasManager]);

  useEffect(() => {
    if (activeId != null) localStorage.setItem(STORAGE_KEY, String(activeId));
  }, [activeId]);

  const registerGuard = useCallback((fn) => {
    guardRef.current = fn;
    return () => {
      if (guardRef.current === fn) guardRef.current = null;
    };
  }, []);

  const isSwitchBlocked = useCallback(() => Boolean(guardRef.current?.()), []);

  const value = useMemo(() => {
    const active = workplaces.find((w) => w.id === activeId) || null;
    return {
      workplaces,
      activeId,
      active,
      loading,
      error,
      forbidden,
      setActive: setActiveId,
      isSwitchBlocked,
      registerGuard,
    };
  }, [workplaces, activeId, loading, error, forbidden, isSwitchBlocked, registerGuard]);

  return <WorkplaceContext.Provider value={value}>{children}</WorkplaceContext.Provider>;
}
