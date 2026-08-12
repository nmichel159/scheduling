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
    hasAdmin: codes.has('AMBULANCE_OVERSEER') || codes.has('HOSPITAL_ADMIN'),
  };
}
