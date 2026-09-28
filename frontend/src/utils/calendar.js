/**
 * Calendar helpers shared by the month views (dashboard, "my schedule",
 * restrictions). They all lay a month out the same way — Monday first, blank
 * cells before the 1st and after the last day — so the arithmetic lives here
 * once instead of in every view.
 */

/** Zero-pad a number to two digits. */
export const pad = (n) => String(n).padStart(2, '0');

/** `YYYY-MM-DD` for a local date, built by hand: `toISOString` goes through
 *  UTC and would shift a day either side of midnight. `monthIndex` is 0-11. */
export const isoDate = (year, monthIndex, day) => `${year}-${pad(monthIndex + 1)}-${pad(day)}`;

/** ISO weekday index: 0 = Monday ... 6 = Sunday (matches `workload.days.*`). */
export const isoWeekday = (date) => (date.getDay() + 6) % 7;

/** Flat array of day numbers for a month grid; null is a filler cell. */
export function buildMonthCells(year, monthIndex) {
  const cells = Array(isoWeekday(new Date(year, monthIndex, 1))).fill(null);
  const daysInMonth = new Date(year, monthIndex + 1, 0).getDate();
  for (let day = 1; day <= daysInMonth; day += 1) cells.push(day);
  while (cells.length % 7 !== 0) cells.push(null);
  return cells;
}

/** The Intl locale for the app language. */
export const localeFor = (language) => (language === 'en' ? 'en-GB' : 'sk-SK');

/** Upper-case the first letter only. Slovak writes month and weekday names in
 *  lower case, so `text-transform: capitalize` (every word) would turn
 *  "streda 30. septembra" into "Streda 30. Septembra". */
export const capitalizeFirst = (text) =>
  text ? text.charAt(0).toLocaleUpperCase() + text.slice(1) : text;
