import client from '../api/client';

/**
 * Frontend service wrapper for the /statistics API (role level >= 4).
 *
 * The endpoint returns aggregates only — counts per workplace, per month and
 * per employee — never the individual duties behind them, so the payload stays
 * small no matter how large the schedules are.
 */

/** Hospital-wide duty statistics for one calendar year. */
export async function fetchYearlyStatistics(year) {
  const { data } = await client.get('/statistics/yearly', { params: { year } });
  return data;
}
