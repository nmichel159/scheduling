import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  SPECIAL_DAY_SLOT,
  defaultIsSurcharge,
  normalizeWeekdayRequirements,
} from '../utils/competenceRequirements';
import { formatShortName } from '../utils/formatEmployeeName';
import './SchedulePlannerView.css';

const pad = (n) => String(n).padStart(2, '0');
const isoDate = (year, month, day) => `${year}-${pad(month + 1)}-${pad(day)}`;
const isoWeekday = (dateObj) => (dateObj.getDay() + 6) % 7;

/* The competence picker is a fixed-position panel anchored next to the cell
   that opened it, so these have to be known here to keep it inside the
   viewport. */
const PICKER_WIDTH = 268;
const PICKER_MAX_HEIGHT = 320;
const PICKER_MARGIN = 12;

/* The people list is a floating panel anchored to the square that opened it,
   so it has to know its own size to stay inside the viewport. It is laid out
   in columns of at most ten names rather than as one long list: a workplace
   where thirty people hold the same competence is exactly the case where the
   whole roster has to be comparable at a glance, and a scrolling column shows
   ten of them. */
const DETAIL_COL_WIDTH = 158;
const DETAIL_MAX_ROWS = 10;
const DETAIL_MAX_COLS = 4;
const DETAIL_CHROME = 14; // borders + the grid's own padding
const DETAIL_MAX_HEIGHT = 360;

/* Every day of the month has to be on screen at once, so the row height is not
   a fixed number but whatever divides the space actually left under the matrix.
   It is measured rather than guessed with svh units: what sits above the table
   changes with the workplace header, an error banner, the sidebar being folded
   away, so only the real position of the table can say how much room is left. */
const MATRIX_BOTTOM_GAP = 16;
const MIN_ROW_HEIGHT = 14;
const MAX_ROW_HEIGHT = 26;
/* The table separates its borders, so each row stands one grid line taller than
   the height it is given. Thirty of those are a row and a half. */
const CELL_BORDER = 1;

/* The header is as tall as the longest competence name needs once it is tilted
   — a name set at 45 degrees claims its own length times sin(45) in height, and
   the same again in width past the last column. Measuring it beats a fixed
   height, which either clips real names ("Detská anestéziológia" is not short)
   or reserves space no workplace uses. A name is only ellipsised when the
   window is too short to show it whole -- the header takes as much room as the
   longest name asks for, as long as the month's days still fit under it at
   their smallest row. */
const LABEL_TILT = Math.SQRT1_2; // sin(45°) === cos(45°)
const MIN_LABEL_WIDTH = 60;
const MAX_LABEL_WIDTH = 320;
const LABEL_PADDING = 8;

/**
 * Third schedule mode — the planner.
 *
 * The month is shown twice at once, from the two angles a scheduler actually
 * works in, split down the middle:
 *
 * - Left: demand. One row per day of the month, one column per competence,
 *   with the competence names set at 45 degrees so a dozen of them still fit
 *   into a narrow pane. Each square says how far that day/competence pair is
 *   from what the workplace needs — a filled dot when a single required duty
 *   is covered, a plain number once more than one person is needed. Clicking a
 *   square opens the people who hold that competence as a row of the table
 *   itself, each with the duties they already carry split into the surcharged
 *   and the ordinary ones — which is the number the choice is actually made
 *   on. Filling the square is one click on a name.
 *
 * - Right: people. One row per employee, one column per day, a coloured dot
 *   where they serve. This is the half that answers "who is overloaded", "who
 *   has not been used" and "is anyone on two duties in one day" — none of
 *   which the demand matrix can show. Clicking a person's day offers exactly
 *   the competences that person holds, so the same month can be filled from
 *   the person's side as well as from the day's.
 *
 * Both halves read from and write to the same unsaved `shifts` state as the
 * calendar and the daily-rows modes, so switching between them mid-edit keeps
 * everything, and one Save still commits the whole month.
 *
 * Props:
 * - year, month (0-11), today, locale, weekdayLabels — calendar framing.
 * - competences: the caller's ordered + coloured competence map (legend).
 * - employees: [{ user_id, full_name, email, competences: [{id, name}] }].
 * - shiftsByDate: { 'YYYY-MM-DD': [shift, ...] } — already sorted by the caller.
 * - restDays: Set of ISO dates the workplace rests on. A duty there is staffed
 *   and paid from the competence's day-of-rest slot rather than from the
 *   weekday it happens to fall on, exactly as the solver reads it.
 * - onAssign(dateStr, competenceId, userId) / onRemoveShift(shiftId) —
 *   local-state edits; nothing here talks to the API.
 * - onGenerate + generate* — the solver button, repeated here because the
 *   planner replaces the left rail that normally carries it.
 * - onClear + clear* — the same for the button that empties the still
 *   plannable part of the month.
 * - header — the page's own action bar. It is handed in rather than left
 *   above the planner because the demand matrix has to start at the very top
 *   of the page; the bar therefore sits in the right column, beside the
 *   matrix instead of over it.
 */
