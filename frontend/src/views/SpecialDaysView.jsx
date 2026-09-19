import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  clearSpecialDay,
  copySpecialDays,
  fetchSpecialDays,
  setSpecialDay,
} from '../services/specialDayService';
import { useWorkplace } from '../hooks/workplaceContext';
import './SpecialDaysView.css';

/** Months of the year, zero-based, for the calendar grid. */
const MONTHS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];

/** How far either side of this year the year picker reaches. */
const YEAR_SPAN = 3;

/** `YYYY-MM-DD` for a local date, without going through UTC — `toISOString`
 *  would shift a day either side of midnight depending on the timezone. */
const isoDay = (year, monthIndex, day) =>
  `${year}-${String(monthIndex + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;

/** Monday-first weekday index of a date, matching `workload.days.*`. */
const isoWeekday = (date) => (date.getDay() + 6) % 7;

const daysInMonth = (year, monthIndex) =>
  new Date(year, monthIndex + 1, 0).getDate();

/**
 * The special-day calendar of one workplace (scheduler screen).
 *
 * "Special day" here means one thing: a day of rest — a `deň pracovného
 * pokoja`. The list of them is not typed in and not maintained per year.
 * The backend asks the Slovak public-holiday library, which knows the
 * moving feasts and knows the 2024 split between the days that rest and the
 * state holidays that are only commemorated (8 May, 1 and 15 September,
 * 28 October, 17 November are worked). That list is the same for every
 * workplace and cannot be edited here.
 *
 * What a workplace owns are its exceptions, and the screen is built around
 * that distinction rather than hiding it. Every day carries where its
 * verdict came from: inherited from the library, added here, or taken away
 * here. A day the workplace decided itself is marked, and one click returns
 * it to the library — so there is always a way back to "whatever the law
 * says", which a plain set of checkboxes would not give.
 *
 * The year is one grid of twelve months, because that is the shape of the
 * question: a planner comes here to look over a year and mark the handful of
 * dates their clinic treats differently, not to page through months.
 *
 * What the marking is *for* lives on the competence screen: a date marked as
 * a day of rest is staffed from the competence's special-day column,
 * whatever weekday it falls on.
 */
const SpecialDaysView = () => {
  const { t } = useTranslation();

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
  const [saving, setSaving] = useState(null); // the ISO day being written
  const [toast, setToast] = useState(null);
  const [copySource, setCopySource] = useState('');

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

  // Switching workplace mid-copy would copy onto the wrong one.
  useEffect(() => {
    setCopySource('');
  }, [selectedId]);

  const byDay = useMemo(
    () => new Map(entries.map((entry) => [entry.day, entry])),
    [entries]
  );

  const years = useMemo(() => {
    const current = new Date().getFullYear();
    return Array.from(
      { length: YEAR_SPAN * 2 + 1 },
      (_unused, offset) => current - YEAR_SPAN + offset
    );
  }, []);

  /** Everything the workplace itself decided, which is the list worth
   *  reading back: the library needs no review, the exceptions do. */
  const ownDecisions = useMemo(
    () => entries.filter((entry) => entry.is_overridden),
    [entries]
  );

  const restDayCount = useMemo(
    () => entries.filter((entry) => entry.is_rest_day).length,
    [entries]
  );

  const write = async (action, day) => {
    if (saving) return;
    setSaving(day);
    try {
      setEntries((await action()).entries);
    } catch {
      notify(t('special_days.save_error'));
      load();
    } finally {
      setSaving(null);
    }
  };

  /** Clicking a day flips what the workplace makes of it. */
  const toggleDay = (day) => {
    const entry = byDay.get(day);
    const nextRest = !(entry?.is_rest_day ?? false);
    return write(() => setSpecialDay(selectedId, day, nextRest), day);
  };

  /** Give one date back to the library, whichever way it was overridden. */
  const resetDay = (day) =>
    write(() => clearSpecialDay(selectedId, day), day);

  const handleCopy = async () => {
    const sourceId = Number(copySource);
    if (!sourceId || saving) return;
    setSaving('copy');
    try {
      setEntries((await copySpecialDays(selectedId, sourceId, year)).entries);
      setCopySource('');
      notify(t('special_days.copied'));
    } catch {
      notify(t('special_days.save_error'));
      load();
    } finally {
      setSaving(null);
    }
  };

  if (workplacesLoading) {
    return <div className="sdays"><p>{t('departments.loading')}</p></div>;
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

  /** One clickable date in a month card. */
  const renderDay = (monthIndex, dayNumber) => {
    const day = isoDay(year, monthIndex, dayNumber);
    const entry = byDay.get(day);
    const date = new Date(year, monthIndex, dayNumber);
    const weekday = isoWeekday(date);
    const isRest = entry?.is_rest_day ?? false;
    const label = entry?.name
      ? `${entry.name}${entry.is_overridden ? ` — ${t('special_days.own_decision')}` : ''}`
      : t(isRest ? 'special_days.is_rest_hint' : 'special_days.is_worked_hint');

    return (
      <button
        type="button"
        key={day}
        className={[
          'sdays-day',
          weekday === 6 ? 'is-sunday' : '',
          weekday === 5 ? 'is-saturday' : '',
          isRest ? 'is-rest' : '',
          entry?.is_overridden ? 'is-own' : '',
          entry && !entry.is_rest_day && entry.in_library ? 'is-state-workday' : '',
        ]
          .join(' ')
          .trim()}
        disabled={saving === day}
        title={label}
        aria-pressed={isRest}
        onClick={() => toggleDay(day)}
      >
        <b>{dayNumber}</b>
      </button>
    );
  };

  return (
    <div className="sdays">
      <header className="sdays-head">
        <h1 className="sdays-title">{t('special_days.title')}</h1>
        <p className="sdays-lede">{t('special_days.lede')}</p>
      </header>

      {(workplacesError || loadError) && (
        <div className="sdays-banner">{t('special_days.load_error')}</div>
      )}

      <div className="sdays-bar">
        <div className="sdays-years" role="group" aria-label={t('special_days.year')}>
          {years.map((option) => (
            <button
              type="button"
              key={option}
              className={`sdays-year ${option === year ? 'is-current' : ''}`}
              aria-pressed={option === year}
              onClick={() => setYear(option)}
            >
              {option}
            </button>
          ))}
        </div>

        <span className="sdays-count">
          {t('special_days.rest_day_count', { count: restDayCount })}
        </span>

        {otherWorkplaces.length > 0 && (
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
              disabled={!copySource || saving != null}
              title={t('special_days.copy_hint')}
              onClick={handleCopy}
            >
              {t('special_days.copy')}
            </button>
          </div>
        )}
      </div>

      <p className="sdays-workplace">{selected?.name}</p>

      {/* The key is permanent here rather than on hover: a day's colour is
          the whole content of this screen, and half of it -- inherited
          against decided here -- is a distinction nobody would guess. */}
      <div className="sdays-legend" role="note">
        <span className="sdays-legend-item">
          <i className="sdays-swatch is-rest" aria-hidden="true" />
          {t('special_days.legend_rest')}
        </span>
        <span className="sdays-legend-item">
          <i className="sdays-swatch is-rest is-own" aria-hidden="true" />
          {t('special_days.legend_own')}
        </span>
        <span className="sdays-legend-item">
          <i className="sdays-swatch is-state-workday" aria-hidden="true" />
          {t('special_days.legend_state_workday')}
        </span>
        <span className="sdays-legend-item">
          <i className="sdays-swatch" aria-hidden="true" />
          {t('special_days.legend_plain')}
        </span>
      </div>

      {loading && <p className="sdays-note">{t('departments.loading')}</p>}

      <div className="sdays-year-grid">
        {MONTHS.map((monthIndex) => {
          const first = isoWeekday(new Date(year, monthIndex, 1));
          return (
            <section className="sdays-month" key={monthIndex}>
              <h2>{t(`special_days.months.${monthIndex}`)}</h2>
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
        <h2>{t('special_days.own_title')}</h2>
        {ownDecisions.length === 0 ? (
          <p className="sdays-note">{t('special_days.own_empty')}</p>
        ) : (
          <ul className="sdays-own-list">
            {ownDecisions.map((entry) => (
              <li key={entry.day}>
                <span className="sdays-own-day">{entry.day}</span>
                <span className="sdays-own-what">
                  {entry.is_rest_day
                    ? t('special_days.own_added')
                    : t('special_days.own_removed')}
                </span>
                {entry.name && <em className="sdays-own-name">{entry.name}</em>}
                <button
                  type="button"
                  className="sdays-btn"
                  disabled={saving === entry.day}
                  title={t('special_days.reset_hint')}
                  onClick={() => resetDay(entry.day)}
                >
                  {t('special_days.reset')}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {toast && (
        <div className="sdays-toast" role="status">
          {toast}
        </div>
      )}
    </div>
  );
};

export default SpecialDaysView;
