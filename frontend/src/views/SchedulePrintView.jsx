import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  fetchCompetences,
  fetchEmployeeCompetenceTable,
} from '../services/competenceService';
import { fetchAmbulanceSchedule } from '../services/scheduleService';
import { fetchSpecialDays } from '../services/specialDayService';
import { useWorkplace } from '../hooks/workplaceContext';
import { formatNameStyle } from '../utils/formatEmployeeName';
import { downloadCsv, downloadXlsx } from '../utils/tableExport';
import { downloadSchedulePdf } from '../utils/schedulePdf';
import './SchedulePrintView.css';

const pad = (n) => String(n).padStart(2, '0');
const isoDate = (year, month, day) => `${year}-${pad(month + 1)}-${pad(day)}`;
const isoWeekday = (dateObj) => (dateObj.getDay() + 6) % 7;

const MONTHS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];

/* How a name may be written on the sheet, in the order the toolbar offers it:
   the initial and the surname, the whole name without its academic titles,
   and the name exactly as it is on record. Shorter is narrower, so the fit
   search will usually find a larger type size for the first of them. */
const NAME_STYLES = ['short', 'full', 'titles'];
const YEAR_SPAN = 2;

/* A4 in millimetres, and the margin the page rule reserves on every side. The
   sheet below is built at exactly what is left, so what is on screen is the
   printable area itself rather than a likeness of it. */
const PAGE_MARGIN_MM = 8;
const A4_SHORT_MM = 210;
const A4_LONG_MM = 297;

/* How many sheets the month may be spread over. One is the default and the
   usual answer -- a rota split across pages is a rota nobody trusts -- but a
   roster of forty people on a thirty-one day month has to choose between a
   second sheet and type nobody can read, and that is the reader's choice to
   make, not ours. */
const PAGE_OPTIONS = [1, 2, 3, 4, 5, 6];

/* Pixels left between two sheets in the preview, so a second page reads as a
   second sheet of paper rather than as more of the first. */
const PAGE_GAP_PX = 16;

/* The type size is not chosen but found: the table is laid out, measured
   against the page, and the size halved in on until the largest one that
   still fits the page budget is known. Eight steps land within a twentieth of
   a pixel of it, which is finer than any printer resolves. */
const MIN_FONT_PX = 3;
const MAX_FONT_PX = 13;
const FIT_STEPS = 8;

/* Pixels of the page the fit search refuses to use. Browsers round a table's
   rows and borders to whole device pixels, and a size that fills the sheet to
   the last of them loses the bottom row's rule -- or the row -- to that
   rounding. Two pixels of air cost nothing and the sheet always closes. */
