import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import {
  fetchUnavailabilities,
  createUnavailability,
  updateUnavailability,
  deleteUnavailability,
  stateOfRecord,
  DAY_STATE,
  REASON_BLOCKED,
  REASON_PREFERRED,
} from '../services/unavailabilityService';
import './WorkloadView.css';

/** Zero-pad a number to two digits. */
const pad = (n) => String(n).padStart(2, '0');

/** Build an ISO date string from year, month index (0-11) and day. */
const isoDate = (y, m, d) => `${y}-${pad(m + 1)}-${pad(d)}`;

/** ISO weekday index: 0=Monday ... 6=Sunday. */
const isoWeekday = (dateObj) => (dateObj.getDay() + 6) % 7;

/** Build the calendar grid of a month as a flat array of day numbers (null = filler cell). */
function buildMonthCells(year, month) {
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const offset = isoWeekday(new Date(year, month, 1));
  const cells = [];
  for (let i = 0; i < offset; i += 1) cells.push(null);
  for (let d = 1; d <= daysInMonth; d += 1) cells.push(d);
  while (cells.length % 7 !== 0) cells.push(null);
  return cells;
}

/**
 * Monthly availability view.
 *
 * Each day cycles through three states on click:
 *   1st click  -> BLOCKED    (red)   — the day does not suit me
 *   2nd click  -> PREFERRED  (green) — I would like to work this day
 *   3rd click  -> NONE       (grey)  — back to neutral
 *
 * Past months are read-only.
 */
