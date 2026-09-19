export const ISO_WEEKDAYS = [0, 1, 2, 3, 4, 5, 6];

export const legacyRequiredCount = (column) =>
  Math.max(0, Number(column.required_count ?? column.count ?? 1));

/** Days of rest a duty costs when the record does not say. One day off means
 *  a Monday duty frees its holder again on Wednesday. */
export const DEFAULT_RECOVERY_DAYS = 1;

/** Hours a duty lasts when the record does not say. */
export const DEFAULT_SHIFT_HOURS = 4;

/** Longest a single duty may last. */
export const MAX_SHIFT_HOURS = 24;

export const clampShiftHours = (value) => {
  const hours = Math.round(Number(value) * 4) / 4;
  if (!Number.isFinite(hours)) return DEFAULT_SHIFT_HOURS;
  return Math.min(MAX_SHIFT_HOURS, Math.max(0, hours));
};

/** Weekdays a duty is paid with a surcharge unless the editor says
 *  otherwise. Surcharge follows the day, not the competence: the same duty
 *  is ordinary on a Tuesday and surcharged on a Sunday. */
export const DEFAULT_SURCHARGE_WEEKDAYS = [5, 6];

export const defaultIsSurcharge = (weekday) =>
  DEFAULT_SURCHARGE_WEEKDAYS.includes(Number(weekday));

/** Largest rest a duty may cost — a full week minus the duty day itself. */
export const MAX_RECOVERY_DAYS = 6;

export const clampRecoveryDays = (value) => {
  const days = Math.round(Number(value));
  if (!Number.isFinite(days)) return DEFAULT_RECOVERY_DAYS;
  return Math.min(MAX_RECOVERY_DAYS, Math.max(0, days));
};

/** The weekday a duty started on `weekday` frees its holder again. */
export const recoveryTargetWeekday = (weekday, recoveryDays) =>
  (weekday + clampRecoveryDays(recoveryDays) + 1) % 7;

/** Inverse of `recoveryTargetWeekday`: rest implied by clicking a day. */
export const recoveryDaysForTarget = (weekday, targetWeekday) =>
  (targetWeekday - weekday + 6) % 7;

/** Return a complete, sorted weekly definition for old and new API records. */
export const normalizeWeekdayRequirements = (column) => {
  const configured = new Map(
    (column.weekday_requirements || []).map((item) => [
      Number(item.weekday),
      {
        required_count: Math.max(0, Number(item.required_count)),
        recovery_days: clampRecoveryDays(
          item.recovery_days ?? DEFAULT_RECOVERY_DAYS
        ),
        shift_hours: clampShiftHours(item.shift_hours ?? DEFAULT_SHIFT_HOURS),
        is_surcharge:
          item.is_surcharge ?? defaultIsSurcharge(Number(item.weekday)),
      },
    ])
  );
  const fallback = legacyRequiredCount(column);
  return ISO_WEEKDAYS.map((weekday) => ({
    weekday,
    required_count: configured.get(weekday)?.required_count ?? fallback,
    recovery_days:
      configured.get(weekday)?.recovery_days ?? DEFAULT_RECOVERY_DAYS,
    shift_hours: configured.get(weekday)?.shift_hours ?? DEFAULT_SHIFT_HOURS,
    is_surcharge:
      configured.get(weekday)?.is_surcharge ?? defaultIsSurcharge(weekday),
  }));
};

export const normalizeCompetenceRequirements = (column) => ({
  ...column,
  weekday_requirements: normalizeWeekdayRequirements(column),
});

const requirementMap = (column) =>
  new Map(
    normalizeWeekdayRequirements(column).map((item) => [
      item.weekday,
      item.required_count,
    ])
  );

/** Drop emptied groups and order everything by the first day it covers, so
 *  the rows always read Mon -> Sun no matter how they were assembled. */
const sortDayGroups = (groups) =>
  groups
    .filter((group) => group.weekdays.length > 0)
    .map((group) => ({
      ...group,
      weekdays: [...new Set(group.weekdays)].sort((a, b) => a - b),
    }))
    .sort((a, b) => a.weekdays[0] - b.weekdays[0]);

