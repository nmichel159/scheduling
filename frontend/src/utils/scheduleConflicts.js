/**
 * Every rule a month on screen breaks, worked out from what the planner holds.
 *
 * The planner lets a manager put anybody anywhere -- somebody without the
 * competence, on a day they are away, into a second role the same day, onto a
 * day their last duty still holds in rest. None of that is refused; all of it
 * is found here and shown where it happens. The rules are the ones the solver
 * keeps (backend/app/services/schedule_generation_service.py), read the same
 * way: a date the workplace rests on is staffed and rested from the
 * competence's day-of-rest slot, not from its weekday.
 *
 * What the planner cannot see by itself -- absences, duties at other
 * workplaces and at this one just outside the month, the monthly wish --
 * comes from GET /ambulances/{id}/schedule/context. Without it the checks
 * that need it are simply skipped.
 */

import {
  DEFAULT_RECOVERY_DAYS,
  SPECIAL_DAY_SLOT,
  normalizeWeekdayRequirements,
} from './competenceRequirements';

/** Conflict types, in the order the planner lists them. */
export const CONFLICT_TYPES = [
  'unqualified',
  'unavailable',
  'double_role',
  'other_workplace',
  'rest',
  'understaffed',
  'overstaffed',
  'over_wish',
  'soft_decline',
];

/** Rules the solver never breaks on its own are errors; wishes and a surplus are warnings. */
export const CONFLICT_SEVERITY = {
  unqualified: 'error',
  unavailable: 'error',
  double_role: 'error',
  other_workplace: 'error',
  rest: 'error',
  understaffed: 'error',
  overstaffed: 'warning',
  over_wish: 'warning',
  soft_decline: 'warning',
};

/** Kinds that are about a day's head-count rather than about a person. */
export const COVERAGE_CONFLICT_TYPES = new Set(['understaffed', 'overstaffed']);

export const SOFT_DECLINE_REASON = 'SOFT_DECLINE';

const DAY_MS = 86400000;
const pad = (n) => String(n).padStart(2, '0');

/** Whole days since the epoch, so two ISO dates can be subtracted. */
const dayNumber = (iso) => {
  const [y, m, d] = iso.split('-').map(Number);
  return Math.round(Date.UTC(y, m - 1, d) / DAY_MS);
};

const isoWeekday = (iso) => {
  const [y, m, d] = iso.split('-').map(Number);
  return (new Date(y, m - 1, d).getDay() + 6) % 7;
};

export const personCellKey = (userId, dateStr) => `${userId}|${dateStr}`;
export const demandCellKey = (dateStr, competenceId) => `${dateStr}|${competenceId}`;

const push = (map, key, value) => {
  const list = map.get(key);
  if (list) list.push(value);
  else map.set(key, [value]);
};

const worstSeverity = (conflicts) =>
  conflicts.some((conflict) => conflict.severity === 'error') ? 'error' : 'warning';

/** 'error' when any of the conflicts is one, 'warning' otherwise, null for none. */
export const severityOf = (conflicts) =>
  conflicts && conflicts.length > 0 ? worstSeverity(conflicts) : null;

/**
 * @param {object} input
 * @param {number} input.year
 * @param {number} input.month 0-11
 * @param {number} input.ambulanceId the workplace on screen
 * @param {Array} input.shifts the month's duties as edited
 * @param {Array} input.employees [{ user_id, competences: [{ id }] }]
 * @param {Array} input.competences the workplace's competences with their slots
 * @param {Set<string>} input.restDays ISO dates the workplace rests on
 * @param {object|null} input.context GET .../schedule/context, or null
 */
