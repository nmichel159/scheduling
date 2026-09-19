import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { normalizeWeekdayRequirements } from '../utils/competenceRequirements';
import { formatShortName } from '../utils/formatEmployeeName';
import './SchedulePlannerView.css';

const pad = (n) => String(n).padStart(2, '0');
const isoDate = (year, month, day) => `${year}-${pad(month + 1)}-${pad(day)}`;
const isoWeekday = (dateObj) => (dateObj.getDay() + 6) % 7;

/* The people picker is a fixed-position panel anchored next to the square that
   opened it, so these have to be known here to keep it inside the viewport. */
const PICKER_WIDTH = 292;
const PICKER_MAX_HEIGHT = 380;
const PICKER_MARGIN = 12;

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
   or reserves space no workplace uses. The cap stops one very long name from
   eating the rows; past it the name ellipsises and the tooltip has the rest. */
const LABEL_TILT = Math.SQRT1_2; // sin(45°) === cos(45°)
const MIN_LABEL_WIDTH = 60;
const MAX_LABEL_WIDTH = 190;
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
 *   square offers exactly the people of this workplace who hold that
 *   competence, and filling the square is one click on a name.
 *
 * - Right: people. One row per employee, one column per day, a coloured dot
 *   where they serve. This is the half that answers "who is overloaded", "who
 *   has not been used" and "is anyone on two duties in one day" — none of
 *   which the demand matrix can show.
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
 * - onAssign(dateStr, competenceId, userId) / onRemoveShift(shiftId) —
 *   local-state edits; nothing here talks to the API.
 * - onShiftClick(shift) — hands a dot over to the full shift editor.
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
  competenceColor,
  loading,
  onAssign,
  onRemoveShift,
  onShiftClick,
  onGenerate,
  generateLabel,
  generateHint,
  generateDisabled,
  onClear,
  clearLabel,
  clearDisabled,
}) => {
  const { t } = useTranslation();

  // { dateStr, competenceId, anchor: DOMRect } — the square whose people list
  // is open. Null while nothing is being filled.
  const [picker, setPicker] = useState(null);
  const pickerRef = useRef(null);
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
        return {
          day,
          weekday,
          date,
          dateStr: isoDate(year, month, day),
          isWeekend: weekday >= 5,
          isToday:
            day === today.getDate() &&
            month === today.getMonth() &&
            year === today.getFullYear(),
        };
      }),
    [daysInMonth, year, month, today]
  );

  /* Required head-count per competence, indexed by ISO weekday.
     normalizeWeekdayRequirements always returns all seven days in order, so
     position === weekday. */
  const requiredByCompetence = useMemo(() => {
    const map = new Map();
    competences.forEach((competence) => {
      map.set(
        competence.id,
        normalizeWeekdayRequirements(competence).map((item) => item.required_count)
      );
    });
    return map;
  }, [competences]);

  const requiredFor = (competenceId, weekday) =>
    requiredByCompetence.get(competenceId)?.[weekday] ?? 0;

  /** Everyone assigned to one competence on one day. */
  const assignedOn = (dateStr, competenceId) =>
    (shiftsByDate[dateStr] || []).filter((s) => s.competence_id === competenceId);

  /* Duties per employee for the whole month — shown next to each name and used
     to offer the least-loaded people first in the picker. */
  const loadByUser = useMemo(() => {
    const counts = new Map();
    Object.values(shiftsByDate).forEach((dayShifts) =>
      dayShifts.forEach((shift) => {
        counts.set(shift.user_id, (counts.get(shift.user_id) || 0) + 1);
      })
    );
    return counts;
  }, [shiftsByDate]);

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

  /** Duties the month is still short of, summed over every day/competence. */
  const missingTotal = useMemo(
    () =>
      days.reduce(
        (sum, dayInfo) =>
          sum +
          competences.reduce((daySum, competence) => {
            const required = requiredFor(competence.id, dayInfo.weekday);
            const filled = assignedOn(dayInfo.dateStr, competence.id).length;
            return daySum + Math.max(0, required - filled);
          }, 0),
        0
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [days, competences, requiredByCompetence, shiftsByDate]
  );

  /* The open square, resolved against the month and the competences currently
     on screen. Worked out during render rather than cleared by an effect: a
     picker cannot outlive the square it points at, and after a month or a
     workplace change that square is simply no longer there. It has to be
     declared before the effect below, which lists it as a dependency. */
  const open = useMemo(() => {
    if (!picker) return null;
    const day = days.find((d) => d.dateStr === picker.dateStr);
    const competence = competences.find((c) => c.id === picker.competenceId);
    return day && competence ? { ...picker, day, competence } : null;
  }, [picker, days, competences]);

  /* Escape, or a press anywhere outside the panel. Deliberately a listener
   * rather than a full-screen backdrop: filling a month means clicking one
   * square after another, and a backdrop would eat the press that opens the
   * next one, making every square after the first cost two clicks. Closing on
   * mousedown lets the click that follows land on the new square. */
  useEffect(() => {
    if (!open) return undefined;
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') setPicker(null);
    };
    const handlePointerDown = (e) => {
      if (!pickerRef.current?.contains(e.target)) setPicker(null);
    };
    window.addEventListener('keydown', handleKeyDown);
    document.addEventListener('mousedown', handlePointerDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('mousedown', handlePointerDown);
    };
  }, [open]);

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
      const labelWidth = Math.min(MAX_LABEL_WIDTH, longest);
      const headHeight = Math.ceil(labelWidth * LABEL_TILT) + LABEL_PADDING;

      const room =
        window.innerHeight - el.getBoundingClientRect().top - MATRIX_BOTTOM_GAP;
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

  const openPicker = (event, dateStr, competenceId) => {
    const rect = event.currentTarget.getBoundingClientRect();
    setPicker((current) =>
      current && current.dateStr === dateStr && current.competenceId === competenceId
        ? null
        : { dateStr, competenceId, anchor: rect }
    );
  };

  /* ---------- the open people list ---------- */

  const pickerRows = useMemo(() => {
    if (!open) return [];
    const dayShifts = shiftsByDate[open.dateStr] || [];
    return employees
      .filter((e) => (e.competences || []).some((c) => c.id === open.competenceId))
      .map((employee) => {
        const mine = dayShifts.find(
          (s) => s.user_id === employee.user_id && s.competence_id === open.competenceId
        );
        const elsewhere = dayShifts.find(
          (s) => s.user_id === employee.user_id && s.competence_id !== open.competenceId
        );
        return {
          employee,
          shift: mine || null,
          busyWith: mine ? null : elsewhere || null,
          load: loadByUser.get(employee.user_id) || 0,
        };
      })
      .sort((a, b) => {
        // Assigned first (so removing is easy), then whoever is free and has
        // served least so far, then the ones already on duty that day.
        const rank = (row) => (row.shift ? 0 : row.busyWith ? 2 : 1);
        return (
          rank(a) - rank(b) ||
          a.load - b.load ||
          (a.employee.full_name || '').localeCompare(b.employee.full_name || '')
        );
      });
  }, [open, employees, shiftsByDate, loadByUser]);

  const pickerStyle = useMemo(() => {
    if (!open) return null;
    const { anchor } = open;
    const left = Math.max(
      PICKER_MARGIN,
      Math.min(anchor.right + 8, window.innerWidth - PICKER_WIDTH - PICKER_MARGIN)
    );
    const top = Math.max(
      PICKER_MARGIN,
      Math.min(anchor.top - 6, window.innerHeight - PICKER_MAX_HEIGHT - PICKER_MARGIN)
    );
    return { left, top, width: PICKER_WIDTH, maxHeight: PICKER_MAX_HEIGHT };
  }, [open]);

  const togglePerson = (row) => {
    if (row.busyWith) return; // one duty per person per day
    if (row.shift) onRemoveShift(row.shift.id);
    else onAssign(open.dateStr, open.competenceId, row.employee.user_id);
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
                  {days.map((dayInfo) => (
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
                        const required = requiredFor(competence.id, dayInfo.weekday);
                        const filled = assignedOn(dayInfo.dateStr, competence.id).length;
                        const isOpen =
                          open?.dateStr === dayInfo.dateStr &&
                          open?.competenceId === competence.id;

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
                                openPicker(e, dayInfo.dateStr, competence.id)
                              }
                              title={t('schedule_edit.planner_cell_title', {
                                date: dateFormatter.format(dayInfo.date),
                                competence: competence.name,
                                filled,
                                required,
                              })}
                            >
                              {showDot ? (
                                <span className="planner-square-dot" aria-hidden="true" />
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
                  ))}
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
                      const total = loadByUser.get(employee.user_id) || 0;
                      const fullLabel = employee.full_name || employee.email;
                      return (
                        <tr key={employee.user_id}>
                          <th scope="row" className="planner-people-name" title={fullLabel}>
                            {formatShortName(employee.full_name) || employee.email}
                          </th>
                          {days.map((dayInfo) => {
                            const dayShifts = byDate?.get(dayInfo.dateStr) || [];
                            return (
                              <td
                                key={dayInfo.dateStr}
                                className={`planner-people-cell ${
                                  dayInfo.isWeekend ? 'is-weekend' : ''
                                } ${dayInfo.isToday ? 'is-today' : ''} ${
                                  dayShifts.length > 1 ? 'is-clash' : ''
                                }`}
                              >
                                {dayShifts.map((shift) => {
                                  const dotLabel = t('schedule_edit.planner_dot_title', {
                                    name: fullLabel,
                                    date: dateFormatter.format(dayInfo.date),
                                    competence: shift.competence_name,
                                  });
                                  return (
                                    <button
                                      key={shift.id}
                                      type="button"
                                      className="planner-people-dot"
                                      style={{
                                        backgroundColor: competenceColor(
                                          shift.competence_id
                                        ),
                                      }}
                                      onClick={() => onShiftClick(shift)}
                                      title={dotLabel}
                                      aria-label={dotLabel}
                                    />
                                  );
                                })}
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

      {open && (
        <div
          ref={pickerRef}
          className="planner-picker"
          style={pickerStyle}
          role="dialog"
          aria-label={t('schedule_edit.planner_picker_title', {
            competence: open.competence.name,
          })}
        >
          <div className="planner-picker-head">
            <div className="planner-picker-heading">
              <span className="planner-picker-competence">
                <span
                  className="planner-legend-swatch"
                  style={{ backgroundColor: competenceColor(open.competenceId) }}
                  aria-hidden="true"
                />
                {open.competence.name}
              </span>
              <span className="planner-picker-meta">
                {dateFormatter.format(open.day.date)} ·{' '}
                {t('schedule_edit.planner_picker_filled', {
                  filled: assignedOn(open.dateStr, open.competenceId).length,
                  required: requiredFor(open.competenceId, open.day.weekday),
                })}
              </span>
            </div>
            <button
              type="button"
              className="planner-picker-close"
              onClick={() => setPicker(null)}
              title={t('schedule_edit.close')}
            >
              ✕
            </button>
          </div>

          {pickerRows.length === 0 ? (
            <p className="planner-picker-empty">
              {t('schedule_edit.no_eligible_users')}
            </p>
          ) : (
            <ul className="planner-picker-list">
              {pickerRows.map((row) => (
                <li key={row.employee.user_id}>
                  <button
                    type="button"
                    className={`planner-picker-person ${
                      row.shift ? 'is-assigned' : ''
                    } ${row.busyWith ? 'is-busy' : ''}`}
                    onClick={() => togglePerson(row)}
                    disabled={!!row.busyWith}
                  >
                    <span className="planner-picker-check" aria-hidden="true">
                      {row.shift ? '✓' : ''}
                    </span>
                    <span className="planner-picker-person-text">
                      <span className="planner-picker-person-name">
                        {row.employee.full_name || row.employee.email}
                      </span>
                      {row.busyWith && (
                        <span className="planner-picker-person-note">
                          {t('schedule_edit.planner_picker_busy', {
                            competence: row.busyWith.competence_name,
                          })}
                        </span>
                      )}
                    </span>
                    <span
                      className="planner-picker-load"
                      title={t('schedule_edit.planner_picker_load', {
                        shifts: row.load,
                      })}
                    >
                      {row.load}
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
