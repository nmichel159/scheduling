import client from '../api/client';

/**
 * Frontend service wrapper for the /schedules API.
 *
 * NOTE: GET /schedules/me is currently fixed to the running month —
 * schedule_service.current_month_range() decides the window server-side and
 * the endpoint takes no query parameters. The `params` argument below is a
 * placeholder: once the backend accepts year/month (or date_from/date_to),
 * ScheduleView can pass them and month navigation starts working without any
 * other change here.
 */

/** Fetch the authenticated user's own shifts (current month). */
export async function fetchMySchedule(params = {}) {
  const { data } = await client.get('/schedules/me', { params });
  return data;
}

/**
 * Fetch all shifts for an ambulance (manager only).
 * The backend groups entries per employee ({user_id, user_full_name, entries});
 * flatten them into a single list of shifts for the calendar.
 */
export async function fetchAmbulanceSchedule(ambulanceId, params = {}) {
  const { data } = await client.get(`/ambulances/${ambulanceId}/schedule`, { params });
  return data.flatMap((employee) => employee.entries || []);
}

/**
 * Update the schedule for an ambulance (manager only, bulk sync).
 * Persisting here also updates each employee's personal schedule —
 * both views read the same schedule entries.
 */
export async function updateAmbulanceSchedule(ambulanceId, entries, params = {}) {
  const { data } = await client.put(`/ambulances/${ambulanceId}/schedule`, { entries }, { params });
  return data;
}