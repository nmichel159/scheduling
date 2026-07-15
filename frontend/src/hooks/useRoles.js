/**
 * Mapa kódov rolí na levely — zrkadlí ROLES_DATA v backend/app/db/seed.py.
 * Level sa určuje primárne podľa kódu roly; index (id) je len fallback.
 */
const ROLE_LEVELS = {
  EMPLOYEE: 1,
  LEADER: 2,
  AMBULANCE_OVERSEER: 3,
  HOSPITAL_ADMIN: 4,
};

/** Prečíta role z localStorage (ukladá ich LoginView z GET /roles/me). */
export function getStoredRoles() {
  try {
    return JSON.parse(localStorage.getItem('roles')) || [];
  } catch {
    return [];
  }
}

/** Roly a odvodené oprávnenia aktuálneho usera. */
export function useRoles() {
  const roles = getStoredRoles();
  const maxLevel = roles.reduce(
    (max, r) => Math.max(max, ROLE_LEVELS[r.name] ?? r.index ?? 0),
    0
  );
  return {
    roles,
    maxLevel,
    isManager: maxLevel >= 2, // Rola 2: oddelenia, kompetencie, zamestnanci
    isAdmin: maxLevel >= 3,   // Rola 3: číselník ambulancií, manažéri
  };
}