export function analyzeScheduleConflicts({
  year,
  month,
  ambulanceId,
  shifts,
  employees,
  competences,
  restDays,
  context,
  fromDate = null,
  editedDates = null,
}) {
  const slotsById = new Map(
    competences.map((competence) => [
      competence.id,
      normalizeWeekdayRequirements(competence),
    ])
  );
  const slotOf = (dateStr) =>
    restDays?.has(dateStr) ? SPECIAL_DAY_SLOT : isoWeekday(dateStr);
  const recoveryOf = (competenceId, dateStr) =>
    slotsById.get(competenceId)?.[slotOf(dateStr)]?.recovery_days ??
    DEFAULT_RECOVERY_DAYS;
  const requiredOf = (competenceId, dateStr) =>
    slotsById.get(competenceId)?.[slotOf(dateStr)]?.required_count ?? 0;

  const heldBy = new Map(
    employees.map((employee) => [
      employee.user_id,
      new Set((employee.competences || []).map((c) => c.id)),
    ])
  );

  const contextByUser = new Map(
    (context?.employees || []).map((entry) => [entry.user_id, entry])
  );
  const marksByUser = new Map();
  contextByUser.forEach((entry, userId) => {
    marksByUser.set(
      userId,
      new Map((entry.marks || []).map((mark) => [mark.work_date, mark.reason]))
    );
  });

  /* Every duty that can collide with one on screen, per person: the ones on
     screen themselves, and from the context the ones at other workplaces and
     at this one outside the month. Sorted by date, so a rest is only looked
     for forwards. */
  const dutiesByUser = new Map();
  shifts.forEach((shift) => {
    if (shift.user_id == null || shift.competence_id == null) return;
    push(dutiesByUser, shift.user_id, {
      dateStr: shift.work_date,
      day: dayNumber(shift.work_date),
      recovery: recoveryOf(shift.competence_id, shift.work_date),
      competenceId: shift.competence_id,
      shift,
      elsewhere: null,
    });
  });
  contextByUser.forEach((entry, userId) => {
    (entry.duties || []).forEach((duty) => {
      push(dutiesByUser, userId, {
        dateStr: duty.work_date,
        day: dayNumber(duty.work_date),
        recovery: duty.recovery_days ?? DEFAULT_RECOVERY_DAYS,
        competenceId: duty.competence_id,
        shift: null,
        elsewhere:
          duty.ambulance_id === ambulanceId
            ? null
            : { id: duty.ambulance_id, name: duty.ambulance_name || '' },
      });
    });
  });
  dutiesByUser.forEach((list) => list.sort((a, b) => a.day - b.day));

  const ownCount = new Map();
  shifts.forEach((shift) => {
    ownCount.set(shift.user_id, (ownCount.get(shift.user_id) || 0) + 1);
  });

  const conflicts = [];
  const add = (type, fields) => {
    conflicts.push({
      key: `${type}|${fields.key}`,
      type,
      severity: CONFLICT_SEVERITY[type],
      shifts: [],
      cells: [],
      demandCells: [],
      rows: [],
      ...fields,
    });
  };
  const cellsOf = (list) =>
    list.map((shift) => personCellKey(shift.user_id, shift.work_date));
  const demandCellsOf = (list) =>
    list.map((shift) => demandCellKey(shift.work_date, shift.competence_id));

  /* ---------- per duty ---------- */

  shifts.forEach((shift) => {
    const held = heldBy.get(shift.user_id);
    if (!held || !held.has(shift.competence_id)) {
      add('unqualified', {
        key: `${shift.user_id}|${shift.work_date}|${shift.competence_id}`,
        date: shift.work_date,
        userId: shift.user_id,
        competenceId: shift.competence_id,
        shifts: [shift],
        cells: cellsOf([shift]),
        demandCells: demandCellsOf([shift]),
      });
    }
  });

  /* ---------- per person and day ---------- */

  const shiftsByUserDate = new Map();
  shifts.forEach((shift) => push(shiftsByUserDate, personCellKey(shift.user_id, shift.work_date), shift));

  shiftsByUserDate.forEach((dayShifts, cellKey) => {
    const { user_id: userId, work_date: dateStr } = dayShifts[0];
    const reason = marksByUser.get(userId)?.get(dateStr);
    const common = {
      key: cellKey,
      date: dateStr,
      userId,
      shifts: dayShifts,
      cells: [cellKey],
      demandCells: demandCellsOf(dayShifts),
    };
    if (reason && reason !== SOFT_DECLINE_REASON) {
      add('unavailable', { ...common, reason });
    } else if (reason === SOFT_DECLINE_REASON) {
      add('soft_decline', common);
    }
    if (dayShifts.length > 1) {
      add('double_role', {
        ...common,
        competenceIds: dayShifts.map((shift) => shift.competence_id),
      });
    }
  });

  /* ---------- between duties: the same day elsewhere, and the rest ---------- */

  dutiesByUser.forEach((duties, userId) => {
    const sameDayElsewhere = new Map();
    const restPairs = new Map();
    duties.forEach((first, index) => {
      for (let next = index + 1; next < duties.length; next += 1) {
        const second = duties[next];
        if (second.day - first.day > first.recovery) break;
        if (!first.shift && !second.shift) continue; // nothing on screen
        if (second.day === first.day) {
          // Two duties here the same day are a double role, found above.
          if (first.shift && second.shift) continue;
          const own = first.shift ? first : second;
          const other = first.shift ? second : first;
          if (!other.elsewhere) continue;
          const entry = sameDayElsewhere.get(own.dateStr) || {
            shifts: new Set(),
            workplaces: new Map(),
          };
          entry.shifts.add(own.shift);
          entry.workplaces.set(other.elsewhere.id, other.elsewhere.name);
          sameDayElsewhere.set(own.dateStr, entry);
          continue;
        }
        const pairKey = `${first.dateStr}|${second.dateStr}`;
        const entry = restPairs.get(pairKey) || {
          firstDate: first.dateStr,
          secondDate: second.dateStr,
          shifts: new Set(),
          workplaces: new Map(),
        };
        [first, second].forEach((duty) => {
          if (duty.shift) entry.shifts.add(duty.shift);
          if (duty.elsewhere) entry.workplaces.set(duty.elsewhere.id, duty.elsewhere.name);
        });
        restPairs.set(pairKey, entry);
      }
    });

    sameDayElsewhere.forEach((entry, dateStr) => {
      const list = [...entry.shifts];
      add('other_workplace', {
        key: personCellKey(userId, dateStr),
        date: dateStr,
        userId,
        workplaces: [...entry.workplaces.values()],
        shifts: list,
        cells: [personCellKey(userId, dateStr)],
        demandCells: demandCellsOf(list),
      });
    });
    restPairs.forEach((entry, pairKey) => {
      const list = [...entry.shifts];
      add('rest', {
        key: `${userId}|${pairKey}`,
        date: list[0]?.work_date ?? entry.firstDate,
        userId,
        firstDate: entry.firstDate,
        secondDate: entry.secondDate,
        workplaces: [...entry.workplaces.values()],
        shifts: list,
        cells: [...new Set(cellsOf(list))],
        demandCells: demandCellsOf(list),
      });
    });
  });

  /* ---------- per person and month ---------- */

  contextByUser.forEach((entry, userId) => {
    const max = entry.max_shifts_per_month;
    const count = ownCount.get(userId) || 0;
    // Zero or nothing entered means no limit.
    if (max && count > max) {
      const list = dutiesByUser.get(userId)?.filter((duty) => duty.shift) || [];
      add('over_wish', {
        key: String(userId),
        date: null,
        userId,
        count,
        max,
        shifts: list.map((duty) => duty.shift),
        rows: [userId],
      });
    }
  });

  /* ---------- per day and competence ---------- */

  const filledByCell = new Map();
  shifts.forEach((shift) => {
    const key = demandCellKey(shift.work_date, shift.competence_id);
    filledByCell.set(key, (filledByCell.get(key) || 0) + 1);
  });
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  for (let day = 1; day <= daysInMonth; day += 1) {
    const dateStr = `${year}-${pad(month + 1)}-${pad(day)}`;
    competences.forEach((competence) => {
      const key = demandCellKey(dateStr, competence.id);
      const required = requiredOf(competence.id, dateStr);
      const filled = filledByCell.get(key) || 0;
      if (filled === required) return;
      add(filled < required ? 'understaffed' : 'overstaffed', {
        key,
        // Zero is a hard "nobody works this role today"; a surplus over a
        // real count is only a penalty.
        ...(required === 0 ? { severity: 'error' } : {}),
        date: dateStr,
        competenceId: competence.id,
        filled,
        required,
        demandCells: [key],
      });
    });
  }

  // Only the days that are still generated count. Days already worked may
  // follow a different scenario, and nothing done now can change them.
  // A day the manager is editing by hand counts again, whatever its date.
  if (fromDate) {
    const kept = conflicts.filter(
      (conflict) =>
        !conflict.date ||
        (conflict.secondDate ?? conflict.date) >= fromDate ||
        editedDates?.has(conflict.date) ||
        (conflict.secondDate != null && editedDates?.has(conflict.secondDate))
    );
    conflicts.length = 0;
    conflicts.push(...kept);
  }

  const typeOrder = new Map(CONFLICT_TYPES.map((type, index) => [type, index]));
  conflicts.sort(
    (a, b) =>
      typeOrder.get(a.type) - typeOrder.get(b.type) ||
      (a.date || '').localeCompare(b.date || '') ||
      (a.userId ?? 0) - (b.userId ?? 0)
  );

  const byCell = new Map();
  const byDemandCell = new Map();
  const byUser = new Map();
  const counts = {};
  conflicts.forEach((conflict) => {
    counts[conflict.type] = (counts[conflict.type] || 0) + 1;
    conflict.cells.forEach((key) => push(byCell, key, conflict));
    conflict.demandCells.forEach((key) => push(byDemandCell, key, conflict));
    conflict.rows.forEach((userId) => push(byUser, userId, conflict));
  });

  /**
   * What putting `userId` into `competenceId` on `dateStr` would break --
   * or, with `shiftId`, what that duty already breaks. Offered next to every
   * name and every competence the planner lets the manager pick, so the
   * conflict is visible before the click, not only after it.
   */
  const forCandidate = (userId, dateStr, competenceId, shiftId = null) => {
    const found = [];
    const held = heldBy.get(userId);
    if (!held || !held.has(competenceId)) found.push({ type: 'unqualified' });

    const reason = marksByUser.get(userId)?.get(dateStr);
    if (reason && reason !== SOFT_DECLINE_REASON) found.push({ type: 'unavailable', reason });

    const day = dayNumber(dateStr);
    const recovery = recoveryOf(competenceId, dateStr);
    // The duty being asked about is not a conflict with itself.
    const isItself = (duty) =>
      duty.shift &&
      (duty.shift.id === shiftId ||
        (duty.shift.competence_id === competenceId && duty.dateStr === dateStr));
    const others = (dutiesByUser.get(userId) || []).filter((duty) => !isItself(duty));
    const sameDayHere = others.filter((duty) => duty.day === day && duty.shift);
    if (sameDayHere.length > 0) {
      found.push({
        type: 'double_role',
        competenceIds: sameDayHere.map((duty) => duty.competenceId),
      });
    }
    const sameDayElsewhere = others.filter((duty) => duty.day === day && duty.elsewhere);
    if (sameDayElsewhere.length > 0) {
      found.push({
        type: 'other_workplace',
        workplaces: [...new Set(sameDayElsewhere.map((duty) => duty.elsewhere.name))],
      });
    }
    const resting = others.filter(
      (duty) =>
        duty.day !== day &&
        ((duty.day < day && day <= duty.day + duty.recovery) ||
          (day < duty.day && duty.day <= day + recovery))
    );
    if (resting.length > 0) {
      found.push({
        type: 'rest',
        dates: resting.map((duty) => duty.dateStr),
        workplaces: [
          ...new Set(resting.filter((duty) => duty.elsewhere).map((duty) => duty.elsewhere.name)),
        ],
      });
    }

    const max = contextByUser.get(userId)?.max_shifts_per_month;
    const alreadyCounted = others.length !== (dutiesByUser.get(userId) || []).length;
    const load = (ownCount.get(userId) || 0) + (alreadyCounted ? 0 : 1);
    if (max && load > max) found.push({ type: 'over_wish', count: load, max });

    if (reason === SOFT_DECLINE_REASON) found.push({ type: 'soft_decline' });
    return found.map((item) => ({ ...item, severity: CONFLICT_SEVERITY[item.type] }));
  };

  /* What a person's day already holds besides this workplace's duties -- an
     absence or a duty elsewhere -- whether or not anything clashes with it
     yet. The people grid marks those days so they are seen before a duty is
     put on them. */
  const notesByCell = new Map();
  const noteFor = (key) => {
    let note = notesByCell.get(key);
    if (!note) {
      note = { reason: null, workplaces: [] };
      notesByCell.set(key, note);
    }
    return note;
  };
  marksByUser.forEach((marks, userId) => {
    marks.forEach((reason, dateStr) => {
      noteFor(personCellKey(userId, dateStr)).reason = reason;
    });
  });
  dutiesByUser.forEach((duties, userId) => {
    duties.forEach((duty) => {
      if (!duty.elsewhere) return;
      const note = noteFor(personCellKey(userId, duty.dateStr));
      if (!note.workplaces.includes(duty.elsewhere.name)) {
        note.workplaces.push(duty.elsewhere.name);
      }
    });
  });

  return {
    conflicts,
    byCell,
    byDemandCell,
    byUser,
    notesByCell,
    counts,
    errorCount: conflicts.filter((conflict) => conflict.severity === 'error').length,
    warningCount: conflicts.filter((conflict) => conflict.severity === 'warning').length,
    forCandidate,
  };
}
