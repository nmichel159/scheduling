import client from '../api/client';

/**
 * Frontend service for the scheduler's view of one workplace's people.
 *
 * Two things live here that the competence table does not answer: how
 * loaded each employee already is in a given month, and what they would
 * rather be given. The load call returns both in one response — the
 * per-day duties the schedule tab draws and the totals the load tab
 * counts — so switching tabs never refetches.
 *
 * Surcharge is decided on the backend from the workplace's selected
 * scenario and its special-day calendar, not here: the screen must agree
 * with what the generator worked with.
 */

/** Which kinds of duty an employee can prefer. */
export const SHIFT_PREFERENCE = {
  SURCHARGE: 'surcharge',
  STANDARD: 'standard',
  ANY: 'any',
};

/** Load every employee of a workplace with their duties in one month. */
export async function fetchEmployeeLoad(ambulanceId, month, year) {
  const { data } = await client.get(`/ambulances/${ambulanceId}/employees/load`, {
    params: { month, year },
  });
  return data;
}

/** Read one employee's duty wish and duty-kind preference. */
export async function fetchEmployeeSettings(ambulanceId, userId) {
  const { data } = await client.get(
    `/ambulances/${ambulanceId}/employees/${userId}/settings`
  );
  return data;
}

/** Store one employee's duty wish and duty-kind preference. */
export async function saveEmployeeSettings(ambulanceId, userId, settings) {
  const { data } = await client.put(
    `/ambulances/${ambulanceId}/employees/${userId}/settings`,
    {
      max_shifts_per_month: settings.max_shifts_per_month,
      shift_preference: settings.shift_preference,
    }
  );
  return data;
}
