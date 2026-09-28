import client from '../api/client';

/**
 * Frontend service for the scheduling rules of one workplace.
 *
 * The rules and their defaults are defined on the backend; each comes back
 * with a `mode` saying what may be changed:
 *
 *   fixed       always strict — nothing to set
 *   switchable  strict, or penalized with a weight
 *   penalty     always penalized — only the weight is set
 *
 * Every call answers with the whole list, because a rule set back to its
 * default loses its stored row and the screen would otherwise have to guess
 * which `is_default` flags moved.
 */

export const CONSTRAINT_MODE = {
  FIXED: 'fixed',
  SWITCHABLE: 'switchable',
  PENALTY: 'penalty',
};

/** The groups the screen shows, in order. */
export const CONSTRAINT_GROUPS = ['fixed', 'absence', 'load', 'wish'];

/** Load every rule of one workplace. */
export async function fetchConstraints(ambulanceId) {
  const { data } = await client.get(`/ambulances/${ambulanceId}/constraints`);
  return data;
}

/**
 * Store the given rules' settings; the backend applies all or none.
 * `entries` is a list of `{ code, is_strict, weight }`.
 */
export async function saveConstraints(ambulanceId, entries) {
  const { data } = await client.put(`/ambulances/${ambulanceId}/constraints`, {
    entries,
  });
  return data;
}