const FIT_SLACK_PX = 2;

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
 * It wants to be one sheet -- a rota split across pages is a rota nobody
 * trusts -- so one sheet is what it is asked for by default, and the type size
 * is found rather than chosen to keep that promise. A month too big to keep it
 * legibly can be given more sheets in the toolbar, and the same search then
 * spends them on larger type and cuts the table where the pages end.
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
  const [pageBudget, setPageBudget] = useState(1);

  const [shifts, setShifts] = useState([]);
  const [competences, setCompetences] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [restDays, setRestDays] = useState(() => new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [buildingPdf, setBuildingPdf] = useState(false);

  const sheetRef = useRef(null);
  const bodyRef = useRef(null);
  const tableRef = useRef(null);
  const legendRef = useRef(null);
  const stageRef = useRef(null);
  const [preview, setPreview] = useState({ scale: 1, height: 0, pageHeight: 0 });

  /* What the fit search settled on: the type size, and the rows each sheet
     carries. Until it has run once the whole month sits on one page, which is
     also what a month that fits ends up with. */
  const [fit, setFit] = useState({ fontPx: MIN_FONT_PX, pages: [] });

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
      return formatNameStyle(full, nameStyle);
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
            label: formatNameStyle(person.fullName, nameStyle),
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
        /* Mirrors .sprint-table.is-employees .sprint-first in the stylesheet:
           the file and the screen have to give the names the same share. */
        firstColumnShare: 0.16,
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
      /* Mirrors .sprint-table.is-competences .sprint-first. */
      firstColumnShare: 0.13,
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

  const handlePdf = async () => {
    if (buildingPdf) return;
    setBuildingPdf(true);
    try {
      await downloadSchedulePdf(
        `${baseFilename}.pdf`,
        {
          title: active?.name || '',
          period: `${monthLabel} ${year}`,
          firstHead: table.firstHead,
          columns: table.columns,
          rows: table.rows,
          legend: table.legend,
          firstColumnShare: table.firstColumnShare,
        },
        orientation,
        pageBudget
      );
    } catch {
      setError(t('schedule_print.pdf_error'));
    } finally {
      setBuildingPdf(false);
    }
  };

  /* --------------------------------- fitting the sheet onto one page ------ */

  const [sheetWidthMm, sheetHeightMm] =
    orientation === 'landscape'
      ? [A4_LONG_MM - 2 * PAGE_MARGIN_MM, A4_SHORT_MM - 2 * PAGE_MARGIN_MM]
      : [A4_SHORT_MM - 2 * PAGE_MARGIN_MM, A4_LONG_MM - 2 * PAGE_MARGIN_MM];

  useLayoutEffect(() => {
    const sheet = sheetRef.current;
    const body = bodyRef.current;
    const tableEl = tableRef.current;
    if (!sheet || !body || !tableEl) return;

    /* One measurement of the whole month at one type size: how tall each row
       stands, and how much of the page is left for rows once the repeated
       heading and the legend have taken theirs.

       The measuring sheet is never stretched, so a row reports the height its
       own content needs rather than the share of the page it was handed --
       which is the only height a split can be worked out from. */
    const measure = (fontPx) => {
      sheet.style.setProperty('--sprint-font', `${fontPx}px`);
      // Reading the geometry flushes the layout the line above dirtied.
      const tableBottom = tableEl.getBoundingClientRect().bottom;
      const legendBlock = legendRef.current
        ? legendRef.current.getBoundingClientRect().bottom - tableBottom
        : 0;
      const headHeight = tableEl.tHead?.getBoundingClientRect().height ?? 0;
      const rowHeights = [...(tableEl.tBodies[0]?.rows ?? [])].map(
        (row) => row.getBoundingClientRect().height
      );
      return {
        rowHeights,
        headHeight,
        /* Every sheet repeats the heading row and carries the legend, so the
           room a page has for rows is the same on all of them. */
        rowSpace: body.clientHeight - FIT_SLACK_PX - legendBlock - headHeight,
        widthFits: tableEl.offsetWidth <= body.clientWidth,
      };
    };

    /* The rows dealt out page by page, each page taking rows until the next
       one would not close on it. A row taller than a whole page still has to
       go somewhere, so it takes a page of its own -- which pushes the count
       over the budget and hands the search the smaller size it needs. */
    const paginate = ({ rowHeights, rowSpace }) => {
      const pages = [[]];
      let used = 0;
      rowHeights.forEach((height, index) => {
        if (used > 0 && used + height > rowSpace) {
          pages.push([]);
          used = 0;
        }
        pages[pages.length - 1].push(index);
        used += height;
      });
      return pages;
    };

    let low = MIN_FONT_PX;
    let high = MAX_FONT_PX;
    let best = null;
    let bestSize = MIN_FONT_PX;
    for (let step = 0; step < FIT_STEPS; step += 1) {
      const mid = (low + high) / 2;
      const measured = measure(mid);
      const pages = measured.rowSpace > 0 ? paginate(measured) : null;
      if (pages && pages.length <= pageBudget && measured.widthFits) {
        best = pages;
        bestSize = mid;
        low = mid;
      } else {
        high = mid;
      }
    }

    if (!best) best = paginate(measure(MIN_FONT_PX));

    setFit({
      fontPx: bestSize,
      pages: best.map((indexes) => indexes.map((index) => table.rows[index])),
    });
  }, [table, sheetWidthMm, sheetHeightMm, pageBudget, loading]);

  /* Before the search has run -- the first paint, and any paint where the
     month has just changed underneath it -- the whole table is shown as one
     page, which is what a month that fits ends up as anyway. */
  const pages = fit.pages.length ? fit.pages : [table.rows];

  /* The sheet is laid out at its true printed size and only shown smaller, so
     every measurement above is taken on the paper's own geometry. */
  useLayoutEffect(() => {
    const stage = stageRef.current;
    const sheet = sheetRef.current;
    if (!stage || !sheet) return undefined;

    const measure = () => {
      const natural = sheet.offsetWidth;
      const scale = natural ? Math.min(1, stage.clientWidth / natural) : 1;
      const pageHeight = sheet.offsetHeight * scale;
      setPreview({
        scale,
        pageHeight,
        height: pageHeight * pages.length + PAGE_GAP_PX * (pages.length - 1),
      });
    };

    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(stage);
    return () => observer.disconnect();
  }, [sheetWidthMm, sheetHeightMm, pages.length]);

  /* ---------------------------------------------------------------- render */

  /**
   * One A4 sheet, carrying the rows it was given.
   *
   * The measuring sheet and the sheets on screen are the same markup on
   * purpose: a size found on a table laid out one way tells you nothing about
   * a table laid out another.
   */
  const renderSheet = (
    rows,
    { ref, className = '', key, measuring = false, loose = false, index = 0 }
  ) => (
    <div
      key={key}
      ref={ref}
      className={`sprint-sheet ${className} ${loose ? 'is-loose' : ''} ${
        loading ? 'is-loading' : ''
      }`}
      style={{
        width: `${sheetWidthMm}mm`,
        height: `${sheetHeightMm}mm`,
        ...(measuring
          ? {}
          : {
              transform: `scale(${preview.scale})`,
              '--sprint-font': `${fit.fontPx}px`,
              /* A sheet is laid out at A4 and only drawn smaller, and a
                 transform leaves the space the untransformed box claimed. So
                 the sheets are placed on the stage themselves, at the height
                 they are actually drawn. */
              top: index * (preview.pageHeight + PAGE_GAP_PX),
            }),
      }}
    >
      <div className="sprint-sheet-head">
        <h2>{active?.name}</h2>
        <span>{`${monthLabel} ${year}`}</span>
      </div>

      <div className="sprint-sheet-body" ref={measuring ? bodyRef : undefined}>
        <div className="sprint-table-wrap">
          <table
            ref={measuring ? tableRef : undefined}
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
              {rows.map((row) => (
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
          <ul className="sprint-legend" ref={measuring ? legendRef : undefined}>
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
  );

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

      <header className="sprint-head">
        <h1 className="sprint-title">{t('schedule_print.title')}</h1>

        <div className="sprint-actions">
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
          <button
            type="button"
            className="sprint-btn sprint-btn-primary"
            disabled={loading || buildingPdf}
            onClick={handlePdf}
          >
            {buildingPdf ? t('schedule_print.pdf_building') : t('schedule_print.pdf')}
          </button>
        </div>
      </header>

      {error && <div className="sprint-banner">{error}</div>}

      <div className="sprint-bar">
        <div className="sprint-group">
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
        </div>

        <span className="sprint-divider" aria-hidden="true" />

        <div className="sprint-group">
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

          <label className="sprint-field">
            {t('schedule_print.pages')}
            <select
              className="sprint-select"
              value={pageBudget}
              onChange={(event) => setPageBudget(Number(event.target.value))}
            >
              {PAGE_OPTIONS.map((count) => (
                <option key={count} value={count}>
                  {count}
                </option>
              ))}
            </select>
          </label>

          <div className="sprint-seg" role="group" aria-label={t('schedule_print.names')}>
            {NAME_STYLES.map((style) => (
              <button
                key={style}
                type="button"
                className={nameStyle === style ? 'is-active' : ''}
                onClick={() => setNameStyle(style)}
              >
                {t(`schedule_print.names_${style}`)}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="sprint-stage" ref={stageRef} style={{ height: preview.height }}>
        {/* The sheet the fit search reads: the whole month at once, at its
            natural height, off the side of the screen. It is measured rather
            than shown, because the sheets that are shown have already been
            cut to the size it found and could not tell anyone what the next
            size down would cost. */}
        {renderSheet(table.rows, {
          ref: sheetRef,
          className: 'sprint-measure is-measuring',
          key: 'measure',
          measuring: true,
        })}

        {pages.map((rows, index) =>
          renderSheet(rows, {
            key: `page-${index}`,
            /* Only a month that came out on one page is spread down it. The
               last of several holds whatever the pages before it left, and
               stretching those few rows over a whole sheet would say the
               month ends in rows three centimetres tall. */
            index,
            loose: pages.length > 1 && index === pages.length - 1,
            /* The legend explains the squares, so it belongs on every sheet
               somebody might be holding. */
          })
        )}
      </div>
    </div>
  );
};

export default SchedulePrintView;
