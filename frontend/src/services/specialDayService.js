import client from '../api/client';

/**
 * Frontend service for the special-day calendar of one workplace.
 *
 * Which dates are days of rest is answered by the Slovak public-holiday
 * library on the backend, so there is nothing to upload and nothing to keep
 * in step year by year. What these calls write are one workplace's
 * exceptions: a day it closes although the library works it, or a day it
 * staffs although the library rests it.
 *
 * Every write answers with the whole year, because one write can also erase
 * an override — setting a date back to what the library says removes it —
 * and the screen would otherwise have to guess which rows moved.
 */

/** Load one workplace's special-day calendar for a year. */
export async function fetchSpecialDays(ambulanceId, year) {
  const { data } = await client.get(`/ambulances/${ambulanceId}/special-days`, {
    params: { year },
  });
  return data;
}

/**
 * Mark a date as a day of rest or as worked.
 * `day` is an ISO date string (YYYY-MM-DD).
 */
export async function setSpecialDay(ambulanceId, day, isRestDay, name = null) {
  const { data } = await client.put(`/ambulances/${ambulanceId}/special-days`, {
    day,
    is_rest_day: isRestDay,
    name,
  });
  return data;
}

/** Drop this workplace's override for a date, whichever way it pointed. */
export async function clearSpecialDay(ambulanceId, day) {
  const { data } = await client.delete(
    `/ambulances/${ambulanceId}/special-days/${day}`
  );
  return data;
}

/** Replace this workplace's year with another workplace's overrides. */
export async function copySpecialDays(ambulanceId, sourceAmbulanceId, year) {
  const { data } = await client.post(
    `/ambulances/${ambulanceId}/special-days/copy`,
    { source_ambulance_id: sourceAmbulanceId, year }
  );
  return data;
}