const WorkloadView = () => {
  const { t, i18n } = useTranslation();
  const today = useMemo(() => new Date(), []);

  const [view, setView] = useState({ y: today.getFullYear(), m: today.getMonth() });
  const [entries, setEntries] = useState({}); // { 'YYYY-MM-DD': record }
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [toast, setToast] = useState(null);

  // Days with an in-flight request, to prevent double toggles.
  const pendingRef = useRef(new Set());

  const isPastMonth =
    view.y < today.getFullYear() ||
    (view.y === today.getFullYear() && view.m < today.getMonth());

  const cells = useMemo(() => buildMonthCells(view.y, view.m), [view]);

  const monthLabel = useMemo(() => {
    const formatter = new Intl.DateTimeFormat(i18n.language === 'en' ? 'en-GB' : 'sk-SK', {
      month: 'long',
      year: 'numeric',
    });
    return formatter.format(new Date(view.y, view.m, 1));
  }, [view, i18n.language]);

  const dayLabels = useMemo(
    () => [0, 1, 2, 3, 4, 5, 6].map((i) => t(`workload.days.${i}`)),
    [t]
  );

  // Counters per state, shown in the footer.
  const counts = useMemo(() => {
    let blocked = 0;
    let preferred = 0;
    Object.values(entries).forEach((rec) => {
      if (stateOfRecord(rec) === DAY_STATE.PREFERRED) preferred += 1;
      else blocked += 1;
    });
    return { blocked, preferred };
  }, [entries]);

  const notify = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2400);
  };

  const loadMonth = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const daysInMonth = new Date(view.y, view.m + 1, 0).getDate();
      const records = await fetchUnavailabilities(
        isoDate(view.y, view.m, 1),
        isoDate(view.y, view.m, daysInMonth)
      );
      const byDate = {};
      records.forEach((r) => {
        byDate[r.date_absent] = r;
      });
      setEntries(byDate);
    } catch {
      setError(t('workload.load_error'));
    } finally {
      setLoading(false);
    }
  }, [view, t]);

  useEffect(() => {
    loadMonth();
  }, [loadMonth]);

  const shiftMonth = (delta) => {
    setView(({ y, m }) => {
      const d = new Date(y, m + delta, 1);
      return { y: d.getFullYear(), m: d.getMonth() };
    });
  };

  /** Write a record into local state. */
  const putEntry = (dateStr, record) =>
    setEntries((prev) => ({ ...prev, [dateStr]: record }));

  /** Drop a record from local state. */
  const dropEntry = (dateStr) =>
    setEntries((prev) => {
      const next = { ...prev };
      delete next[dateStr];
      return next;
    });

  /**
   * Advance a day to the next state in the cycle, with optimistic UI.
   * On failure the previous value is restored and a toast is shown.
   *
   *   NONE -> BLOCKED     POST   (reason = UNAVAILABLE)
   *   BLOCKED -> PREFERRED PUT   (reason = PREFERRED)
   *   PREFERRED -> NONE   DELETE
   */
  const cycleDay = async (day) => {
    if (isPastMonth || day == null) return;
    const dateStr = isoDate(view.y, view.m, day);
    if (pendingRef.current.has(dateStr)) return;

    const existing = entries[dateStr] || null;
    const current = stateOfRecord(existing);
    pendingRef.current.add(dateStr);

    try {
      if (current === DAY_STATE.NONE) {
        // Placeholder until the server hands back the real record (with its id).
        putEntry(dateStr, { id: null, date_absent: dateStr, reason: REASON_BLOCKED });
        try {
          const record = await createUnavailability(dateStr, REASON_BLOCKED);
          putEntry(dateStr, record);
        } catch {
          dropEntry(dateStr);
          notify(t('workload.save_error'));
        }
      } else if (current === DAY_STATE.BLOCKED) {
        // The optimistic placeholder above has no id yet — nothing to update.
        if (existing.id == null) return;
        putEntry(dateStr, { ...existing, reason: REASON_PREFERRED });
        try {
          const record = await updateUnavailability(existing.id, REASON_PREFERRED);
          putEntry(dateStr, record);
        } catch {
          putEntry(dateStr, existing);
          notify(t('workload.save_error'));
        }
      } else {
        if (existing.id == null) return;
        dropEntry(dateStr);
        try {
          await deleteUnavailability(existing.id);
        } catch {
          putEntry(dateStr, existing);
          notify(t('workload.save_error'));
        }
      }
    } finally {
      pendingRef.current.delete(dateStr);
    }
  };

  return (
    <div className="workload">
      <header className="workload-head">
        <h1 className="workload-title">{t('workload.title')}</h1>
        <div className="workload-monthnav" role="group" aria-label={t('workload.month_nav')}>
          <button type="button" className="workload-navbtn" onClick={() => shiftMonth(-1)} aria-label={t('workload.prev_month')}>
            ‹
          </button>
          <span className="workload-monthlabel">{monthLabel}</span>
          <button type="button" className="workload-navbtn" onClick={() => shiftMonth(1)} aria-label={t('workload.next_month')}>
            ›
          </button>
        </div>
      </header>

      <div className="workload-legend">
        <span className="workload-legend-item">
          <span className="workload-legend-swatch is-blocked" />
          {t('workload.legend_blocked')}
        </span>
        <span className="workload-legend-item">
          <span className="workload-legend-swatch is-preferred" />
          {t('workload.legend_preferred')}
        </span>
        <span className="workload-legend-item">
          <span className="workload-legend-swatch is-none" />
          {t('workload.legend_none')}
        </span>
      </div>

      {isPastMonth && <div className="workload-banner">{t('workload.past_month')}</div>}
      {error && (
        <div className="workload-banner workload-banner-error">
          {error}{' '}
          <button type="button" className="workload-linkbtn" onClick={loadMonth}>
            {t('workload.retry')}
          </button>
        </div>
      )}

      <div className={`workload-grid ${loading ? 'is-loading' : ''}`}>
        {dayLabels.map((label) => (
          <div key={label} className="workload-grid-head">
            {label}
          </div>
        ))}
        {cells.map((day, idx) => {
          if (day == null) {
            // eslint-disable-next-line react/no-array-index-key
            return <div key={`e${idx}`} className="workload-cell workload-cell-empty" />;
          }
          const dateStr = isoDate(view.y, view.m, day);
          const state = stateOfRecord(entries[dateStr]);
          const isToday =
            day === today.getDate() && view.m === today.getMonth() && view.y === today.getFullYear();
          const stateLabel =
            state === DAY_STATE.BLOCKED
              ? t('workload.marked')
              : state === DAY_STATE.PREFERRED
                ? t('workload.preferred')
                : '';
          return (
            <button
              type="button"
              key={dateStr}
              className={`workload-cell is-${state} ${isToday ? 'is-today' : ''}`}
              onClick={() => cycleDay(day)}
              disabled={isPastMonth}
              aria-label={`${day}. ${monthLabel}${stateLabel ? `, ${stateLabel}` : ''}`}
              title={stateLabel || undefined}
            >
              <span className="workload-cell-daynum">{day}</span>
              {state === DAY_STATE.BLOCKED && <span className="workload-cell-mark">✕</span>}
              {state === DAY_STATE.PREFERRED && <span className="workload-cell-mark">✓</span>}
            </button>
          );
        })}
      </div>

      <p className="workload-footer">
        {t('workload.marked_count', { count: counts.blocked })}
        {' · '}
        {t('workload.preferred_count', { count: counts.preferred })}
      </p>

      {toast && (
        <div className="workload-toast" role="status">
          {toast}
        </div>
      )}
    </div>
  );
};

export default WorkloadView;