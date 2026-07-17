/** Prečíta role z localStorage (ukladá ich LoginView z GET /roles/me). */
export function getStoredRoles() {
  try {
    return JSON.parse(localStorage.getItem('roles')) || [];
  } catch {
    return [];
  }
}

/**
 * Roly a odvodené oprávnenia aktuálneho usera.
 * Role nie sú hierarchické — user môže mať viacero rolí naraz
 * (napr. EMPLOYEE aj LEADER) a každá odomyká svoju časť aplikácie nezávisle.
 */
export function useRoles() {
  const roles = getStoredRoles();
  const codes = new Set(roles.map((r) => r.name));
  const indexes = new Set(roles.map((r) => r.index));

  const hasRole = (code, index) => codes.has(code) || indexes.has(index);

  return {
    roles,
    hasEmployee: hasRole('EMPLOYEE', 1),
    hasManager: hasRole('LEADER', 2),
    hasAdmin: hasRole('AMBULANCE_OVERSEER', 3),
  };
}