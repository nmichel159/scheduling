import client from '../api/client';

/**
 * Frontend service wrapper for the /unavailabilities API.
 *
 * A record marks a whole day the user has an opinion about for
 * emergency-duty scheduling. Dates are ISO strings (YYYY-MM-DD).
 *
 * DAY STATES
 * ----------
 * The backend table stores only `date_absent` + a free-text `reason`, so the
 * meaning of a day is encoded into `reason`:
 *
 *   no record        -> NONE           neutral, grey
 *   PREFERRED        -> PREFERRED      "I want this day"      (soft, rewarded)
 *   SOFT_DECLINE     -> SOFT_DECLINE   "I would rather not"   (soft, penalized)
 *   UNAVAILABLE      -> UNAVAILABLE    "I cannot"             (hard block)
 *   VACATION         -> VACATION       leave                  (hard block)
 *   BUSINESS_TRIP    -> BUSINESS_TRIP  business trip          (hard block)
 *
 * Only the two soft states are wishes; the rest stop the solver from
 * scheduling the day at all. Anything unrecognized — including the null
 * reason older records were written with — reads back as UNAVAILABLE, which
 * is exactly what those records meant.
 *
 * A dedicated enum column on the backend would be cleaner — worth flagging
 * with the backend owner. Until then this keeps the mapping in one place.
 */

export const DAY_STATE = {
  NONE: 'none',
  PREFERRED: 'preferred',
  SOFT_DECLINE: 'soft-decline',
  UNAVAILABLE: 'unavailable',
  VACATION: 'vacation',
  BUSINESS_TRIP: 'business-trip',
};

/** Sentinel values written into the `reason` column, keyed by day state. */
export const REASON_BY_STATE = {
  [DAY_STATE.PREFERRED]: 'PREFERRED',
  [DAY_STATE.SOFT_DECLINE]: 'SOFT_DECLINE',
  [DAY_STATE.UNAVAILABLE]: 'UNAVAILABLE',
  [DAY_STATE.VACATION]: 'VACATION',
  [DAY_STATE.BUSINESS_TRIP]: 'BUSINESS_TRIP',
};

const STATE_BY_REASON = Object.fromEntries(
  Object.entries(REASON_BY_STATE).map(([state, reason]) => [reason, state])
);

/** The states a day can be set to, in the order the picker offers them. */
export const MARKABLE_STATES = [
  DAY_STATE.PREFERRED,
  DAY_STATE.SOFT_DECLINE,
  DAY_STATE.UNAVAILABLE,
  DAY_STATE.VACATION,
  DAY_STATE.BUSINESS_TRIP,
];

/** What an unmarked day becomes when a caller names no reason. */
const REASON_BLOCKED = REASON_BY_STATE[DAY_STATE.UNAVAILABLE];

/** Map a server record onto one of the day states. */
export function stateOfRecord(record) {
  if (!record) return DAY_STATE.NONE;
  const reason = (record.reason || '').trim().toUpperCase();
  return STATE_BY_REASON[reason] || DAY_STATE.UNAVAILABLE;
}

/** Fetch records for the authenticated user within an inclusive date range. */
export async function fetchUnavailabilities(dateFrom, dateTo) {
  const { data } = await client.get('/unavailabilities', {
    params: { date_from: dateFrom, date_to: dateTo, limit: 500 },
  });
  return data;
}

/** Create a record for a day. */
export async function createUnavailability(dateAbsent, reason = REASON_BLOCKED) {
  const { data } = await client.post('/unavailabilities', {
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

/* ---------- monthly duty wish ---------- */

/** How many duties a month the user wants at most (null = no opinion). */
export async function fetchMonthlyWish() {
  const { data } = await client.get('/unavailabilities/monthly-wish');
  return data.max_shifts_per_month ?? null;
}

export async function saveMonthlyWish(maxShiftsPerMonth) {
  const { data } = await client.put('/unavailabilities/monthly-wish', {
    max_shifts_per_month: maxShiftsPerMonth,
  });
  return data.max_shifts_per_month ?? null;
}
