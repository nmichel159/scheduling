import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  SPECIAL_DAY_SLOT,
  defaultIsSurcharge,
  normalizeWeekdayRequirements,
} from '../utils/competenceRequirements';
import { compareNames, formatShortName } from '../utils/formatEmployeeName';
import {
  CONFLICT_SEVERITY,
  CONFLICT_TYPES,
  COVERAGE_CONFLICT_TYPES,
  SOFT_DECLINE_REASON,
  demandCellKey,
  personCellKey,
  severityOf,
} from '../utils/scheduleConflicts';
import ConflictIcon from './ConflictIcon';
import { ChevronDownIcon, CloseIcon } from './NavIcons';
import './SchedulePlannerView.css';

const pad = (n) => String(n).padStart(2, '0');
const isoDate = (year, month, day) => `${year}-${pad(month + 1)}-${pad(day)}`;
const isoWeekday = (dateObj) => (dateObj.getDay() + 6) % 7;

/* Digits and dots drawn on a filled square. White reads on the darker
   competence colours, but on orange, lime or cyan it all but disappears, so
   those get near-black instead. The threshold keeps white wherever it still
   clears 3:1, which is what bold digits this size need. */
const inkOn = (hex) => {
  const match = /^#?([0-9a-f]{6})$/i.exec(hex || '');
  if (!match) return '#ffffff';
  const value = parseInt(match[1], 16);
  const channel = (shift) => {
    const c = ((value >> shift) & 255) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  const luminance =
    0.2126 * channel(16) + 0.7152 * channel(8) + 0.0722 * channel(0);
  return luminance > 0.3 ? '#16181d' : '#ffffff';
};

/* Mirrors the breakpoint in SchedulePlannerView.css where the two halves
   stack. Stacked, the matrix no longer shares the window with anything, the
   page scrolls past it anyway, and squashing 31 rows into what is left under
   the controls would only make them too small to tap. */
const STACKED_QUERY = '(max-width: 1100px)';
/* Stacked row height: easy to tap, and two pixels short of the widest row so
   seven competences and their tilted names still fit a phone's width. */
const STACKED_ROW_HEIGHT = 24;

/* The competence picker is a fixed-position panel anchored next to the cell
   that opened it, so these have to be known here to keep it inside the
   viewport. */
const PICKER_WIDTH = 300;
const PICKER_MAX_HEIGHT = 320;
const PICKER_MARGIN = 12;

/* The people list is a floating panel anchored to the square that opened it,
   so it has to know its own size to stay inside the viewport. It is laid out
   in columns of at most ten names rather than as one long list: a workplace
   where thirty people hold the same competence is exactly the case where the
   whole roster has to be comparable at a glance, and a scrolling column shows
   ten of them. */
const DETAIL_COL_WIDTH = 184;
const DETAIL_MAX_ROWS = 10;
const DETAIL_MAX_COLS = 4;
const DETAIL_CHROME = 18; // borders + the grid's own padding
const DETAIL_MAX_HEIGHT = 380;

/* Every day of the month has to be on screen at once, so the row height is not
   a fixed number but whatever divides the space actually left under the matrix.
   It is measured rather than guessed with svh units: what sits above the table
   changes with the workplace header, an error banner, the sidebar being folded
   away, so only the real position of the table can say how much room is left. */
/* Air under the last day, plus the padding and border of the card the matrix
   sits in: the whole card has to close inside the window, not just the table. */
const MATRIX_BOTTOM_GAP = 30;
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
/* Air above the tilted names, and room for their own line height, which
   leans upwards with them: without it the top of the longest name was cut
   off by the edge of the scrolling pane. Kept equal to the 20px in
   --planner-head-h in the stylesheet. */
const LABEL_PADDING = 20;

/* How many conflicts the panel lists before it counts the rest. The list
   scrolls on its own, so this only bounds what a month with hundreds of
   empty squares puts into the page. */
const CONFLICT_LIST_LIMIT = 60;
/* How many conflict glyphs a name in the people list carries; the tooltip
   has them all. */
const ROW_GLYPH_LIMIT = 3;
const NO_CONFLICTS = [];

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
 *   square opens the workplace's people, the ones holding that competence
 *   first, each with the duties they already carry split into the surcharged
 *   and the ordinary ones — which is the number the choice is actually made
 *   on. Filling the square is one click on a name.
 *
 * - Right: people. One row per employee, one column per day, a coloured dot
 *   where they serve. This is the half that answers "who is overloaded", "who
 *   has not been used" and "is anyone on two duties in one day" — none of
 *   which the demand matrix can show. Clicking a person's day offers every
 *   competence of the workplace, so the same month can be filled from the
 *   person's side as well as from the day's.
 *
 * Nothing is refused: anybody can be put into any square, a second role on
 * the same day included. What that breaks is shown instead — a marked cell
 * in both halves wherever a conflict sits, the conflicts listed by type above
 * the people grid (clicking a type or an item points at its cells), and next
 * to every name and competence the planner offers, what picking it would
 * break before it is picked.
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
 * - conflictReport: analyzeScheduleConflicts() over the same shifts — every
 *   conflict, indexed by the cells it marks, plus forCandidate() for what a
 *   pick would break.
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
 * - period — the page's month stepper, which leads the generate toolbar.
 */
const SchedulePlannerView = ({
  header,
  period,
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
  conflictReport,
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
  const rootRef = useRef(null);
  // The conflict type whose cells are singled out, and the one conflict whose
  // cells are pointed at -- both picked in the conflicts panel.
  const [conflictFocus, setConflictFocus] = useState(null);
  const [conflictTarget, setConflictTarget] = useState(null);
  const [conflictsOpen, setConflictsOpen] = useState(true);
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
        compareNames(a.full_name || a.email, b.full_name || b.email)
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
   * cell.
   *
   * Scrolling the page or resizing the window closes it as well: the panels
   * are pinned to where their square was when it was clicked, and once the
   * square has moved away the panel would name a day it no longer sits
   * beside. A scroll inside the panel itself (a long roster) is left alone. */
  useEffect(() => {
    if (!openDemand && !openPerson) return undefined;
    const closeAll = () => {
      setDemandCell(null);
      setPersonCell(null);
    };
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') closeAll();
    };
    const handlePointerDown = (e) => {
      if (!pickerRef.current?.contains(e.target)) setPersonCell(null);
      if (!detailRef.current?.contains(e.target)) setDemandCell(null);
    };
    const handleScroll = (e) => {
      if (
        pickerRef.current?.contains(e.target) ||
        detailRef.current?.contains(e.target)
      ) {
        return;
      }
      closeAll();
    };
    window.addEventListener('keydown', handleKeyDown);
    document.addEventListener('mousedown', handlePointerDown);
    window.addEventListener('scroll', handleScroll, true);
    window.addEventListener('resize', closeAll);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('mousedown', handlePointerDown);
      window.removeEventListener('scroll', handleScroll, true);
      window.removeEventListener('resize', closeAll);
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
      const stacked = window.matchMedia(STACKED_QUERY).matches;
      /* Stacked, the month is simply given comfortable rows and the page
         scrolls; the window height has nothing left to say about them. */
      const room = stacked
        ? Number.POSITIVE_INFINITY
        : window.innerHeight - el.getBoundingClientRect().top - MATRIX_BOTTOM_GAP;

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
        stacked ? STACKED_ROW_HEIGHT : MAX_ROW_HEIGHT,
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

  /* ---------- conflicts: what they say and where they sit ---------- */

  const shortDateFormatter = useMemo(
    () => new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'numeric' }),
    [locale]
  );
  const formatIso = (iso) => shortDateFormatter.format(new Date(`${iso}T00:00:00`));

  const competenceById = useMemo(
    () => new Map(competences.map((competence) => [competence.id, competence])),
    [competences]
  );
  const competenceName = (id) => competenceById.get(id)?.name || '';
  const personName = (userId) => {
    const employee = employeeById.get(userId);
    return formatShortName(employee?.full_name) || employee?.email || '';
  };
  const typeLabel = (type) => t(`schedule_edit.conflicts.types.${type}`);
  const reasonLabel = (reason) =>
    t(`schedule_edit.conflicts.reasons.${reason}`, {
      defaultValue: t('schedule_edit.conflicts.reasons.UNAVAILABLE'),
    });

  /** The specifics of one conflict, without its type -- the type is the glyph. */
  const conflictDetail = (conflict) => {
    switch (conflict.type) {
      case 'unqualified':
        return competenceName(conflict.competenceId);
      case 'unavailable':
        return reasonLabel(conflict.reason);
      case 'double_role':
        return conflict.competenceIds.map(competenceName).join(' + ');
      case 'other_workplace':
        return conflict.workplaces.join(', ');
      case 'rest': {
        const values = {
          first: formatIso(conflict.firstDate),
          second: formatIso(conflict.secondDate),
          workplaces: conflict.workplaces.join(', '),
        };
        return conflict.workplaces.length > 0
          ? t('schedule_edit.conflicts.detail.rest_elsewhere', values)
          : t('schedule_edit.conflicts.detail.rest', values);
      }
      case 'understaffed':
      case 'overstaffed':
        return t('schedule_edit.conflicts.detail.coverage', {
          competence: competenceName(conflict.competenceId),
          filled: conflict.filled,
          required: conflict.required,
        });
      case 'over_wish':
        return t('schedule_edit.conflicts.detail.over_wish', {
          count: conflict.count,
          max: conflict.max,
        });
      default:
        return '';
    }
  };

  /** One tooltip line: the type, then what exactly. */
  const conflictLine = (conflict) => {
    const detail = conflictDetail(conflict);
    return detail ? `${typeLabel(conflict.type)}: ${detail}` : typeLabel(conflict.type);
  };

  /** What picking a name or a competence would break, as a short phrase. */
  const candidateLine = (item) => {
    switch (item.type) {
      case 'unavailable':
        return reasonLabel(item.reason);
      case 'double_role':
        return t('schedule_edit.conflicts.candidate.double_role', {
          competences: item.competenceIds.map(competenceName).join(', '),
        });
      case 'other_workplace':
        return t('schedule_edit.conflicts.candidate.other_workplace', {
          workplaces: item.workplaces.join(', '),
        });
      case 'rest':
        return t('schedule_edit.conflicts.candidate.rest', {
          dates: item.dates.map(formatIso).join(', '),
        });
      case 'over_wish':
        return t('schedule_edit.conflicts.candidate.over_wish', {
          count: item.count,
          max: item.max,
        });
      default:
        return typeLabel(item.type);
    }
  };

  /* The focused type counts only while the month still has one of it, and
     the pointed-at conflict only while it still exists: a fix clears either
     without anyone having to switch it off. */
  const conflicts = conflictReport?.conflicts || NO_CONFLICTS;
  const activeFocus =
    conflictFocus && conflictReport?.counts[conflictFocus] ? conflictFocus : null;
  const target = useMemo(
    () => conflicts.find((conflict) => conflict.key === conflictTarget) || null,
    [conflicts, conflictTarget]
  );
  const targetCells = useMemo(() => new Set(target?.cells || []), [target]);
  const targetDemandCells = useMemo(() => new Set(target?.demandCells || []), [target]);
  const targetRows = useMemo(() => new Set(target?.rows || []), [target]);

  /* Without a type picked the list holds what concerns people; the empty and
     overfilled squares are already plain to see in the matrix, and a fresh
     month has hundreds of them. Picking their type lists them too. */
  const listedConflicts = useMemo(
    () =>
      activeFocus
        ? conflicts.filter((conflict) => conflict.type === activeFocus)
        : conflicts.filter((conflict) => !COVERAGE_CONFLICT_TYPES.has(conflict.type)),
    [conflicts, activeFocus]
  );

  const conflictClasses = (cellConflicts, isTarget) => {
    const severity = severityOf(cellConflicts);
    const isFocus =
      activeFocus != null && cellConflicts.some((conflict) => conflict.type === activeFocus);
    return [
      severity ? `has-conflict is-${severity}` : '',
      isFocus ? 'is-conflict-focus' : '',
      isTarget ? 'is-conflict-target' : '',
    ]
      .filter(Boolean)
      .join(' ');
  };

  const toggleConflictFocus = (type) => {
    setConflictTarget(null);
    setConflictFocus((current) => (current === type ? null : type));
  };

  /** Point at one conflict's cells and bring the first of them into view. */
  const showConflict = (conflict) => {
    if (conflictTarget === conflict.key) {
      setConflictTarget(null);
      return;
    }
    setConflictTarget(conflict.key);
    let selector = null;
    if (conflict.cells[0]) selector = `[data-person-cell="${conflict.cells[0]}"]`;
    else if (conflict.demandCells[0]) {
      selector = `[data-demand-cell="${conflict.demandCells[0]}"]`;
    } else if (conflict.rows[0] != null) {
      selector = `[data-person-row="${conflict.rows[0]}"]`;
    }
    if (!selector) return;
    window.requestAnimationFrame(() => {
      rootRef.current
        ?.querySelector(selector)
        ?.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' });
    });
  };

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
      .map((employee) => {
        const mine = dayShifts.find(
          (s) =>
            s.user_id === employee.user_id &&
            s.competence_id === openDemand.competenceId
        );
        const warnings = conflictReport
          ? conflictReport.forCandidate(
              employee.user_id,
              openDemand.dateStr,
              openDemand.competenceId,
              mine?.id ?? null
            )
          : [];
        return {
          employee,
          shift: mine || null,
          qualified: (employee.competences || []).some(
            (c) => c.id === openDemand.competenceId
          ),
          warnings,
          severity: severityOf(warnings),
          stats: statsFor(employee.user_id),
        };
      })
      .sort((a, b) => {
        // Assigned first (so removing is easy), then the qualified who can
        // take the duty cleanly, least served first, then the qualified it
        // would put in conflict, and last everybody without the competence.
        const rank = (row) => {
          if (row.shift) return 0;
          if (!row.qualified) return 3;
          return row.severity === 'error' ? 2 : 1;
        };
        return (
          rank(a) - rank(b) ||
          a.stats.total - b.stats.total ||
          compareNames(a.employee.full_name, b.employee.full_name)
        );
      });
  }, [openDemand, employees, shiftsByDate, dutyStats, conflictReport]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleAssignment = (dateStr, competenceId, row) => {
    if (row.shift) onRemoveShift(row.shift.id);
    else onAssign(dateStr, competenceId, row.employee.user_id);
  };

  /* Fill columns top to bottom, ten names each, and let the panel be as wide
     as the columns it ends up with -- but never wider than the window: on a
     phone there is room for one or two, and the rest of the roster scrolls
     inside the panel instead of hanging off the edge of the screen. */
  const detailGrid = useMemo(() => {
    const count = Math.max(1, demandRows.length);
    const fitting = Math.max(
      1,
      Math.floor(
        (window.innerWidth - 2 * PICKER_MARGIN - DETAIL_CHROME) / DETAIL_COL_WIDTH
      )
    );
    const columns = Math.min(
      DETAIL_MAX_COLS,
      fitting,
      Math.ceil(count / DETAIL_MAX_ROWS)
    );
    return { columns, rows: Math.ceil(count / columns) };
  }, [demandRows.length]);

  /* Anchored to the right of the square it belongs to, and pulled back inside
     the viewport near the edges of the month. */
  const detailStyle = useMemo(() => {
    if (!openDemand?.anchor) return null;
    const { anchor } = openDemand;
    const width = Math.min(
      detailGrid.columns * DETAIL_COL_WIDTH + DETAIL_CHROME,
      window.innerWidth - 2 * PICKER_MARGIN
    );
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

  /* Every competence of the workplace, the ones the person does not hold
     included -- they are marked, not hidden. What a pick would break is split
     in two: whatever holds for every row (an absence, the rest, a duty
     elsewhere) is said once under the name, and only what differs from one
     competence to the next stays on its row. */
  const personPicker = useMemo(() => {
    if (!openPerson) return { rows: [], shared: [] };
    const dayShifts = shiftsByDate[openPerson.dateStr] || [];
    const userId = openPerson.employee.user_id;
    const rows = competences.map((competence) => {
      const mine = dayShifts.find(
        (s) => s.user_id === userId && s.competence_id === competence.id
      );
      return {
        competence,
        shift: mine || null,
        warnings: conflictReport
          ? conflictReport.forCandidate(
              userId,
              openPerson.dateStr,
              competence.id,
              mine?.id ?? null
            )
          : [],
        filled: dayShifts.filter((s) => s.competence_id === competence.id).length,
        required: requiredFor(competence.id, openPerson.day.slot),
      };
    });
    // Shared means said the same way on every row: "already on" names the
    // other roles, which differ from row to row, so it never moves up.
    const keyOf = (item) => JSON.stringify(item);
    const sharedKeys = new Set(
      rows.length > 0
        ? rows[0].warnings
            .map(keyOf)
            .filter((key) => rows.every((row) => row.warnings.some((item) => keyOf(item) === key)))
        : []
    );
    return {
      shared: rows[0]?.warnings.filter((item) => sharedKeys.has(keyOf(item))) || [],
      rows: rows.map((row) => {
        const own = row.warnings.filter((item) => !sharedKeys.has(keyOf(item)));
        return { ...row, own, severity: severityOf(row.warnings) };
      }),
    };
  }, [openPerson, competences, shiftsByDate, slotsByCompetence, conflictReport]); // eslint-disable-line react-hooks/exhaustive-deps
  const personRows = personPicker.rows;

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
    return {
      left,
      top,
      width: Math.min(PICKER_WIDTH, window.innerWidth - 2 * PICKER_MARGIN),
      maxHeight: PICKER_MAX_HEIGHT,
    };
  }, [openPerson]);

  const togglePersonDuty = (row) => {
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
    <div
      ref={rootRef}
      className={`planner ${loading ? 'is-loading' : ''} ${
        activeFocus || target ? 'has-conflict-focus' : ''
      }`}
      aria-busy={loading}
    >
      <div className="planner-split">
        {/* ---------- left: demand per day ----------
            First thing on the page and flush with its top edge: it is the half
            that is worked in, and every pixel spent above it is taken off the
            row height that has to carry all 31 days. Everything else — the
            generate button, the legend, the shortfall — moved across to the
            right column for the same reason. */}
        <section className="card planner-pane planner-pane-demand">
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
                      <span className="visually-hidden">
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
                          dayInfo.isWeekend || dayInfo.isRestDay ? 'is-weekend' : ''
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
                            const color = competenceColor(competence.id);

                            /* The square's own shortfall or surplus is its colour
                               already; the corner mark is for the people in it --
                               somebody unqualified, absent, doubled up, unrested. */
                            const cellKey = demandCellKey(dayInfo.dateStr, competence.id);
                            const cellConflicts =
                              conflictReport?.byDemandCell.get(cellKey) || NO_CONFLICTS;
                            const peopleConflicts = cellConflicts.filter(
                              (conflict) => !COVERAGE_CONFLICT_TYPES.has(conflict.type)
                            );
                            const markSeverity = severityOf(peopleConflicts);
                            const isFocus =
                              activeFocus != null &&
                              cellConflicts.some((conflict) => conflict.type === activeFocus);
                            const cellTitle = [
                              t('schedule_edit.planner_cell_title', {
                                date: dateFormatter.format(dayInfo.date),
                                competence: competence.name,
                                filled,
                                required,
                              }),
                              ...peopleConflicts.map(
                                (conflict) =>
                                  `${personName(conflict.userId)} – ${conflictLine(conflict)}`
                              ),
                            ].join('\n');

                            return (
                              <td
                                key={competence.id}
                                className={`planner-matrix-cell ${
                                  markSeverity ? `has-conflict is-${markSeverity}` : ''
                                } ${isFocus ? 'is-conflict-focus' : ''} ${
                                  targetDemandCells.has(cellKey) ? 'is-conflict-target' : ''
                                }`}
                                data-demand-cell={cellKey}
                              >
                                <button
                                  type="button"
                                  className={`planner-square is-${state} ${
                                    isOpen ? 'is-open' : ''
                                  }`}
                                  style={{
                                    '--square-color': color,
                                    '--square-ink': inkOn(color),
                                    '--square-fill': required
                                      ? `${Math.round((filled / required) * 100)}%`
                                      : '100%',
                                  }}
                                  onClick={(e) =>
                                    toggleDemandCell(e, dayInfo.dateStr, competence.id)
                                  }
                                  aria-expanded={isOpen}
                                  aria-label={cellTitle}
                                  title={cellTitle}
                                >
                                  {showDot ? (
                                    <span
                                      className="planner-square-dot"
                                      aria-hidden="true"
                                    />
                                  ) : (
                                    <span
                                      className="planner-square-count"
                                      aria-hidden="true"
                                    >
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
          {header && <div className="planner-header">{header}</div>}

          <div className="card planner-toolbar">
            <div className="planner-toolbar-row">
              {period}

              <div className="planner-toolbar-actions">
                {onGenerate && (
                  <button
                    type="button"
                    className="btn btn-primary planner-generate"
                    onClick={onGenerate}
                    disabled={generateDisabled}
                    title={generateHint}
                  >
                    {generateLabel}
                  </button>
                )}

                {onTimeBudgetChange && (
                  <select
                    className="select planner-time-budget"
                    value={timeBudget}
                    onChange={(event) => onTimeBudgetChange(Number(event.target.value))}
                    disabled={generateDisabled}
                    aria-label={t('schedule_edit.time_budget_label')}
                    title={t('schedule_edit.time_budget_label')}
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
                    className="btn planner-clear"
                    onClick={onClear}
                    disabled={clearDisabled}
                  >
                    {clearLabel}
                  </button>
                )}
              </div>

              {/* Pushed to the far end: it is the one number that says whether
                  the month is finished, so it does not sit inside the legend. */}
              {hasCompetences && (
                <span
                  className={`badge badge-dot planner-missing ${
                    missingTotal === 0 ? 'badge-success' : 'badge-danger'
                  }`}
                  title={t('schedule_edit.planner_missing_hint')}
                >
                  {missingTotal === 0
                    ? t('schedule_edit.planner_missing_none')
                    : t('schedule_edit.planner_missing', { missing: missingTotal })}
                </span>
              )}
            </div>

            {hasCompetences && (
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
            )}
          </div>

          {conflicts.length > 0 && (
            <section
              className="card planner-conflicts"
              aria-labelledby="planner-conflicts-title"
            >
              <button
                type="button"
                className="planner-conflicts-head"
                onClick={() => setConflictsOpen((open) => !open)}
                aria-expanded={conflictsOpen}
                title={
                  conflictsOpen
                    ? t('schedule_edit.conflicts.collapse')
                    : t('schedule_edit.conflicts.expand')
                }
              >
                <h2 id="planner-conflicts-title" className="planner-pane-title">
                  {t('schedule_edit.conflicts.title')}
                </h2>
                <span
                  className={`badge ${
                    conflictReport.errorCount > 0 ? 'badge-danger' : 'badge-warning'
                  }`}
                >
                  {conflicts.length}
                </span>
                <ChevronDownIcon
                  className={`planner-conflicts-chevron ${conflictsOpen ? 'is-open' : ''}`}
                />
              </button>

              {conflictsOpen && (
                <>
                  <div className="planner-conflict-types">
                    {CONFLICT_TYPES.filter((type) => conflictReport.counts[type]).map(
                      (type) => (
                        <button
                          key={type}
                          type="button"
                          className={`planner-conflict-type is-${CONFLICT_SEVERITY[type]} ${
                            activeFocus === type ? 'is-active' : ''
                          }`}
                          onClick={() => toggleConflictFocus(type)}
                          aria-pressed={activeFocus === type}
                        >
                          <ConflictIcon type={type} className="planner-conflict-glyph" />
                          <span>{typeLabel(type)}</span>
                          <span className="planner-conflict-type-count">
                            {conflictReport.counts[type]}
                          </span>
                        </button>
                      )
                    )}
                  </div>

                  {listedConflicts.length > 0 && (
                    <ul className="planner-conflict-list">
                      {listedConflicts.slice(0, CONFLICT_LIST_LIMIT).map((conflict) => {
                        const detail = conflictDetail(conflict);
                        return (
                          <li key={conflict.key}>
                            <button
                              type="button"
                              className={`planner-conflict-item is-${conflict.severity} ${
                                conflictTarget === conflict.key ? 'is-active' : ''
                              }`}
                              onClick={() => showConflict(conflict)}
                              aria-pressed={conflictTarget === conflict.key}
                              title={conflictLine(conflict)}
                            >
                              <ConflictIcon
                                type={conflict.type}
                                className="planner-conflict-glyph"
                              />
                              <span className="planner-conflict-date">
                                {conflict.date ? formatIso(conflict.date) : ''}
                              </span>
                              {conflict.userId != null && (
                                <span className="planner-conflict-person">
                                  {personName(conflict.userId)}
                                </span>
                              )}
                              {!activeFocus && (
                                <span className="planner-conflict-kind">
                                  {typeLabel(conflict.type)}
                                </span>
                              )}
                              {detail && (
                                <span className="planner-conflict-detail">{detail}</span>
                              )}
                            </button>
                          </li>
                        );
                      })}
                      {listedConflicts.length > CONFLICT_LIST_LIMIT && (
                        <li className="planner-conflict-more">
                          {t('schedule_edit.conflicts.more', {
                            count: listedConflicts.length - CONFLICT_LIST_LIMIT,
                          })}
                        </li>
                      )}
                    </ul>
                  )}
                </>
              )}
            </section>
          )}

          <section className="card planner-pane planner-pane-people">
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
                            dayInfo.isWeekend || dayInfo.isRestDay ? 'is-weekend' : ''
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
                      <th
                        scope="col"
                        className="planner-people-total-head is-surcharge"
                      >
                        {t('schedule_edit.planner_surcharge')}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {people.map((employee) => {
                      const byDate = shiftsByUserDate.get(employee.user_id);
                      const stats = statsFor(employee.user_id);
                      const fullLabel = employee.full_name || employee.email;
                      // The whole month is the conflict here -- more duties
                      // than the person asked for -- so it marks the row.
                      const rowConflicts =
                        conflictReport?.byUser.get(employee.user_id) || NO_CONFLICTS;
                      const rowClasses = conflictClasses(
                        rowConflicts,
                        targetRows.has(employee.user_id)
                      );
                      return (
                        <tr key={employee.user_id}>
                          <th
                            scope="row"
                            className={`planner-people-name ${rowClasses}`}
                            title={[fullLabel, ...rowConflicts.map(conflictLine)].join('\n')}
                            data-person-row={employee.user_id}
                          >
                            {formatShortName(employee.full_name) || employee.email}
                          </th>
                          {days.map((dayInfo) => {
                            const dayShifts = byDate?.get(dayInfo.dateStr) || [];
                            const isOpen =
                              openPerson?.dateStr === dayInfo.dateStr &&
                              openPerson?.userId === employee.user_id;
                            const cellKey = personCellKey(employee.user_id, dayInfo.dateStr);
                            const cellConflicts =
                              conflictReport?.byCell.get(cellKey) || NO_CONFLICTS;
                            /* An absence or a duty elsewhere is marked even on a
                               free day: it is where the next conflict would be. */
                            const note = conflictReport?.notesByCell.get(cellKey);
                            const isAbsent =
                              note?.reason != null && note.reason !== SOFT_DECLINE_REASON;
                            const isElsewhere = (note?.workplaces.length ?? 0) > 0;
                            const noteLines = [
                              isAbsent ? reasonLabel(note.reason) : null,
                              note?.reason === SOFT_DECLINE_REASON
                                ? typeLabel('soft_decline')
                                : null,
                              isElsewhere
                                ? t('schedule_edit.conflicts.candidate.other_workplace', {
                                    workplaces: note.workplaces.join(', '),
                                  })
                                : null,
                            ].filter(Boolean);
                            const slotTitle = [
                              dayShifts.length > 0
                                ? dayShifts
                                    .map((shift) =>
                                      t('schedule_edit.planner_dot_title', {
                                        name: fullLabel,
                                        date: dateFormatter.format(dayInfo.date),
                                        competence:
                                          shift.competence_name ||
                                          competenceName(shift.competence_id),
                                      })
                                    )
                                    .join('\n')
                                : `${fullLabel} — ${dateFormatter.format(dayInfo.date)}`,
                              ...(cellConflicts.length > 0
                                ? cellConflicts.map(conflictLine)
                                : noteLines),
                            ].join('\n');
                            return (
                              <td
                                key={dayInfo.dateStr}
                                className={`planner-people-cell ${
                                  dayInfo.isWeekend || dayInfo.isRestDay
                                    ? 'is-weekend'
                                    : ''
                                } ${dayInfo.isToday ? 'is-today' : ''} ${
                                  isAbsent ? 'is-absent' : ''
                                } ${conflictClasses(cellConflicts, targetCells.has(cellKey))}`}
                                data-person-cell={cellKey}
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
                                  aria-expanded={isOpen}
                                  aria-label={slotTitle}
                                  title={slotTitle}
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
                                  {dayShifts.length === 0 && isElsewhere && (
                                    <span
                                      className="planner-people-dot is-elsewhere"
                                      aria-hidden="true"
                                    />
                                  )}
                                </button>
                              </td>
                            );
                          })}
                          <td
                            className={`planner-people-total ${
                              rowConflicts.length > 0 ? 'is-over-wish' : ''
                            }`}
                          >
                            {stats.total || ''}
                          </td>
                          <td className="planner-people-total is-surcharge">
                            {stats.surcharge || ''}
                          </td>
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
          className="planner-popover planner-detail"
          style={detailStyle}
          role="dialog"
          aria-label={t('schedule_edit.planner_picker_title', {
            competence: openDemand.competence.name,
          })}
        >
          <div className="planner-popover-head">
            <div className="planner-popover-heading">
              <span className="planner-popover-title">
                <span
                  className="planner-legend-swatch"
                  style={{
                    backgroundColor: competenceColor(openDemand.competenceId),
                  }}
                  aria-hidden="true"
                />
                {openDemand.competence.name}
              </span>
              <span className="planner-popover-meta">
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
            </div>
            <button
              type="button"
              className="dialog-close planner-popover-close"
              onClick={() => setDemandCell(null)}
              title={t('schedule_edit.close')}
              aria-label={t('schedule_edit.close')}
            >
              <CloseIcon />
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
            <p className="planner-popover-empty">
              {t('schedule_edit.planner_people_empty')}
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
                    } ${row.qualified ? '' : 'is-unqualified'} ${
                      row.severity ? `has-warning is-${row.severity}` : ''
                    }`}
                    onClick={() =>
                      toggleAssignment(
                        openDemand.dateStr,
                        openDemand.competenceId,
                        row
                      )
                    }
                    aria-pressed={!!row.shift}
                    title={[fullLabel, ...row.warnings.map(candidateLine)].join('\n')}
                  >
                    <span className="planner-check" aria-hidden="true" />
                    <span className="planner-detail-name">
                      {formatShortName(row.employee.full_name) ||
                        row.employee.email}
                    </span>
                    {row.warnings.length > 0 && (
                      <span className="planner-conflict-glyphs" aria-hidden="true">
                        {row.warnings.slice(0, ROW_GLYPH_LIMIT).map((item) => (
                          <ConflictIcon
                            key={item.type}
                            type={item.type}
                            className={`planner-conflict-glyph is-${item.severity}`}
                          />
                        ))}
                      </span>
                    )}
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
          className="planner-popover planner-picker"
          style={pickerStyle}
          role="dialog"
          aria-label={t('schedule_edit.planner_person_picker_title', {
            name: openPerson.employee.full_name || openPerson.employee.email,
          })}
        >
          <div className="planner-popover-head has-divider">
            <div className="planner-popover-heading">
              <span className="planner-popover-title">
                {openPerson.employee.full_name || openPerson.employee.email}
              </span>
              <span className="planner-popover-meta">
                {dateFormatter.format(openPerson.day.date)}
              </span>
              {personPicker.shared.length > 0 && (
                <span className="planner-picker-warnings">
                  {personPicker.shared.map((item) => (
                    <span
                      key={item.type}
                      className={`planner-picker-warning is-${item.severity}`}
                    >
                      <ConflictIcon type={item.type} className="planner-conflict-glyph" />
                      {candidateLine(item)}
                    </span>
                  ))}
                </span>
              )}
            </div>
            <button
              type="button"
              className="dialog-close planner-popover-close"
              onClick={() => setPersonCell(null)}
              title={t('schedule_edit.close')}
              aria-label={t('schedule_edit.close')}
            >
              <CloseIcon />
            </button>
          </div>

          {personRows.length === 0 ? (
            <p className="planner-popover-empty">{t('schedule_edit.legend_empty')}</p>
          ) : (
            <ul className="planner-picker-list">
              {personRows.map((row) => (
                <li key={row.competence.id}>
                  <button
                    type="button"
                    className={`planner-picker-option ${
                      row.shift ? 'is-assigned' : ''
                    } ${row.severity ? `has-warning is-${row.severity}` : ''}`}
                    onClick={() => togglePersonDuty(row)}
                    aria-pressed={!!row.shift}
                  >
                    <span className="planner-check" aria-hidden="true" />
                    <span
                      className="planner-legend-swatch"
                      style={{
                        backgroundColor: competenceColor(row.competence.id),
                      }}
                      aria-hidden="true"
                    />
                    <span className="planner-picker-option-text">
                      <span className="planner-picker-option-name">
                        {row.competence.name}
                      </span>
                      {row.own.length > 0 && (
                        <span className="planner-picker-warnings">
                          {row.own.map((item) => (
                            <span
                              key={item.type}
                              className={`planner-picker-warning is-${item.severity}`}
                            >
                              <ConflictIcon
                                type={item.type}
                                className="planner-conflict-glyph"
                              />
                              {candidateLine(item)}
                            </span>
                          ))}
                        </span>
                      )}
                    </span>
                    <span
                      className={`planner-picker-load ${
                        row.required > 0 && row.filled >= row.required
                          ? 'is-full'
                          : ''
                      }`}
                    >
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
