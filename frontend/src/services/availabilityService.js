import client from '../api/client';

/**
 * Frontend service for when employees may fill in their restrictions.
 *
 * A month is filled in during the month before it: on the reminder day the
 * server mails the workplace's people, from the lock day on the month is
 * closed to them. Each workplace's scheduler sets both days and can close or
 * open a month by hand; an employee of several workplaces is closed out as
 * soon as any of them closes.
 */

/** Whether one month (1-12) is closed to the signed-in employee. */
export async function fetchMonthStatus(year, month) {
  const { data } = await client.get(`/availability/months/${year}/${month}`);
  return data;
}

/** The workplace's two days with the state of the month being filled in. */
export async function fetchAvailabilityWindow(ambulanceId) {
  const { data } = await client.get(`/ambulances/${ambulanceId}/availability/window`);
  return data;
}

export async function saveAvailabilityWindow(ambulanceId, reminderDay, lockDay) {
  const { data } = await client.put(`/ambulances/${ambulanceId}/availability/window`, {
    reminder_day: reminderDay,
    lock_day: lockDay,
  });
  return data;
}

/** Whether one month (1-12) is closed in the workplace. */
export async function fetchWorkplaceMonthStatus(ambulanceId, year, month) {
  const { data } = await client.get(
    `/ambulances/${ambulanceId}/availability/months/${year}/${month}`
  );
  return data;
}

/** Close (`true`) or open (`false`) one month of the workplace by hand. */
export async function setMonthLock(ambulanceId, year, month, locked) {
  const { data } = await client.put(
    `/ambulances/${ambulanceId}/availability/months/${year}/${month}/lock`,
    { locked }
  );
  return data;
}

/** True when a refused write says the month is closed. */
export function isMonthLockedError(error) {
  return error?.response?.data?.detail?.code === 'month_locked';
}

/** The reasons a day can be limited on, in the order the screens show them. */
export const LIMITED_REASONS = ['VACATION', 'BUSINESS_TRIP', 'UNAVAILABLE'];

/** How many of a workplace's people may have each absence on one day; `null` is no limit. */
export async function fetchDayLimits(ambulanceId) {
  const { data } = await client.get(`/ambulances/${ambulanceId}/availability/day-limits`);
  return data.limits;
}

/** Store the limits; a reason left out keeps its limit, `null` drops it. */
export async function saveDayLimits(ambulanceId, limits) {
  const { data } = await client.put(`/ambulances/${ambulanceId}/availability/day-limits`, {
    limits,
  });
  return data.limits;
}

/** Per day of one month (1-12), how many of a workplace's people entered each reason. */
export async function fetchMonthOverview(ambulanceId, year, month) {
  const { data } = await client.get(
    `/ambulances/${ambulanceId}/availability/overview/${year}/${month}`
  );
  return data;
}

/** One day's (`YYYY-MM-DD`) restrictions of a workplace's people, in entry order. */
export async function fetchDayDetail(ambulanceId, day) {
  const { data } = await client.get(`/ambulances/${ambulanceId}/availability/days/${day}`);
  return data;
}

/** True when a refused write says the day's limit for its reason is used up. */
export function isDayLimitError(error) {
  return error?.response?.data?.detail?.code === 'day_limit_reached';
}
