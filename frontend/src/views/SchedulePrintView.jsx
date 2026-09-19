import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  fetchCompetences,
  fetchEmployeeCompetenceTable,
} from '../services/competenceService';
import { fetchAmbulanceSchedule } from '../services/scheduleService';
import { fetchSpecialDays } from '../services/specialDayService';
import { useWorkplace } from '../hooks/workplaceContext';
import { formatShortName } from '../utils/formatEmployeeName';
import { downloadCsv, downloadXlsx } from '../utils/tableExport';
import './SchedulePrintView.css';

const pad = (n) => String(n).padStart(2, '0');
const isoDate = (year, month, day) => `${year}-${pad(month + 1)}-${pad(day)}`;
const isoWeekday = (dateObj) => (dateObj.getDay() + 6) % 7;

const MONTHS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
const YEAR_SPAN = 2;

/* A4 in millimetres, and the margin the page rule reserves on every side. The
   sheet below is built at exactly what is left, so what is on screen is the
   printable area itself rather than a likeness of it. */
const PAGE_MARGIN_MM = 8;
const A4_SHORT_MM = 210;
const A4_LONG_MM = 297;

/* The one rule the sheet may not break is fitting on a single A4, so the type
   size is not chosen but found: the table is laid out, measured against the
   page, and the size halved in on until the largest one that still fits is
   known. Eight steps land within a twentieth of a pixel of it, which is finer
   than any printer resolves. */
const MIN_FONT_PX = 3;
const MAX_FONT_PX = 13;
const FIT_STEPS = 8;

const slugify = (value) =>
  (value || 'rozvrh')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .toLowerCase() || 'rozvrh';

/**
 * Printing the finished month.
 *
 * The schedule is worked out on screen but it is lived with on paper — pinned
 * to a wall, carried to a ward round, handed over at a shift change. That is
 * one table: a row per day, a column per competence, names in the squares.
 * Its only hard requirement is that a month never runs onto a second sheet,
 * because a rota split across two pages is a rota nobody trusts.
 *
 * The same month leaves in three ways, which are three different jobs rather
 * than three formats of one: the printed sheet for the wall, the spreadsheet
 * for whoever reworks it into payroll or a clinic's own template, and the CSV
 * for everything else. All of them are written from a single table model, so
 * the columns cannot drift apart between them.
 *
 * The second layout turns the same month on its side — a row per person, a
 * column per day — which is the sheet somebody reads to find their own name
 * rather than the day's cover. Its squares carry the competence's number from
 * the legend, since a name will not fit in a column a month wide; the exported
 * files, which have no such limit, carry the competence name itself.
 */
