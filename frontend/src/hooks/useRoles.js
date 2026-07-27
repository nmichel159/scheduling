/** Prečíta role z localStorage (ukladá ich LoginView z GET /roles/me). */
export function getStoredRoles() {
  try {
    return JSON.parse(localStorage.getItem('roles')) || [];
  } catch {
    return [];
  }
}


export function useRoles() {
  const roles = getStoredRoles();
  const codes = new Set(roles.map((r) => r.name));

  return {
    roles,
    hasEmployee: codes.has('EMPLOYEE'),
    hasManager: codes.has('LEADER'),
    hasAdmin: codes.has('AMBULANCE_OVERSEER') || codes.has('HOSPITAL_ADMIN'),
  };
}