const signatureForWeekday = (columns, weekday) =>
  [...columns]
    .sort((a, b) => a.id - b.id)
    .map((column) => `${column.id}:${requirementMap(column).get(weekday)}`)
    .join('|');

/** Collapse weekdays whose complete competence-demand vectors are identical. */
export const groupWeekdaysByRequirements = (columns) => {
  if (columns.length === 0) return [];
  const bySignature = new Map();
  ISO_WEEKDAYS.forEach((weekday) => {
    const signature = signatureForWeekday(columns, weekday);
    const current = bySignature.get(signature);
    if (current) current.weekdays.push(weekday);
    else {
      bySignature.set(signature, {
        id: `days-${weekday}`,
        weekdays: [weekday],
      });
    }
  });
  return sortDayGroups([...bySignature.values()]);
};

/** Merge existing UI groups when their current demand vectors become equal. */
export const mergeEquivalentDayGroups = (groups, columns) => {
  const merged = new Map();
  groups
    .filter((group) => group.weekdays.length > 0)
    .forEach((group) => {
      const signature = signatureForWeekday(columns, group.weekdays[0]);
      const current = merged.get(signature);
      if (current) current.weekdays.push(...group.weekdays);
      else merged.set(signature, { ...group, weekdays: [...group.weekdays] });
    });
  return sortDayGroups([...merged.values()]);
};

/** Apply one group's edited count to each of its weekdays. */
export const updateGroupRequiredCount = (
  columns,
  competenceId,
  weekdays,
  requiredCount
) => {
  const weekdaySet = new Set(weekdays);
  return columns.map((column) => {
    if (column.id !== competenceId) return column;
    return {
      ...column,
      weekday_requirements: normalizeWeekdayRequirements(column).map((item) =>
        weekdaySet.has(item.weekday)
          ? { ...item, required_count: Math.max(0, Number(requiredCount)) }
          : item
      ),
    };
  });
};

/** Pull `weekdays` out of whatever groups hold them into one new group.
 *
 *  Unlike a plain split this can gather days that currently live in
 *  different groups, so the days it collects may disagree on their counts.
 *  `sourceWeekday` — the day the user clicked first — settles that: every
 *  collected day inherits that day's count for every competence, which is
 *  also what makes the new group internally consistent and therefore a
 *  single row. Groups left without any day disappear.
 *
 *  Returns both halves of the change because the grouping (UI-only) and the
 *  counts (persisted) have to move together.
 */
export const extractDayGroup = (groups, columns, weekdays, sourceWeekday) => {
  const selected = [...new Set(weekdays)].sort((a, b) => a - b);
  if (selected.length === 0 || sourceWeekday === null || sourceWeekday === undefined) {
    return { groups, columns };
  }
  const selectedSet = new Set(selected);
  const nextGroups = sortDayGroups([
    ...groups.map((group) => ({
      ...group,
      weekdays: group.weekdays.filter((weekday) => !selectedSet.has(weekday)),
    })),
    { id: `days-${selected.join('-')}-${Date.now()}`, weekdays: selected },
  ]);
  const nextColumns = columns.map((column) => {
    const inherited =
      requirementMap(column).get(sourceWeekday) ?? legacyRequiredCount(column);
    return {
      ...column,
      weekday_requirements: normalizeWeekdayRequirements(column).map((item) =>
        selectedSet.has(item.weekday)
          ? { ...item, required_count: inherited }
          : item
      ),
    };
  });
  return { groups: nextGroups, columns: nextColumns };
};

export const requiredCountForGroup = (column, group) => {
  const byWeekday = requirementMap(column);
  return byWeekday.get(group.weekdays[0]) ?? legacyRequiredCount(column);
};

/** Semantic fingerprint: UI grouping itself is irrelevant, per-day values are not. */
export const fingerprintCompetenceRequirements = (columns) =>
  JSON.stringify(
    [...columns]
      .map((column) => ({
        id: column.id,
        weekday_requirements: normalizeWeekdayRequirements(column),
      }))
      .sort((a, b) => a.id - b.id)
  );