const SchedulePrintView = () => {
  const { t, i18n } = useTranslation();
  const {
    workplaces,
    activeId,
    active,
    loading: workplacesLoading,
    forbidden,
  } = useWorkplace();

  const today = useMemo(() => new Date(), []);
  const [month, setMonth] = useState(today.getMonth());
  const [year, setYear] = useState(today.getFullYear());
  const [layout, setLayout] = useState('competences');
  const [orientation, setOrientation] = useState('portrait');
  const [nameStyle, setNameStyle] = useState('short');

  const [shifts, setShifts] = useState([]);
  const [competences, setCompetences] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [restDays, setRestDays] = useState(() => new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const sheetRef = useRef(null);
  const bodyRef = useRef(null);
  const stageRef = useRef(null);
  const [preview, setPreview] = useState({ scale: 1, height: 0 });

  // Only the newest load may publish: switching month or workplace leaves the
  // previous request in flight, and a slower earlier answer would otherwise
  // print a different month than the toolbar names.
  const loadRequestId = useRef(0);

  const years = useMemo(() => {
    const current = new Date().getFullYear();
    return Array.from(
      { length: YEAR_SPAN * 2 + 1 },
      (_unused, offset) => current - YEAR_SPAN + offset
    );
  }, []);

  const load = useCallback(async () => {
    if (activeId == null) return;
    const requestId = loadRequestId.current + 1;
    loadRequestId.current = requestId;
    setLoading(true);
    setError(null);
    try {
      const [scheduleData, competenceData, employeeData] = await Promise.all([
        fetchAmbulanceSchedule(activeId, { month: month + 1, year }),
        fetchCompetences(activeId),
        fetchEmployeeCompetenceTable(activeId),
      ]);
      if (loadRequestId.current !== requestId) return;
      setShifts(scheduleData);
      setCompetences(competenceData);
      setEmployees(employeeData);
    } catch {
      if (loadRequestId.current !== requestId) return;
      setShifts([]);
      setCompetences([]);
      setEmployees([]);
      setError(t('schedule_print.load_error'));
    } finally {
      if (loadRequestId.current === requestId) setLoading(false);
    }
  }, [activeId, month, year, t]);

  useEffect(() => {
    load();
  }, [load]);

  /* The special-day calendar is a year at a time and fails silently: without
     it the sheet only loses the shading on public holidays. */
  useEffect(() => {
    if (activeId == null) {
      setRestDays(new Set());
      return undefined;
    }
    let live = true;
    fetchSpecialDays(activeId, year)
      .then((data) => {
        if (!live) return;
        setRestDays(
          new Set(
            (data.entries || [])
              .filter((entry) => entry.is_rest_day)
              .map((entry) => entry.day)
          )
        );
      })
      .catch(() => {
        if (live) setRestDays(new Set());
      });
    return () => {
      live = false;
    };
  }, [activeId, year]);

  const locale = i18n.language?.startsWith('en') ? 'en-GB' : 'sk-SK';

  const weekdayShort = useMemo(
    () => new Intl.DateTimeFormat(locale, { weekday: 'short' }),
    [locale]
  );

  const days = useMemo(() => {
    const count = new Date(year, month + 1, 0).getDate();
    return Array.from({ length: count }, (_unused, index) => {
      const day = index + 1;
      const date = new Date(year, month, day);
      const dateStr = isoDate(year, month, day);
      const weekday = isoWeekday(date);
      const isRestDay = restDays.has(dateStr);
      return {
        day,
        date,
        dateStr,
        weekday,
        isRestDay,
        muted: weekday >= 5 || isRestDay,
        weekdayLabel: weekdayShort.format(date).replace(/\.$/, ''),
      };
    });
  }, [year, month, restDays, weekdayShort]);

  const orderedCompetences = useMemo(
    () => [...competences].sort((a, b) => a.id - b.id),
    [competences]
  );

  const shiftsByDate = useMemo(() => {
    const map = new Map();
    shifts.forEach((shift) => {
      const list = map.get(shift.work_date) || [];
      list.push(shift);
      map.set(shift.work_date, list);
    });
    return map;
  }, [shifts]);

  const nameOf = useCallback(
    (shift) => {
      const full = shift.user_full_name || shift.user_email || '';
      return nameStyle === 'full' ? full : formatShortName(full) || full;
    },
    [nameStyle]
  );

  /* Everyone the month can name: the workplace's roster, plus anyone holding a
     duty who has since left it — their duties are still on the sheet and a row
     they are missing from would silently drop them. */
  const people = useMemo(() => {
    const map = new Map();
    employees.forEach((employee) =>
      map.set(employee.user_id, employee.full_name || employee.email || '')
    );
    shifts.forEach((shift) => {
      if (!map.has(shift.user_id)) {
        map.set(shift.user_id, shift.user_full_name || shift.user_email || '');
      }
    });
    return [...map.entries()]
      .map(([userId, fullName]) => ({ userId, fullName }))
      .sort((a, b) => a.fullName.localeCompare(b.fullName, locale));
  }, [employees, shifts, locale]);

  const monthLabel = t(`special_days.months.${month}`);

  /**
   * The one table every output is written from.
   *
   * `cells` is what the sheet prints and `exportCells` what the files carry —
   * the same strings except where a column too narrow for a name forces the
   * printed square down to a number.
   *
   * `minFirstEm` and `minColumnEm` are the narrowest each column may get,
   * stated in the table's own type size. They are what makes a column too
   * narrow measurable at all: a fixed-layout table never widens past its
   * container on its own, it just breaks "31" over two lines or hides what
   * will not wrap, and the fit search would read either as a fit. Given a
   * minimum width the table overflows instead, and the search answers by
   * setting the type smaller until the columns are honestly wide enough.
   */
  const table = useMemo(() => {
    if (layout === 'employees') {
      const markerOf = new Map(
        orderedCompetences.map((competence, index) => [competence.id, String(index + 1)])
      );
      return {
        firstHead: t('schedule_print.employee'),
        columns: days.map((day) => ({
          key: day.dateStr,
          label: String(day.day),
          sub: day.weekdayLabel,
          muted: day.muted,
        })),
        rows: people.map((person) => {
          const cells = [];
          const exportCells = [];
          days.forEach((day) => {
            const own = (shiftsByDate.get(day.dateStr) || []).filter(
              (shift) => shift.user_id === person.userId
            );
            cells.push(
              own.map((shift) => markerOf.get(shift.competence_id) || '•').join(' ')
            );
            exportCells.push(
              own
                .map(
                  (shift) =>
                    orderedCompetences.find((item) => item.id === shift.competence_id)
                      ?.name || ''
                )
                .join(', ')
            );
          });
          return {
            key: person.userId,
            label:
              nameStyle === 'full'
                ? person.fullName
                : formatShortName(person.fullName) || person.fullName,
            sub: null,
            muted: false,
            cells,
            exportCells,
          };
        }),
        legend: orderedCompetences.map((competence, index) => ({
          key: competence.id,
          marker: String(index + 1),
          label: competence.name,
        })),
        minFirstEm: 8,
        minColumnEm: 2.2,
        firstColumnWidth: 24,
        columnWidth: 16,
      };
    }

    return {
      firstHead: t('schedule_print.date'),
      columns: orderedCompetences.map((competence) => ({
        key: competence.id,
        label: competence.name,
        sub: null,
        muted: false,
      })),
      rows: days.map((day) => {
        const cells = orderedCompetences.map((competence) =>
          (shiftsByDate.get(day.dateStr) || [])
            .filter((shift) => shift.competence_id === competence.id)
            .map(nameOf)
            .join(', ')
        );
        return {
          key: day.dateStr,
          label: `${day.day}.`,
          sub: day.weekdayLabel,
          muted: day.muted,
          cells,
          exportCells: cells,
        };
      }),
      legend: [],
      minFirstEm: 4,
      minColumnEm: 5,
      firstColumnWidth: 14,
      columnWidth: 24,
    };
  }, [layout, days, orderedCompetences, people, shiftsByDate, nameOf, nameStyle, t]);

  const sheetTitle = `${active?.name || ''} — ${monthLabel} ${year}`;

  /* The sheet sets a heading's second line under its first; a spreadsheet has
     no such thing, so the two are joined into the one string the cell holds —
     "12. Ut", "3 St". */
  const exportMatrix = useMemo(() => {
    const header = [
      table.firstHead,
      ...table.columns.map((column) =>
        column.sub ? `${column.label} ${column.sub}` : column.label
      ),
    ];
    const rows = table.rows.map((row) => [
      row.sub ? `${row.label} ${row.sub}` : row.label,
      ...row.exportCells,
    ]);
    const highlighted = new Set(
      table.rows.map((row, index) => (row.muted ? index : -1)).filter((index) => index >= 0)
    );
    return { header, rows, highlighted };
  }, [table]);

  const baseFilename = `rozvrh-${slugify(active?.name)}-${year}-${pad(month + 1)}`;

  const handleXlsx = () => {
    downloadXlsx(
      `${baseFilename}.xlsx`,
      `${monthLabel} ${year}`,
      exportMatrix.header,
      exportMatrix.rows,
      {
        highlighted: exportMatrix.highlighted,
        widths: [
          table.firstColumnWidth,
          ...table.columns.map(() => table.columnWidth),
        ],
        title: sheetTitle,
      }
    );
  };

  const handleCsv = () => {
    downloadCsv(`${baseFilename}.csv`, exportMatrix.header, exportMatrix.rows);
  };

  /* --------------------------------- fitting the sheet onto one page ------ */

  const [sheetWidthMm, sheetHeightMm] =
    orientation === 'landscape'
      ? [A4_LONG_MM - 2 * PAGE_MARGIN_MM, A4_SHORT_MM - 2 * PAGE_MARGIN_MM]
      : [A4_SHORT_MM - 2 * PAGE_MARGIN_MM, A4_LONG_MM - 2 * PAGE_MARGIN_MM];

  useLayoutEffect(() => {
    const sheet = sheetRef.current;
    const body = bodyRef.current;
    if (!sheet || !body) return;

    let low = MIN_FONT_PX;
    let high = MAX_FONT_PX;
    let best = MIN_FONT_PX;
    for (let step = 0; step < FIT_STEPS; step += 1) {
      const mid = (low + high) / 2;
      sheet.style.setProperty('--sprint-font', `${mid}px`);
      // Reading the scrolled size flushes the layout the line above dirtied.
      const fits =
        body.scrollHeight <= body.clientHeight + 1 &&
        body.scrollWidth <= body.clientWidth + 1;
      if (fits) {
        best = mid;
        low = mid;
      } else {
        high = mid;
      }
    }
    sheet.style.setProperty('--sprint-font', `${best}px`);
  }, [table, sheetWidthMm, sheetHeightMm, loading]);

  /* The sheet is laid out at its true printed size and only shown smaller, so
     every measurement above is taken on the paper's own geometry. */
  useLayoutEffect(() => {
    const stage = stageRef.current;
    const sheet = sheetRef.current;
    if (!stage || !sheet) return undefined;

    const measure = () => {
      const natural = sheet.offsetWidth;
      const scale = natural ? Math.min(1, stage.clientWidth / natural) : 1;
      setPreview({ scale, height: sheet.offsetHeight * scale });
    };

    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(stage);
    return () => observer.disconnect();
  }, [sheetWidthMm, sheetHeightMm]);

  /* ---------------------------------------------------------------- render */

  if (workplacesLoading) {
    return (
      <div className="sprint">
        <p>{t('schedule_print.loading')}</p>
      </div>
    );
  }

  if (forbidden || workplaces.length === 0) {
    return (
      <div className="sprint">
        <h1 className="sprint-title">{t('schedule_print.title')}</h1>
        <div className="sprint-banner">
          {forbidden ? t('departments.forbidden') : t('departments.no_ambulances')}
        </div>
      </div>
    );
  }

  return (
    <div className="sprint">
      <style>{`@page { size: A4 ${orientation}; margin: ${PAGE_MARGIN_MM}mm; }`}</style>

      <h1 className="sprint-title">{t('schedule_print.title')}</h1>

      {error && <div className="sprint-banner">{error}</div>}

      <div className="sprint-bar">
        <select
          className="sprint-select"
          aria-label={t('schedule_print.month')}
          value={month}
          onChange={(event) => setMonth(Number(event.target.value))}
        >
          {MONTHS.map((index) => (
            <option key={index} value={index}>
              {t(`special_days.months.${index}`)}
            </option>
          ))}
        </select>

        <select
          className="sprint-select"
          aria-label={t('schedule_print.year')}
          value={year}
          onChange={(event) => setYear(Number(event.target.value))}
        >
          {years.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>

        <div className="sprint-seg" role="group" aria-label={t('schedule_print.layout')}>
          <button
            type="button"
            className={layout === 'competences' ? 'is-active' : ''}
            onClick={() => setLayout('competences')}
          >
            {t('schedule_print.layout_competences')}
          </button>
          <button
            type="button"
            className={layout === 'employees' ? 'is-active' : ''}
            onClick={() => setLayout('employees')}
          >
            {t('schedule_print.layout_employees')}
          </button>
        </div>

        <div className="sprint-seg" role="group" aria-label={t('schedule_print.orientation')}>
          <button
            type="button"
            className={orientation === 'portrait' ? 'is-active' : ''}
            onClick={() => setOrientation('portrait')}
          >
            {t('schedule_print.portrait')}
          </button>
          <button
            type="button"
            className={orientation === 'landscape' ? 'is-active' : ''}
            onClick={() => setOrientation('landscape')}
          >
            {t('schedule_print.landscape')}
          </button>
        </div>

        <div className="sprint-seg" role="group" aria-label={t('schedule_print.names')}>
          <button
            type="button"
            className={nameStyle === 'short' ? 'is-active' : ''}
            onClick={() => setNameStyle('short')}
          >
            {t('schedule_print.names_short')}
          </button>
          <button
            type="button"
            className={nameStyle === 'full' ? 'is-active' : ''}
            onClick={() => setNameStyle('full')}
          >
            {t('schedule_print.names_full')}
          </button>
        </div>

        <div className="sprint-actions">
          <button
            type="button"
            className="sprint-btn sprint-btn-primary"
            disabled={loading}
            onClick={() => window.print()}
          >
            {t('schedule_print.print')}
          </button>
          <button
            type="button"
            className="sprint-btn"
            disabled={loading}
            onClick={handleXlsx}
          >
            {t('schedule_print.xlsx')}
          </button>
          <button
            type="button"
            className="sprint-btn"
            disabled={loading}
            onClick={handleCsv}
          >
            {t('schedule_print.csv')}
          </button>
        </div>
      </div>

      <div className="sprint-stage" ref={stageRef} style={{ height: preview.height }}>
        <div
          className={`sprint-sheet ${loading ? 'is-loading' : ''}`}
          ref={sheetRef}
          style={{
            width: `${sheetWidthMm}mm`,
            height: `${sheetHeightMm}mm`,
            transform: `scale(${preview.scale})`,
          }}
        >
          <div className="sprint-sheet-head">
            <h2>{active?.name}</h2>
            <span>{`${monthLabel} ${year}`}</span>
          </div>

          <div className="sprint-sheet-body" ref={bodyRef}>
            <div className="sprint-table-wrap">
              <table
                className={`sprint-table is-${layout}`}
                style={{
                  minWidth: `calc(${table.minFirstEm}em + ${table.columns.length} * ${table.minColumnEm}em)`,
                }}
              >
                <thead>
                  <tr>
                    <th className="sprint-first">{table.firstHead}</th>
                    {table.columns.map((column) => (
                      <th key={column.key} className={column.muted ? 'is-muted' : ''}>
                        {column.label}
                        {column.sub && <em>{column.sub}</em>}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {table.rows.map((row) => (
                    <tr key={row.key} className={row.muted ? 'is-muted' : ''}>
                      <th className="sprint-first">
                        {row.label}
                        {row.sub && <em>{row.sub}</em>}
                      </th>
                      {row.cells.map((cell, index) => (
                        <td
                          key={table.columns[index].key}
                          className={table.columns[index].muted ? 'is-muted' : ''}
                        >
                          {cell}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {table.legend.length > 0 && (
              <ul className="sprint-legend">
                {table.legend.map((item) => (
                  <li key={item.key}>
                    <b>{item.marker}</b>
                    {item.label}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default SchedulePrintView;
