import client from '../api/client';

/**
 * Frontend service for when employees may fill in their restrictions.
 *
 * A month is filled in during the month before it: on the reminder day the
 * server mails everybody, from the lock day on the month is closed to the
 * employees. The scheduler sets both days and can close or open the month
 * being filled in by hand.
 */

/** Whether one month (1-12) is closed to the employee. */
export async function fetchMonthStatus(year, month) {
  const { data } = await client.get(`/availability/months/${year}/${month}`);
  return data;
}

/** The scheduler's two days with the state of the month being filled in. */
export async function fetchAvailabilityWindow() {
  const { data } = await client.get('/availability/window');
  return data;
}

export async function saveAvailabilityWindow(reminderDay, lockDay) {
  const { data } = await client.put('/availability/window', {
    reminder_day: reminderDay,
    lock_day: lockDay,
  });
  return data;
}

/** Close (`true`) or open (`false`) one month by hand. */
export async function setMonthLock(year, month, locked) {
  const { data } = await client.put(`/availability/months/${year}/${month}/lock`, {
    locked,
  });
  return data;
}

/** True when a refused write says the month is closed. */
export function isMonthLockedError(error) {
  return error?.response?.data?.detail?.code === 'month_locked';
}

/** The reasons a day can be limited on, in the order the screens show them. */
export const LIMITED_REASONS = ['VACATION', 'BUSINESS_TRIP', 'UNAVAILABLE'];

/** How many people may have each absence on one day; `null` is no limit. */
export async function fetchDayLimits() {
  const { data } = await client.get('/availability/day-limits');
  return data.limits;
}

/** Store the limits; a reason left out keeps its limit, `null` drops it. */
export async function saveDayLimits(limits) {
  const { data } = await client.put('/availability/day-limits', { limits });
  return data.limits;
}

/** Per day of one month (1-12), how many people entered each reason. */
export async function fetchMonthOverview(year, month) {
  const { data } = await client.get(`/availability/overview/${year}/${month}`);
  return data;
}

/** One day's (`YYYY-MM-DD`) restrictions in the order they were entered. */
export async function fetchDayDetail(day) {
  const { data } = await client.get(`/availability/days/${day}`);
  return data;
}

/** True when a refused write says the day's limit for its reason is used up. */
export function isDayLimitError(error) {
  return error?.response?.data?.detail?.code === 'day_limit_reached';
}
