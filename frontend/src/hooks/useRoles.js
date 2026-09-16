import { useEffect, useState } from 'react';

const ROLES_CHANGED_EVENT = 'roles-changed';

/** Prečíta role z localStorage (ukladá ich LoginView z GET /roles/me). */
export function getStoredRoles() {
  try {
    return JSON.parse(localStorage.getItem('roles')) || [];
  } catch {
    return [];
  }
}


export function storeRoles(roles) {
  localStorage.setItem('roles', JSON.stringify(roles));
  window.dispatchEvent(new Event(ROLES_CHANGED_EVENT));
}


export function useRoles() {
  const [roles, setRoles] = useState(getStoredRoles);

  useEffect(() => {
    const refresh = () => setRoles(getStoredRoles());
    window.addEventListener(ROLES_CHANGED_EVENT, refresh);
    window.addEventListener('storage', refresh);
    return () => {
      window.removeEventListener(ROLES_CHANGED_EVENT, refresh);
      window.removeEventListener('storage', refresh);
    };
  }, []);

  const codes = new Set(roles.map((r) => r.name));

  return {
    roles,
    hasEmployee: codes.has('EMPLOYEE'),
    hasManager: codes.has('LEADER'),
    hasAdmin: codes.has('AMBULANCE_OVERSEER') || codes.has('ANALYST'),
    // Level 4: reads across every workplace, which is what the reports need.
    hasAnalyst: codes.has('ANALYST'),
  };
}


/**
 * Prvá obrazovka, ktorú daná kombinácia rolí smie vidieť. Domov je zamestnanecká
 * stránka ("moje" endpointy), takže vedúci/admin/analytik bez EMPLOYEE tam
 * nepatrí — dostane prvú položku svojej sekcie.
 */
export function landingPathFor(roles) {
  const codes = new Set((roles || []).map((r) => r.name));
  if (codes.has('EMPLOYEE')) return '/dashboard';
  if (codes.has('LEADER')) return '/ambulances/schedule';
  if (codes.has('AMBULANCE_OVERSEER') || codes.has('ANALYST')) return '/schedules/overview';
  return '/';
}


export function useLandingPath() {
  const { roles } = useRoles();
  return landingPathFor(roles);
}
