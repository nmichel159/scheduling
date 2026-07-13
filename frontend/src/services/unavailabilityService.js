import client from '../api/client';

/**
 * Frontend service wrapper for the /unavailabilities API.
 * All dates are ISO strings (YYYY-MM-DD), times are HH:MM strings.
 */

/** Fetch records for the authenticated user within an inclusive date range. */
export async function fetchUnavailabilities(dateFrom, dateTo) {
  const { data } = await client.get('/unavailabilities/', {
    params: { date_from: dateFrom, date_to: dateTo, limit: 500 },
  });
  return data;
}

/** Create a record. Pass null times for an all-day absence. */
export async function createUnavailability({ dateAbsent, startTime, endTime, reason }) {
  const { data } = await client.post('/unavailabilities/', {
    date_absent: dateAbsent,
    start_time: startTime,
    end_time: endTime,
    reason: reason || null,
  });
  return data;
}

/** Update a record. Set clearTimes to switch it to an all-day absence. */
export async function updateUnavailability(id, { startTime, endTime, reason, clearTimes }) {
  const payload = { reason: reason || null };
  if (clearTimes) {
    payload.clear_times = true;
  } else {
    payload.start_time = startTime;
    payload.end_time = endTime;
  }
  const { data } = await client.put(`/unavailabilities/${id}`, payload);
  return data;
}

/** Delete a record permanently. */
export async function deleteUnavailability(id) {
  await client.delete(`/unavailabilities/${id}`);
}

/**
 * Apply a repeating week pattern to a whole month.
 * @param {number} year Target year.
 * @param {number} month Target month (1-12).
 * @param {Array<{weekday: number, startTime: string, endTime: string}>} pattern Weekday windows (0=Monday).
 * @param {boolean} overwrite Replace already filled days.
 */
export async function applyPattern(year, month, pattern, overwrite) {
  const { data } = await client.post('/unavailabilities/apply-pattern', {
    year,
    month,
    overwrite,
    pattern: pattern.map((p) => ({
      weekday: p.weekday,
      start_time: p.startTime,
      end_time: p.endTime,
    })),
  });
  return data;
}
