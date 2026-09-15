import client from '../api/client';

/**
 * Frontend service wrapper for the /statistics API (role level >= 4).
 *
 * The endpoint returns aggregates only — counts per workplace, per month and
 * per employee — never the individual duties behind them, so the payload stays
 * small no matter how large the schedules are.
 */

/**
 * Duty statistics for one calendar year.
 *
 * `ambulanceId` narrows every figure — totals, the monthly series and the
 * employee ranking — to that one workplace; omit it for the whole hospital.
 */
export async function fetchYearlyStatistics(year, ambulanceId = null) {
  const { data } = await client.get('/statistics/yearly', {
    params: { year, ambulance_id: ambulanceId ?? undefined },
  });
  return data;
}
