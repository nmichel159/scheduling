import client from '../api/client';

/**
 * Frontend service wrapper for the /unavailabilities API.
 *
 * A record marks a whole day the user has an opinion about for
 * emergency-duty scheduling. Dates are ISO strings (YYYY-MM-DD).
 *
 * THREE-STATE MARKING
 * -------------------
 * The backend table currently stores only `date_absent` + a free-text
 * `reason`, so the meaning of a day is encoded into `reason`:
 *
 *   no record             -> DAY_STATE.NONE       (neutral, grey)
 *   reason != PREFERRED   -> DAY_STATE.BLOCKED    (does not suit me, red)
 *   reason === PREFERRED  -> DAY_STATE.PREFERRED  (I'd like this day, green)
 *
 * A dedicated enum/boolean column on the backend would be cleaner — worth
 * flagging with the backend owner. Until then this keeps the feature
 * frontend-only and stays backward compatible: records written before this
 * change have a null reason and therefore read back as BLOCKED, which is
 * exactly what they meant.
 */

export const DAY_STATE = {
  NONE: 'none',
  BLOCKED: 'blocked',
  PREFERRED: 'preferred',
};

/** Sentinel values written into the `reason` column. */
export const REASON_BLOCKED = 'UNAVAILABLE';
export const REASON_PREFERRED = 'PREFERRED';

/** Map a server record onto one of the three UI states. */
export function stateOfRecord(record) {
  if (!record) return DAY_STATE.NONE;
  return record.reason === REASON_PREFERRED ? DAY_STATE.PREFERRED : DAY_STATE.BLOCKED;
}

/** Fetch records for the authenticated user within an inclusive date range. */
export async function fetchUnavailabilities(dateFrom, dateTo) {
  const { data } = await client.get('/unavailabilities/', {
    params: { date_from: dateFrom, date_to: dateTo, limit: 500 },
  });
  return data;
}

/** Create a record for a day. */
export async function createUnavailability(dateAbsent, reason = REASON_BLOCKED) {
  const { data } = await client.post('/unavailabilities/', {
    date_absent: dateAbsent,
    reason,
  });
  return data;
}

/** Change an existing record's reason (flips blocked <-> preferred). */
export async function updateUnavailability(id, reason) {
  const { data } = await client.put(`/unavailabilities/${id}`, { reason });
  return data;
}

/** Remove a day's mark entirely. */
export async function deleteUnavailability(id) {
  await client.delete(`/unavailabilities/${id}`);
}