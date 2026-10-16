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
      max_surcharge_shifts_per_month: settings.max_surcharge_shifts_per_month,
      shift_preference: settings.shift_preference,
      scheduling_active: settings.scheduling_active,
      is_vip: settings.is_vip,
    }
  );
  return data;
}

/** Create a new account and add it to the workplace in one step. */
export async function createEmployeeAccount(ambulanceId, account) {
  const { data } = await client.post(`/ambulances/${ambulanceId}/employees/accounts`, {
    first_name: account.first_name,
    last_name: account.last_name,
    email: account.email,
  });
  return data;
}

/** Change one employee's name and e-mail. */
export async function updateEmployeeProfile(ambulanceId, userId, profile) {
  const { data } = await client.put(
    `/ambulances/${ambulanceId}/employees/${userId}/profile`,
    { full_name: profile.full_name, email: profile.email }
  );
  return data;
}
