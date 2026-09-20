import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  clearSpecialDay,
  copySpecialDays,
  fetchSpecialDays,
  setSpecialDay,
} from '../services/specialDayService';
import { useWorkplace } from '../hooks/workplaceContext';
import { useRoles } from '../hooks/useRoles';
import ConfirmDialog from '../components/ConfirmDialog';
import './SpecialDaysView.css';

/** Months of the year, zero-based, for the calendar grid. */
const MONTHS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];

/** How far either side of this year the year stepper reaches. */
const YEAR_SPAN = 3;

/** `YYYY-MM-DD` for a local date, without going through UTC — `toISOString`
 *  would shift a day either side of midnight depending on the timezone. */
const isoDay = (year, monthIndex, day) =>
  `${year}-${String(monthIndex + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;

/** Monday-first weekday index of a date, matching `workload.days.*`. */
const isoWeekday = (date) => (date.getDay() + 6) % 7;

const daysInMonth = (year, monthIndex) =>
  new Date(year, monthIndex + 1, 0).getDate();

/** `1. 9. 2026` — numeric, because the month names are nominative and would
 *  read wrong after a day number in Slovak. */
const readableDay = (day) => {
  const [year, month, date] = day.split('-');
  return `${Number(date)}. ${Number(month)}. ${year}`;
};

/**
 * The special-day calendar of one workplace (scheduler screen).
 *
 * "Special day" here means one thing: a day of rest — a `deň pracovného
 * pokoja`. The list of them is not typed in and not maintained per year.
 * The backend asks the Slovak public-holiday library, which knows the moving
 * feasts and knows the 2024 split between the days that rest and the state
 * holidays that are only commemorated. That list is the same for every
 * workplace and cannot be edited here.
 *
 * What a workplace owns are its exceptions, and the screen is built around
 * that distinction rather than hiding it. A day the workplace decided itself
 * carries a mark, and the list under the year names every one of them with a
 * way back to "whatever the law says" — which a plain set of checkboxes
 * would not give.
 *
 * The year is one grid of twelve months, because that is the shape of the
 * question: a planner comes here to look over a year and mark the handful of
 * dates their clinic treats differently, not to page through months. None of
 * this is spelled out on the screen: the colour key is the only prose, and
 * the rest is the calendar itself.
 *
 * Who may change the year is not who may see it. Which dates a clinic rests
 * on follows from the law and from how the hospital runs, so it is the
 * administrator's to set; a scheduler opens the same screen to read it,
 * because it decides which column of a competence staffs a date. For them
 * the grid is a picture and nothing else: no clicks, no controls, rather
 * than buttons that would answer with a refusal.
 *
 * For the administrator there is no save button, so a click has to be the
 * save: the square flips at once and the write goes out behind it. Marking a
 * handful of dates is a run of quick clicks, and none of them may be dropped
 * because the one before is still in the air.
 *
 * What the marking is *for* lives on the competence screen: a date marked as
 * a day of rest is staffed from the competence's special-day column,
 * whatever weekday it falls on.
 */
const SpecialDaysView = () => {
  const { t } = useTranslation();
  const { hasAdmin: canEdit } = useRoles();

  const {
    workplaces,
    activeId: selectedId,
    active: selected,
    loading: workplacesLoading,
    error: workplacesError,
    forbidden,
  } = useWorkplace();

  const [year, setYear] = useState(() => new Date().getFullYear());
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  /** Days clicked but not yet answered for, `day -> the verdict sent`. */
  const [pending, setPending] = useState(() => new Map());
  /** Writes in the air. Only the year-wide actions have to wait for zero. */
  const [busy, setBusy] = useState(0);
  const [toast, setToast] = useState(null);
  const [copySource, setCopySource] = useState('');
  const [copyTarget, setCopyTarget] = useState(null);

  /** Writes go out one at a time. Every answer is the whole year, so two in
   *  flight would let the earlier one land last and undo the later click. */
  const queue = useRef(Promise.resolve());

  const notify = (message) => {
    setToast(message);
    setTimeout(() => setToast(null), 2400);
  };

  const load = useCallback(async () => {
    if (selectedId == null) return;
    setLoading(true);
    setLoadError(false);
    try {
      const data = await fetchSpecialDays(selectedId, year);
      setEntries(data.entries);
    } catch {
      setEntries([]);
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, [selectedId, year]);

  useEffect(() => {
    load();
  }, [load]);

  // A pending click belongs to the year and workplace it was made in.
  useEffect(() => {
    setPending(new Map());
    setCopySource('');
  }, [selectedId, year]);

  const enqueue = (job) => {
    setBusy((count) => count + 1);
    queue.current = queue.current
      .then(job)
      .catch(() => {})
      .finally(() => setBusy((count) => count - 1));
    return queue.current;
  };

  /** Let go of a clicked day once its own write answered — unless a newer
   *  click has claimed it since, whose own write is still on its way. */
  const release = (day, sent) =>
    setPending((prev) => {
      if (prev.get(day) !== sent) return prev;
      const next = new Map(prev);
      next.delete(day);
      return next;
    });

  /** The year as the screen shows it: what the server last said, with the
   *  clicks that have not been answered for yet laid over the top. */
  const byDay = useMemo(() => {
    const map = new Map(entries.map((entry) => [entry.day, entry]));
    pending.forEach((isRest, day) => {
      const base = map.get(day) ?? {
        day,
        name: null,
        in_library: false,
        library_rest_day: false,
      };
      map.set(day, {
        ...base,
        is_rest_day: isRest,
        is_overridden: isRest !== base.library_rest_day,
      });
    });
    return map;
  }, [entries, pending]);

  const shown = useMemo(
    () => [...byDay.values()].sort((a, b) => a.day.localeCompare(b.day)),
    [byDay]
  );

  /** Today, so the year in view can point at where we actually are. */
  const today = useMemo(() => {
    const now = new Date();
    return isoDay(now.getFullYear(), now.getMonth(), now.getDate());
  }, []);

  const firstYear = new Date().getFullYear() - YEAR_SPAN;
  const lastYear = firstYear + YEAR_SPAN * 2;

  /** Everything the workplace itself decided, which is the list worth
   *  reading back: the library needs no review, the exceptions do. */
  const ownDecisions = useMemo(
    () => shown.filter((entry) => entry.is_overridden),
    [shown]
  );

  /** Days of rest per month, so every card carries its own tally — the
   *  number that is otherwise counted off the grid by hand. */
  const restByMonth = useMemo(() => {
    const counts = Array(12).fill(0);
    shown.forEach((entry) => {
      if (!entry.is_rest_day) return;
      const monthIndex = Number(entry.day.slice(5, 7)) - 1;
      if (monthIndex >= 0 && monthIndex < 12) counts[monthIndex] += 1;
    });
    return counts;
  }, [shown]);

  const restDayCount = useMemo(
    () => restByMonth.reduce((sum, count) => sum + count, 0),
    [restByMonth]
  );

  /** Send one date's verdict, having already shown it on the grid. */
  const write = (day, verdict, action) => {
    setPending((prev) => new Map(prev).set(day, verdict));
    return enqueue(async () => {
      try {
        setEntries((await action()).entries);
        notify(t('special_days.saved'));
      } catch {
        notify(t('special_days.save_error'));
        await load();
      } finally {
        release(day, verdict);
      }
    });
  };

  /** Clicking a day flips what the workplace makes of it. */
  const toggleDay = (day) => {
    const nextRest = !(byDay.get(day)?.is_rest_day ?? false);
    return write(day, nextRest, () => setSpecialDay(selectedId, day, nextRest));
  };

  /** Give one date back to the library, whichever way it was overridden. */
  const resetDay = (day) => {
    const back = byDay.get(day)?.library_rest_day ?? false;
    return write(day, back, () => clearSpecialDay(selectedId, day));
  };

  /** Take another workplace's year. This replaces the exceptions already
   *  here, so it asks first — including when the source has none to give,
   *  which is the case that silently empties the year. */
  const handleCopy = async () => {
    const source = copyTarget;
    setCopyTarget(null);
    if (!source) return;
    setBusy((count) => count + 1);
    try {
      const data = await copySpecialDays(selectedId, source.id, year);
      setPending(new Map());
      setEntries(data.entries);
      setCopySource('');
      notify(t('special_days.copied'));
    } catch {
      notify(t('special_days.save_error'));
      load();
    } finally {
      setBusy((count) => count - 1);
    }
  };

  if (workplacesLoading) {
    return (
      <div className="sdays">
        <p className="sdays-note">{t('departments.loading')}</p>
      </div>
    );
  }

  if (forbidden || workplaces.length === 0) {
    return (
      <div className="sdays">
        <h1 className="sdays-title">{t('special_days.title')}</h1>
        <div className="sdays-banner">
          {forbidden ? t('departments.forbidden') : t('departments.no_ambulances')}
        </div>
      </div>
    );
  }

  const otherWorkplaces = workplaces.filter((item) => item.id !== selectedId);

  /** One date in a month card — a button for whoever may change it. */
  const renderDay = (monthIndex, dayNumber) => {
    const day = isoDay(year, monthIndex, dayNumber);
    const entry = byDay.get(day);
    const weekday = isoWeekday(new Date(year, monthIndex, dayNumber));
    const isRest = entry?.is_rest_day ?? false;
    const month = t(`special_days.months.${monthIndex}`);
    const className = [
      'sdays-day',
      canEdit ? '' : 'is-static',
      weekday >= 5 ? 'is-weekend' : '',
      isRest ? 'is-rest' : '',
      entry?.is_overridden ? 'is-own' : '',
      entry && !entry.is_rest_day && entry.in_library ? 'is-state-workday' : '',
      day === today ? 'is-today' : '',
    ]
      .join(' ')
      .trim();

    if (!canEdit) {
      return (
        <span key={day} className={className} title={entry?.name || undefined}>
          <span>{dayNumber}</span>
        </span>
      );
    }

    return (
      <button
        type="button"
        key={day}
        className={className}
        title={entry?.name || undefined}
        aria-label={`${dayNumber}. ${month} ${year}${entry?.name ? `, ${entry.name}` : ''}`}
        aria-pressed={isRest}
        onClick={() => toggleDay(day)}
      >
        <span>{dayNumber}</span>
      </button>
    );
  };

  return (
    <div className="sdays">
      <header className="sdays-head">
        <div className="sdays-head-name">
          <h1 className="sdays-title">{t('special_days.title')}</h1>
          {selected?.name && <span className="sdays-workplace">{selected.name}</span>}
        </div>

        <div className="sdays-years">
          <button
            type="button"
            className="sdays-step"
            disabled={year <= firstYear}
            aria-label={t('special_days.previous_year')}
            onClick={() => setYear((current) => Math.max(firstYear, current - 1))}
          >
            ‹
          </button>
          <span className="sdays-year">{year}</span>
          <button
            type="button"
            className="sdays-step"
            disabled={year >= lastYear}
            aria-label={t('special_days.next_year')}
            onClick={() => setYear((current) => Math.min(lastYear, current + 1))}
          >
            ›
          </button>
        </div>
      </header>

      {(workplacesError || loadError) && (
        <div className="sdays-banner">{t('special_days.load_error')}</div>
      )}

      {/* The key is permanent here rather than on hover: a day's colour is
          the whole content of this screen, and half of it -- inherited
          against decided here -- is a distinction nobody would guess. */}
      <div className="sdays-legend" role="note">
        <span className="sdays-chip is-count">
          {t('special_days.rest_day_count', { count: restDayCount })}
        </span>
        <span className="sdays-chip">
          <i className="sdays-swatch is-rest" aria-hidden="true" />
          {t('special_days.legend_rest')}
        </span>
        <span className="sdays-chip">
          <i className="sdays-swatch is-rest is-own" aria-hidden="true" />
          {t('special_days.legend_own')}
        </span>
        <span className="sdays-chip">
          <i className="sdays-swatch is-state-workday" aria-hidden="true" />
          {t('special_days.legend_state_workday')}
        </span>
      </div>

      {/* Loading dims the year instead of replacing it, so the grid keeps its
          height and nothing jumps under the cursor when the year lands. */}
      <div
        className={`sdays-year-grid ${loading ? 'is-loading' : ''}`}
        aria-busy={loading}
      >
        {MONTHS.map((monthIndex) => {
          const first = isoWeekday(new Date(year, monthIndex, 1));
          return (
            <section className="sdays-month" key={monthIndex}>
              <header className="sdays-month-head">
                <h2>{t(`special_days.months.${monthIndex}`)}</h2>
                {restByMonth[monthIndex] > 0 && (
                  <span className="sdays-month-count">{restByMonth[monthIndex]}</span>
                )}
              </header>
              <div className="sdays-month-grid">
                {[0, 1, 2, 3, 4, 5, 6].map((weekday) => (
                  <span
                    key={`head-${weekday}`}
                    className={`sdays-weekday ${weekday >= 5 ? 'is-weekend' : ''}`}
                  >
                    {t(`workload.days.${weekday}`)}
                  </span>
                ))}
                {/* Blanks push the first of the month under its weekday. */}
                {Array.from({ length: first }, (_unused, index) => (
                  <span className="sdays-blank" key={`blank-${index}`} />
                ))}
                {Array.from({ length: daysInMonth(year, monthIndex) }, (_unused, index) =>
                  renderDay(monthIndex, index + 1)
                )}
              </div>
            </section>
          );
        })}
      </div>

      <section className="sdays-own">
        {/* Taking another workplace's year belongs to the exceptions, not to
            the calendar: it is the one control here that replaces them. */}
        <header className="sdays-own-head">
          <h2>{t('special_days.own_title')}</h2>
          {canEdit && otherWorkplaces.length > 0 && (
            <div className="sdays-copy">
              <label htmlFor="sdays-copy-source">{t('special_days.copy_from')}</label>
              <select
                id="sdays-copy-source"
                className="sdays-select"
                value={copySource}
                onChange={(e) => setCopySource(e.target.value)}
              >
                <option value="">{t('special_days.copy_pick')}</option>
                {otherWorkplaces.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="sdays-btn"
                disabled={!copySource || busy > 0}
                onClick={() =>
                  setCopyTarget(
                    otherWorkplaces.find(
                      (item) => String(item.id) === copySource
                    ) ?? null
                  )
                }
              >
                {t('special_days.copy')}
              </button>
            </div>
          )}
        </header>

        {ownDecisions.length === 0 ? (
          <p className="sdays-note">{t('special_days.own_empty')}</p>
        ) : (
          <ul className="sdays-own-list">
            {ownDecisions.map((entry) => (
              <li key={entry.day}>
                <span className="sdays-own-day">{readableDay(entry.day)}</span>
                <span
                  className={`sdays-own-what ${
                    entry.is_rest_day ? 'is-added' : 'is-removed'
                  }`}
                >
                  {entry.is_rest_day
                    ? t('special_days.own_added')
                    : t('special_days.own_removed')}
                </span>
                {entry.name && <em className="sdays-own-name">{entry.name}</em>}
                {canEdit && (
                  <button
                    type="button"
                    className="sdays-btn"
                    onClick={() => resetDay(entry.day)}
                  >
                    {t('special_days.reset')}
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <ConfirmDialog
        open={copyTarget != null}
        message={t('special_days.copy_confirm', {
          name: copyTarget?.name,
          year,
        })}
        confirmLabel={t('special_days.copy')}
        cancelLabel={t('departments.cancel')}
        onConfirm={handleCopy}
        onCancel={() => setCopyTarget(null)}
      />

      {toast && (
        <div className="sdays-toast" role="status">
          {toast}
        </div>
      )}
    </div>
  );
};

export default SpecialDaysView;
