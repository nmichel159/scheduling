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

/** Fetch all shifts for an ambulance (manager only, current month). */
export async function fetchAmbulanceSchedule(ambulanceId) {
  const { data } = await client.get(`/ambulances/${ambulanceId}/schedule`);
  return data;
}

/** Update the schedule for an ambulance (manager only, bulk sync). */
export async function updateAmbulanceSchedule(ambulanceId, entries) {
  const { data } = await client.put(`/ambulances/${ambulanceId}/schedule`, { entries });
  return data;
}
