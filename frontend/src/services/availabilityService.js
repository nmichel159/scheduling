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