const SchedulePlannerView = ({
  header,
  year,
  month,
  today,
  locale,
  weekdayLabels,
  competences,
  employees,
  shiftsByDate,
  restDays,
  competenceColor,
  loading,
  onAssign,
  onRemoveShift,
  onGenerate,
  generateLabel,
  generateHint,
  generateDisabled,
  timeBudget,
  timeBudgetOptions,
  onTimeBudgetChange,
  onClear,
  clearLabel,
  clearDisabled,
}) => {
  const { t } = useTranslation();

  // { dateStr, competenceId, anchor: DOMRect } — the square whose people are
  // listed. Null while nothing is being filled.
  const [demandCell, setDemandCell] = useState(null);
  // { dateStr, userId, anchor: DOMRect } — the person's day whose competence
  // list is open.
  const [personCell, setPersonCell] = useState(null);
  const pickerRef = useRef(null);
  const detailRef = useRef(null);
  const demandRef = useRef(null);
  const [metrics, setMetrics] = useState({
    rowHeight: MAX_ROW_HEIGHT,
    labelWidth: MAX_LABEL_WIDTH,
  });

  const daysInMonth = new Date(year, month + 1, 0).getDate();

  const days = useMemo(
    () =>
      Array.from({ length: daysInMonth }, (_, index) => {
        const day = index + 1;
        const date = new Date(year, month, day);
        const weekday = isoWeekday(date);
        const dateStr = isoDate(year, month, day);
        const isRestDay = restDays?.has(dateStr) ?? false;
        return {
          day,
          weekday,
          date,
          dateStr,
          /* Which column of the competence definition staffs and pays this
             date. A public holiday on a Tuesday is a day of rest, not a
             Tuesday, and the generator reads it that way too. */
          slot: isRestDay ? SPECIAL_DAY_SLOT : weekday,
          isWeekend: weekday >= 5,
          isRestDay,
          isToday:
            day === today.getDate() &&
            month === today.getMonth() &&
            year === today.getFullYear(),
        };
      }),
    [daysInMonth, year, month, today, restDays]
  );

  /* Complete slot definitions per competence. normalizeWeekdayRequirements
     always returns all eight slots in order, so position === slot. */
  const slotsByCompetence = useMemo(() => {
    const map = new Map();
    competences.forEach((competence) => {
      map.set(competence.id, normalizeWeekdayRequirements(competence));
    });
    return map;
  }, [competences]);

  const requiredFor = (competenceId, slot) =>
    slotsByCompetence.get(competenceId)?.[slot]?.required_count ?? 0;

  const isSurchargeFor = (competenceId, slot) =>
    slotsByCompetence.get(competenceId)?.[slot]?.is_surcharge ??
    defaultIsSurcharge(slot);

  /** Everyone assigned to one competence on one day. */
  const assignedOn = (dateStr, competenceId) =>
    (shiftsByDate[dateStr] || []).filter((s) => s.competence_id === competenceId);

  /* Duties per employee for the whole month, split the way the payroll splits
     them. The surcharged count is what the choice between two equally able
     people is actually made on, so it is carried next to every name the
     planner offers. */
  const dutyStats = useMemo(() => {
    const map = new Map();
    days.forEach((dayInfo) => {
      (shiftsByDate[dayInfo.dateStr] || []).forEach((shift) => {
        const stats = map.get(shift.user_id) || {
          total: 0,
          surcharge: 0,
          standard: 0,
        };
        stats.total += 1;
        if (isSurchargeFor(shift.competence_id, dayInfo.slot)) stats.surcharge += 1;
        else stats.standard += 1;
        map.set(shift.user_id, stats);
      });
    });
    return map;
  }, [days, shiftsByDate, slotsByCompetence]); // eslint-disable-line react-hooks/exhaustive-deps

  const statsFor = (userId) =>
    dutyStats.get(userId) || { total: 0, surcharge: 0, standard: 0 };

  /* Shifts of one employee on one day, for the right-hand grid. */
  const shiftsByUserDate = useMemo(() => {
    const map = new Map();
    Object.entries(shiftsByDate).forEach(([dateStr, dayShifts]) => {
      dayShifts.forEach((shift) => {
        let byDate = map.get(shift.user_id);
        if (!byDate) {
          byDate = new Map();
          map.set(shift.user_id, byDate);
        }
        const list = byDate.get(dateStr);
        if (list) list.push(shift);
        else byDate.set(dateStr, [shift]);
      });
    });
    return map;
  }, [shiftsByDate]);

  const people = useMemo(
    () =>
      [...employees].sort((a, b) =>
        (a.full_name || a.email || '').localeCompare(b.full_name || b.email || '')
      ),
    [employees]
  );

  const employeeById = useMemo(() => {
    const map = new Map();
    employees.forEach((employee) => map.set(employee.user_id, employee));
    return map;
  }, [employees]);

  /** Duties the month is still short of, summed over every day/competence. */
  const missingTotal = useMemo(
    () =>
      days.reduce(
        (sum, dayInfo) =>
          sum +
          competences.reduce((daySum, competence) => {
            const required = requiredFor(competence.id, dayInfo.slot);
            const filled = assignedOn(dayInfo.dateStr, competence.id).length;
            return daySum + Math.max(0, required - filled);
          }, 0),
        0
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [days, competences, slotsByCompetence, shiftsByDate]
  );

  /* The open square and the open person-day, resolved against the month, the
     competences and the roster currently on screen. Worked out during render
     rather than cleared by an effect: neither can outlive the cell it points
     at, and after a month or a workplace change that cell is simply no longer
     there. They have to be declared before the effect below, which lists the
     person picker as a dependency. */
  const openDemand = useMemo(() => {
    if (!demandCell) return null;
    const day = days.find((d) => d.dateStr === demandCell.dateStr);
    const competence = competences.find((c) => c.id === demandCell.competenceId);
    return day && competence ? { ...demandCell, day, competence } : null;
  }, [demandCell, days, competences]);

  const openPerson = useMemo(() => {
    if (!personCell) return null;
    const day = days.find((d) => d.dateStr === personCell.dateStr);
    const employee = employeeById.get(personCell.userId);
    return day && employee ? { ...personCell, day, employee } : null;
  }, [personCell, days, employeeById]);

  /* Escape closes whichever list is open; a press outside closes it too.
   * Deliberately a listener rather than a full-screen backdrop: filling a
   * month means clicking one cell after another, and a backdrop would eat the
   * press that opens the next one, making every cell after the first cost two
   * clicks. Closing on mousedown lets the click that follows land on the new
   * cell. */
  useEffect(() => {
    if (!openDemand && !openPerson) return undefined;
    const handleKeyDown = (e) => {
      if (e.key !== 'Escape') return;
      setDemandCell(null);
      setPersonCell(null);
    };
    const handlePointerDown = (e) => {
      if (!pickerRef.current?.contains(e.target)) setPersonCell(null);
      if (!detailRef.current?.contains(e.target)) setDemandCell(null);
    };
    window.addEventListener('keydown', handleKeyDown);
    document.addEventListener('mousedown', handlePointerDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('mousedown', handlePointerDown);
    };
  }, [openDemand, openPerson]);

  /* Size the header to the names it actually carries, then fit all of the
     month's days into whatever is left between the table's top edge and the
     bottom of the window. Driven by a ResizeObserver, which also delivers the
     first measurement when it starts observing, so nothing has to be computed
     during render. scrollWidth is the full width of a label even while it is
     being ellipsised, so the two measurements do not chase each other. */
  useEffect(() => {
    const measure = () => {
      const el = demandRef.current;
      if (!el) return;

      const labels = el.querySelectorAll('.planner-matrix-colhead-text');
      const longest = Math.max(
        MIN_LABEL_WIDTH,
        ...[...labels].map((label) => Math.ceil(label.scrollWidth) + 1)
      );
      const room =
        window.innerHeight - el.getBoundingClientRect().top - MATRIX_BOTTOM_GAP;

      // What the header may take without pushing the month's days below the
      // row height they stop being readable at. Only a window shorter than
      // that makes a name ellipsise.
      const affordable =
        (room - daysInMonth * (MIN_ROW_HEIGHT + CELL_BORDER) - LABEL_PADDING) /
        LABEL_TILT;
      const labelWidth = Math.min(
        MAX_LABEL_WIDTH,
        longest,
        Math.max(MIN_LABEL_WIDTH, Math.floor(affordable))
      );
      const headHeight = Math.ceil(labelWidth * LABEL_TILT) + LABEL_PADDING;

      const perRow =
        Math.floor((room - headHeight) / daysInMonth) - CELL_BORDER;
      const rowHeight = Math.min(
        MAX_ROW_HEIGHT,
        Math.max(MIN_ROW_HEIGHT, perRow || MIN_ROW_HEIGHT)
      );

      setMetrics((current) =>
        current.rowHeight === rowHeight && current.labelWidth === labelWidth
          ? current
          : { rowHeight, labelWidth }
      );
    };
    const observer = new ResizeObserver(measure);
    if (demandRef.current) observer.observe(demandRef.current);
    observer.observe(document.body);
    window.addEventListener('resize', measure);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, [daysInMonth, competences]);

  const dateFormatter = useMemo(
    () => new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'long' }),
    [locale]
  );

  const toggleDemandCell = (event, dateStr, competenceId) => {
    const rect = event.currentTarget.getBoundingClientRect();
    setPersonCell(null);
    setDemandCell((current) =>
      current && current.dateStr === dateStr && current.competenceId === competenceId
        ? null
        : { dateStr, competenceId, anchor: rect }
    );
  };

  const togglePersonCell = (event, dateStr, userId) => {
    const rect = event.currentTarget.getBoundingClientRect();
    setPersonCell((current) =>
      current && current.dateStr === dateStr && current.userId === userId
        ? null
        : { dateStr, userId, anchor: rect }
    );
  };

  /* ---------- who can fill the open square ---------- */

  const demandRows = useMemo(() => {
    if (!openDemand) return [];
    const dayShifts = shiftsByDate[openDemand.dateStr] || [];
    return employees
      .filter((e) =>
        (e.competences || []).some((c) => c.id === openDemand.competenceId)
      )
      .map((employee) => {
        const mine = dayShifts.find(
          (s) =>
            s.user_id === employee.user_id &&
            s.competence_id === openDemand.competenceId
        );
        const elsewhere = dayShifts.find(
          (s) =>
            s.user_id === employee.user_id &&
            s.competence_id !== openDemand.competenceId
        );
        return {
          employee,
          shift: mine || null,
          busyWith: mine ? null : elsewhere || null,
          stats: statsFor(employee.user_id),
        };
      })
      .sort((a, b) => {
        // Assigned first (so removing is easy), then whoever is free and has
        // served least so far, then the ones already on duty that day.
        const rank = (row) => (row.shift ? 0 : row.busyWith ? 2 : 1);
        return (
          rank(a) - rank(b) ||
          a.stats.total - b.stats.total ||
          (a.employee.full_name || '').localeCompare(b.employee.full_name || '')
        );
      });
  }, [openDemand, employees, shiftsByDate, dutyStats]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleAssignment = (dateStr, competenceId, row) => {
    if (row.busyWith) return; // one duty per person per day
    if (row.shift) onRemoveShift(row.shift.id);
    else onAssign(dateStr, competenceId, row.employee.user_id);
  };

  /* Fill columns top to bottom, ten names each, and let the panel be as wide
     as the columns it ends up with. */
  const detailGrid = useMemo(() => {
    const count = Math.max(1, demandRows.length);
    const columns = Math.min(DETAIL_MAX_COLS, Math.ceil(count / DETAIL_MAX_ROWS));
    return { columns, rows: Math.ceil(count / columns) };
  }, [demandRows.length]);

  /* Anchored to the right of the square it belongs to, and pulled back inside
     the viewport near the edges of the month. */
  const detailStyle = useMemo(() => {
    if (!openDemand?.anchor) return null;
    const { anchor } = openDemand;
    const width = detailGrid.columns * DETAIL_COL_WIDTH + DETAIL_CHROME;
    const left = Math.max(
      PICKER_MARGIN,
      Math.min(anchor.right + 8, window.innerWidth - width - PICKER_MARGIN)
    );
    const top = Math.max(
      PICKER_MARGIN,
      Math.min(anchor.top - 6, window.innerHeight - DETAIL_MAX_HEIGHT - PICKER_MARGIN)
    );
    return {
      left,
      top,
      width,
      maxHeight: DETAIL_MAX_HEIGHT,
      '--detail-rows': detailGrid.rows,
    };
  }, [openDemand, detailGrid]);

  /* ---------- what the open person can do that day ---------- */

  const personRows = useMemo(() => {
    if (!openPerson) return [];
    const dayShifts = shiftsByDate[openPerson.dateStr] || [];
    const held = new Set(
      (openPerson.employee.competences || []).map((c) => c.id)
    );
    const elsewhere = dayShifts.find(
      (s) => s.user_id === openPerson.employee.user_id
    );
    return competences
      .filter(
        (competence) =>
          held.has(competence.id) ||
          /* A duty placed before the person lost the competence, or by the
             solver on an older roster, still has to be removable from here —
             so what is already theirs is listed whether they hold it or not. */
          dayShifts.some(
            (s) =>
              s.user_id === openPerson.employee.user_id &&
              s.competence_id === competence.id
          )
      )
      .map((competence) => {
        const mine = dayShifts.find(
          (s) =>
            s.user_id === openPerson.employee.user_id &&
            s.competence_id === competence.id
        );
        return {
          competence,
          shift: mine || null,
          busyWith: mine ? null : elsewhere || null,
          filled: dayShifts.filter((s) => s.competence_id === competence.id)
            .length,
          required: requiredFor(competence.id, openPerson.day.slot),
        };
      });
  }, [openPerson, competences, shiftsByDate, slotsByCompetence]); // eslint-disable-line react-hooks/exhaustive-deps

  const pickerStyle = useMemo(() => {
    if (!openPerson) return null;
    const { anchor } = openPerson;
    const left = Math.max(
      PICKER_MARGIN,
      Math.min(anchor.right + 8, window.innerWidth - PICKER_WIDTH - PICKER_MARGIN)
    );
    const top = Math.max(
      PICKER_MARGIN,
      Math.min(anchor.top - 6, window.innerHeight - PICKER_MAX_HEIGHT - PICKER_MARGIN)
    );
    return { left, top, width: PICKER_WIDTH, maxHeight: PICKER_MAX_HEIGHT };
  }, [openPerson]);

  const togglePersonDuty = (row) => {
    if (row.busyWith) return; // one duty per person per day
    if (row.shift) onRemoveShift(row.shift.id);
    else
      onAssign(
        openPerson.dateStr,
        row.competence.id,
        openPerson.employee.user_id
      );
  };

  /* ---------- render ---------- */

  const hasCompetences = competences.length > 0;

  return (
    <div className={`planner ${loading ? 'is-loading' : ''}`}>
      <div className="planner-split">
        {/* ---------- left: demand per day ----------
            First thing on the page and flush with its top edge: it is the half
            that is worked in, and every pixel spent above it is taken off the
            row height that has to carry all 31 days. Everything else — the
            generate button, the legend, the shortfall — moved across to the
            right column for the same reason. */}
        <section className="planner-pane planner-pane-demand">
          <h2 className="planner-pane-title">
            {t('schedule_edit.planner_demand_title')}
          </h2>
          {!hasCompetences ? (
            <p className="planner-empty">{t('schedule_edit.legend_empty')}</p>
          ) : (
            <div className="planner-scroll planner-scroll-demand" ref={demandRef}>
              <table
                className="planner-matrix"
                style={{
                  '--planner-row': `${metrics.rowHeight}px`,
                  '--planner-label-w': `${metrics.labelWidth}px`,
                }}
              >
                <thead>
                  <tr className="planner-matrix-headrow">
                    <th scope="col" className="planner-matrix-corner">
                      <span className="planner-sr-only">
                        {t('schedule_edit.planner_day')}
                      </span>
                    </th>
                    {competences.map((competence) => (
                      <th
                        key={competence.id}
                        scope="col"
                        className="planner-matrix-colhead"
                        style={{ '--head-color': competence.color }}
                      >
                        {/* Set on the diagonal so a dozen competences still fit
                            across a narrow pane — upright names would force
                            either 90px columns or vertical lettering.
                            The label is plain in-flow cell content, tilted by
                            a transform: as an absolutely positioned box it
                            would be painted under the next column's header
                            background and only the last name would survive. */}
                        <div className="planner-matrix-colhead-label">
                          <span
                            className="planner-matrix-colhead-text"
                            title={competence.description || competence.name}
                          >
                            {competence.name}
                          </span>
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {days.map((dayInfo) => {
                    const isOpenDay = openDemand?.dateStr === dayInfo.dateStr;
                    return (
                      <tr
                        key={dayInfo.dateStr}
                        className={`planner-matrix-row ${
                          dayInfo.isWeekend ? 'is-weekend' : ''
                        } ${dayInfo.isToday ? 'is-today' : ''}`}
                      >
                          <th scope="row" className="planner-matrix-dayhead">
                            <span className="planner-matrix-daynum">{dayInfo.day}</span>
                            <span className="planner-matrix-dayname">
                              {weekdayLabels[dayInfo.weekday]}
                            </span>
                          </th>
                          {competences.map((competence) => {
                            const required = requiredFor(competence.id, dayInfo.slot);
                            const filled = assignedOn(
                              dayInfo.dateStr,
                              competence.id
                            ).length;
                            const isOpen =
                              isOpenDay && openDemand?.competenceId === competence.id;

                            let state = 'idle';
                            if (filled === 0 && required > 0) state = 'needed';
                            else if (filled > 0 && filled < required) state = 'partial';
                            else if (filled > required) state = 'over';
                            else if (filled > 0) state = 'complete';

                            // A single required duty reads best as a dot: the square
                            // is either filled or it is not. From two people up a dot
                            // cannot say how many, so the count takes over.
                            const showDot = filled === 1 && required <= 1;

                            return (
                              <td key={competence.id} className="planner-matrix-cell">
                                <button
                                  type="button"
                                  className={`planner-square is-${state} ${
                                    isOpen ? 'is-open' : ''
                                  }`}
                                  style={{
                                    '--square-color': competenceColor(competence.id),
                                    '--square-fill': required
                                      ? `${Math.round((filled / required) * 100)}%`
                                      : '100%',
                                  }}
                                  onClick={(e) =>
                                    toggleDemandCell(e, dayInfo.dateStr, competence.id)
                                  }
                                  title={t('schedule_edit.planner_cell_title', {
                                    date: dateFormatter.format(dayInfo.date),
                                    competence: competence.name,
                                    filled,
                                    required,
                                  })}
                                >
                                  {showDot ? (
                                    <span
                                      className="planner-square-dot"
                                      aria-hidden="true"
                                    />
                                  ) : (
                                    <span className="planner-square-count">
                                      {filled > 0 ? filled : required || ''}
                                    </span>
                                  )}
                                </button>
                              </td>
                            );
                          })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {/* ---------- right: the controls, then the month per person ---------- */}
        <div className="planner-right">
          {header}

          <div className="planner-toolbar">
            {onGenerate && (
              <button
                type="button"
                className="planner-generate"
                onClick={onGenerate}
                disabled={generateDisabled}
                title={generateHint}
              >
                {generateLabel}
              </button>
            )}

            {onTimeBudgetChange && (
              <select
                className="planner-time-budget"
                value={timeBudget}
                onChange={(event) => onTimeBudgetChange(Number(event.target.value))}
                disabled={generateDisabled}
                aria-label={t('schedule_edit.time_budget_label')}
              >
                {(timeBudgetOptions || []).map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            )}

            {onClear && (
              <button
                type="button"
                className="planner-clear"
                onClick={onClear}
                disabled={clearDisabled}
              >
                {clearLabel}
              </button>
            )}

            <ul className="planner-legend">
              {competences.map((competence) => (
                <li key={competence.id} className="planner-legend-item">
                  <span
                    className="planner-legend-swatch"
                    style={{ backgroundColor: competence.color }}
                    aria-hidden="true"
                  />
                  <span title={competence.description || competence.name}>
                    {competence.name}
                  </span>
                </li>
              ))}
            </ul>

            <span
              className={`planner-missing ${missingTotal === 0 ? 'is-ok' : ''}`}
              title={t('schedule_edit.planner_missing_hint')}
            >
              {missingTotal === 0
                ? t('schedule_edit.planner_missing_none')
                : t('schedule_edit.planner_missing', { missing: missingTotal })}
            </span>
          </div>

          <section className="planner-pane planner-pane-people">
            <h2 className="planner-pane-title">
              {t('schedule_edit.planner_people_title')}
            </h2>
            {people.length === 0 ? (
              <p className="planner-empty">{t('schedule_edit.planner_people_empty')}</p>
            ) : (
              <div className="planner-scroll planner-scroll-people">
                <table className="planner-people-table">
                  <thead>
                    <tr>
                      <th scope="col" className="planner-people-corner">
                        {t('schedule_edit.planner_person')}
                      </th>
                      {days.map((dayInfo) => (
                        <th
                          key={dayInfo.dateStr}
                          scope="col"
                          className={`planner-people-dayhead ${
                            dayInfo.isWeekend ? 'is-weekend' : ''
                          } ${dayInfo.isToday ? 'is-today' : ''}`}
                          title={`${dayInfo.day}. ${weekdayLabels[dayInfo.weekday]}`}
                        >
                          <span className="planner-people-daynum">{dayInfo.day}</span>
                          <span className="planner-people-dayname">
                            {weekdayLabels[dayInfo.weekday].charAt(0)}
                          </span>
                        </th>
                      ))}
                      <th scope="col" className="planner-people-total-head">
                        {t('schedule_edit.planner_shifts')}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {people.map((employee) => {
                      const byDate = shiftsByUserDate.get(employee.user_id);
                      const total = statsFor(employee.user_id).total;
                      const fullLabel = employee.full_name || employee.email;
                      return (
                        <tr key={employee.user_id}>
                          <th scope="row" className="planner-people-name" title={fullLabel}>
                            {formatShortName(employee.full_name) || employee.email}
                          </th>
                          {days.map((dayInfo) => {
                            const dayShifts = byDate?.get(dayInfo.dateStr) || [];
                            const isOpen =
                              openPerson?.dateStr === dayInfo.dateStr &&
                              openPerson?.userId === employee.user_id;
                            return (
                              <td
                                key={dayInfo.dateStr}
                                className={`planner-people-cell ${
                                  dayInfo.isWeekend ? 'is-weekend' : ''
                                } ${dayInfo.isToday ? 'is-today' : ''} ${
                                  dayShifts.length > 1 ? 'is-clash' : ''
                                }`}
                              >
                                {/* The whole square opens the list of what this
                                    person may serve that day — an empty one as
                                    readily as a taken one, which is what makes
                                    the month fillable from the person's side. */}
                                <button
                                  type="button"
                                  className={`planner-people-slot ${
                                    isOpen ? 'is-open' : ''
                                  }`}
                                  onClick={(e) =>
                                    togglePersonCell(
                                      e,
                                      dayInfo.dateStr,
                                      employee.user_id
                                    )
                                  }
                                  title={
                                    dayShifts.length > 0
                                      ? dayShifts
                                          .map((shift) =>
                                            t('schedule_edit.planner_dot_title', {
                                              name: fullLabel,
                                              date: dateFormatter.format(
                                                dayInfo.date
                                              ),
                                              competence: shift.competence_name,
                                            })
                                          )
                                          .join('\n')
                                      : `${fullLabel} — ${dateFormatter.format(
                                          dayInfo.date
                                        )}`
                                  }
                                >
                                  {dayShifts.map((shift) => (
                                    <span
                                      key={shift.id}
                                      className="planner-people-dot"
                                      style={{
                                        backgroundColor: competenceColor(
                                          shift.competence_id
                                        ),
                                      }}
                                    />
                                  ))}
                                </button>
                              </td>
                            );
                          })}
                          <td className="planner-people-total">{total || ''}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      </div>

      {openDemand && (
        <div
          ref={detailRef}
          className="planner-detail"
          style={detailStyle}
          role="dialog"
          aria-label={t('schedule_edit.planner_picker_title', {
            competence: openDemand.competence.name,
          })}
        >
          <div className="planner-detail-head">
            <span className="planner-detail-heading">
              <span
                className="planner-legend-swatch"
                style={{
                  backgroundColor: competenceColor(openDemand.competenceId),
                }}
                aria-hidden="true"
              />
              <span className="planner-detail-competence">
                {openDemand.competence.name}
              </span>
              <span className="planner-detail-meta">
                {dateFormatter.format(openDemand.day.date)} ·{' '}
                {t('schedule_edit.planner_picker_filled', {
                  filled: assignedOn(openDemand.dateStr, openDemand.competenceId)
                    .length,
                  required: requiredFor(
                    openDemand.competenceId,
                    openDemand.day.slot
                  ),
                })}
              </span>
            </span>
            <button
              type="button"
              className="planner-picker-close"
              onClick={() => setDemandCell(null)}
              title={t('schedule_edit.close')}
            >
              ✕
            </button>
          </div>

          <div className="planner-detail-legend">
            <span className="planner-detail-count is-surcharge">
              {t('schedule_edit.planner_surcharge')}
            </span>
            <span className="planner-detail-count-sep">/</span>
            <span className="planner-detail-count">
              {t('schedule_edit.planner_standard')}
            </span>
          </div>

          {demandRows.length === 0 ? (
            <p className="planner-picker-empty">
              {t('schedule_edit.no_eligible_users')}
            </p>
          ) : (
            <div className="planner-detail-grid">
              {demandRows.map((row) => {
                const fullLabel = row.employee.full_name || row.employee.email;
                return (
                  <button
                    key={row.employee.user_id}
                    type="button"
                    className={`planner-detail-person ${
                      row.shift ? 'is-assigned' : ''
                    } ${row.busyWith ? 'is-busy' : ''}`}
                    onClick={() =>
                      toggleAssignment(
                        openDemand.dateStr,
                        openDemand.competenceId,
                        row
                      )
                    }
                    disabled={!!row.busyWith}
                    title={
                      row.busyWith
                        ? `${fullLabel} — ${t('schedule_edit.planner_picker_busy', {
                            competence: row.busyWith.competence_name,
                          })}`
                        : fullLabel
                    }
                  >
                    <span className="planner-detail-mark" aria-hidden="true">
                      {row.shift ? '✓' : ''}
                    </span>
                    <span className="planner-detail-name">
                      {formatShortName(row.employee.full_name) ||
                        row.employee.email}
                    </span>
                    {/* The two numbers the choice is made on, read as one
                        figure: surcharged duties first, ordinary ones after
                        the slash. The legend in the head says which is which
                        so the cells themselves can stay this short. */}
                    <span className="planner-detail-counts">
                      <span className="planner-detail-count is-surcharge">
                        {row.stats.surcharge}
                      </span>
                      <span className="planner-detail-count-sep">/</span>
                      <span className="planner-detail-count">
                        {row.stats.standard}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}

      {openPerson && (
        <div
          ref={pickerRef}
          className="planner-picker"
          style={pickerStyle}
          role="dialog"
          aria-label={t('schedule_edit.planner_person_picker_title', {
            name: openPerson.employee.full_name || openPerson.employee.email,
          })}
        >
          <div className="planner-picker-head">
            <div className="planner-picker-heading">
              <span className="planner-picker-competence">
                {openPerson.employee.full_name || openPerson.employee.email}
              </span>
              <span className="planner-picker-meta">
                {dateFormatter.format(openPerson.day.date)}
              </span>
            </div>
            <button
              type="button"
              className="planner-picker-close"
              onClick={() => setPersonCell(null)}
              title={t('schedule_edit.close')}
            >
              ✕
            </button>
          </div>

          {personRows.length === 0 ? (
            <p className="planner-picker-empty">
              {t('schedule_edit.planner_person_no_competence')}
            </p>
          ) : (
            <ul className="planner-picker-list">
              {personRows.map((row) => (
                <li key={row.competence.id}>
                  <button
                    type="button"
                    className={`planner-picker-person ${
                      row.shift ? 'is-assigned' : ''
                    } ${row.busyWith ? 'is-busy' : ''}`}
                    onClick={() => togglePersonDuty(row)}
                    disabled={!!row.busyWith}
                  >
                    <span className="planner-picker-check" aria-hidden="true">
                      {row.shift ? '✓' : ''}
                    </span>
                    <span
                      className="planner-legend-swatch"
                      style={{
                        backgroundColor: competenceColor(row.competence.id),
                      }}
                      aria-hidden="true"
                    />
                    <span className="planner-picker-person-text">
                      <span className="planner-picker-person-name">
                        {row.competence.name}
                      </span>
                      {row.busyWith && (
                        <span className="planner-picker-person-note">
                          {t('schedule_edit.planner_picker_busy', {
                            competence: row.busyWith.competence_name,
                          })}
                        </span>
                      )}
                    </span>
                    <span className="planner-picker-load">
                      {t('schedule_edit.planner_picker_filled_short', {
                        filled: row.filled,
                        required: row.required,
                      })}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
};

export default SchedulePlannerView;
