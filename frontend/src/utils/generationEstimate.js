import { normalizeWeekdayRequirements } from './competenceRequirements';

/**
 * Estimated duration of one MILP schedule generation.
 *
 * The solver cost is driven by the number of binary decision variables, which
 * is one per (employee, competence they hold, day the competence is staffed).
 * Calibrated against the Phase 4 measurements in PERFORMANCE_OPTIMIZATION_PLAN:
 * 16,200 variables solved end to end in 0.989 s, and the 33/60/100/150-employee
 * runs measured 0.27/0.41/0.61/0.91 s. Both fit t = 0.10 s + 55 us per variable.
 *
 * The estimate is intentionally computed client-side from data the view has
 * already loaded: the manager sees the number before the request is sent, and
 * the confirmation dialog opens without an extra round trip.
 */
const BASE_SECONDS = 0.1;
const SECONDS_PER_VARIABLE = 0.000055;

/**
 * Safety factor applied to the number shown to the manager.
 * The calibration above is a median on a warm local database; the displayed
 * figure must stay believable on a cold, loaded, or contended server, so it
 * deliberately overstates rather than understates the wait.
 */
export const GENERATION_ESTIMATE_SAFETY_FACTOR = 5;

/** Monday-based weekday index, matching the backend's date.weekday(). */
const isoWeekday = (dateObj) => (dateObj.getDay() + 6) % 7;

/**
 * Count the binary decision variables the solver would build.
 *
 * Mirrors the backend variable filter for the two conditions the frontend can
 * see: the employee must hold the competence, and the competence must need
 * somebody that weekday. Absences and cross-ambulance duties shrink the real
 * model further, so this is an upper bound — which is what an estimate wants.
 *
 * @param {Array} employees Rows of {user_id, competences: [{id}]}.
 * @param {Array} competences Ambulance competences with weekday requirements.
 * @param {number} year Four-digit year.
 * @param {number} monthIndex Zero-based month, as held in the view state.
 */
export function countGenerationVariables(employees, competences, year, monthIndex) {
  if (!employees?.length || !competences?.length) return 0;

  const daysInMonth = new Date(year, monthIndex + 1, 0).getDate();
  const staffedDaysByCompetence = new Map();
  competences.forEach((competence) => {
    const byWeekday = new Map(
      normalizeWeekdayRequirements(competence).map((item) => [
        item.weekday,
        item.required_count,
      ])
    );
    let staffedDays = 0;
    for (let day = 1; day <= daysInMonth; day += 1) {
      const weekday = isoWeekday(new Date(year, monthIndex, day));
      if ((byWeekday.get(weekday) ?? 0) > 0) staffedDays += 1;
    }
    staffedDaysByCompetence.set(competence.id, staffedDays);
  });

  return employees.reduce(
    (total, employee) =>
      total +
      (employee.competences || []).reduce(
        (perEmployee, held) =>
          perEmployee + (staffedDaysByCompetence.get(held.id) ?? 0),
        0
      ),
    0
  );
}

/** Raw expected solve time in seconds, before the safety factor. */
export function estimateGenerationSeconds(employees, competences, year, monthIndex) {
  const variables = countGenerationVariables(employees, competences, year, monthIndex);
  if (variables === 0) return 0;
  return BASE_SECONDS + SECONDS_PER_VARIABLE * variables;
}

/** Whole seconds to show the manager: the estimate times the safety factor. */
export function displayedGenerationSeconds(employees, competences, year, monthIndex) {
  const seconds = estimateGenerationSeconds(employees, competences, year, monthIndex);
  if (seconds === 0) return 0;
  return Math.max(1, Math.ceil(seconds * GENERATION_ESTIMATE_SAFETY_FACTOR));
}

/**
 * Render a second count as "8 s" or "2 min".
 * Minutes round up, so the shown figure is never optimistic. Zero is rendered
 * as "0 s" rather than clamped -- the elapsed counter starts there.
 */
export function formatDurationSeconds(seconds, t) {
  if (seconds < 60) {
    return t('schedule_edit.duration_seconds', { value: Math.round(seconds) });
  }
  return t('schedule_edit.duration_minutes', { value: Math.ceil(seconds / 60) });
}
