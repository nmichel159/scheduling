import client from '../api/client';

/**
 * Frontend service wrapper for the /unavailabilities API.
 * An unavailability record marks a whole day that does not suit
 * the user for emergency duty. Dates are ISO strings (YYYY-MM-DD).
 */

/** Fetch records for the authenticated user within an inclusive date range. */
export async function fetchUnavailabilities(dateFrom, dateTo) {
  const { data } = await client.get('/unavailabilities/', {
    params: { date_from: dateFrom, date_to: dateTo, limit: 500 },
  });
  return data;
}

/** Mark a day as unavailable. */
export async function createUnavailability(dateAbsent, reason = null) {
  const { data } = await client.post('/unavailabilities/', {
    date_absent: dateAbsent,
    reason,
  });
  return data;
}

/** Remove an unavailability mark. */
export async function deleteUnavailability(id) {
  await client.delete(`/unavailabilities/${id}`);
}
