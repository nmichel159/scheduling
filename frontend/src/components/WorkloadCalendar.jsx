import { useState, useEffect, useMemo, useCallback, useId, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import {
  stateOfRecord,
  DAY_STATE,
  MARKABLE_STATES,
  REASON_BY_STATE,
} from '../services/unavailabilityService';
import PeriodStepper from './PeriodStepper';
import Toast from './Toast';
import { useToast } from '../hooks/useToast';
import { buildMonthCells, isoDate, localeFor } from '../utils/calendar';
import '../views/WorkloadView.css';

/** The mark drawn in the corner of a marked day. Inline SVG rather than
 *  text glyphs: ☀ and ✈ turn into colour emoji on some systems and would
 *  then ignore the state colour. */
const MarkIcon = ({ children }) => (
  <svg
    className="workload-cell-mark"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    {children}
  </svg>
);

const MARK_BY_STATE = {
  [DAY_STATE.PREFERRED]: <path d="m5 12.5 4.5 4.5L19 7.5" />,
  [DAY_STATE.SOFT_DECLINE]: <path d="M4.5 13.5c2.2-3.2 4.6-3.2 7.5 0s5.3 3.2 7.5 0" />,
  [DAY_STATE.UNAVAILABLE]: <path d="M7 7l10 10M17 7 7 17" />,
  [DAY_STATE.VACATION]: (
    <>
      <circle cx="12" cy="12" r="3.6" />
      <path d="M12 3.5v1.8M12 18.7v1.8M3.5 12h1.8M18.7 12h1.8M6 6l1.3 1.3M16.7 16.7 18 18M6 18l1.3-1.3M16.7 7.3 18 6" />
    </>
  ),
  [DAY_STATE.BUSINESS_TRIP]: (
    <>
      <rect x="3.5" y="7.5" width="17" height="12" rx="2" />
      <path d="M9 7.5V6a1.5 1.5 0 0 1 1.5-1.5h3A1.5 1.5 0 0 1 15 6v1.5M3.5 12.5h17" />
    </>
  ),
};

/** The order one day walks through, one click at a time. */
const STATE_CYCLE = [DAY_STATE.NONE, ...MARKABLE_STATES];

/**
 * Reusable monthly restriction calendar; a click walks a day through the states.
 *
 * With a `title` it lays itself out as a page (page header, calendar card);
 * without one it is embedded — in the manager's availability dialog — and
 * shows only its controls and the grid.
 */
const WorkloadCalendar = ({
  title,
  subtitle,
  titleLevel = 1,
  fetchEntries,
  createEntry,
  updateEntry,
  deleteEntry,
  fetchMonthlyWish,
  saveMonthlyWish,
}) => {
  const { t, i18n } = useTranslation();
  const TitleTag = `h${titleLevel}`;
  const wishInputId = useId();
  const today = useMemo(() => new Date(), []);
  const [view, setView] = useState({ y: today.getFullYear(), m: today.getMonth() });
  const [entries, setEntries] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [toast, notify] = useToast();
  const [wish, setWish] = useState('');
  const pendingRef = useRef(new Set());
  // Only the month asked for last may fill the grid; a slow answer for the
  // month stepped away from would otherwise land under the new month's name.
  const loadSeq = useRef(0);
  const todayStr = isoDate(today.getFullYear(), today.getMonth(), today.getDate());

  const isPastMonth =
    view.y < today.getFullYear() ||
    (view.y === today.getFullYear() && view.m < today.getMonth());
  const isCurrentMonth = view.y === today.getFullYear() && view.m === today.getMonth();

  const cells = useMemo(() => buildMonthCells(view.y, view.m), [view]);
  const monthLabel = useMemo(() => {
    const formatter = new Intl.DateTimeFormat(localeFor(i18n.language), {
      month: 'long',
      year: 'numeric',
    });
    return formatter.format(new Date(view.y, view.m, 1));
  }, [view, i18n.language]);
  const dayLabels = useMemo(
    () => [0, 1, 2, 3, 4, 5, 6].map((i) => t(`workload.days.${i}`)),
    [t]
  );
  const counts = useMemo(() => {
    const byState = {};
    Object.values(entries).forEach((record) => {
      const state = stateOfRecord(record);
      byState[state] = (byState[state] || 0) + 1;
    });
    return byState;
  }, [entries]);

  const loadMonth = useCallback(async () => {
    const seq = ++loadSeq.current;
    setLoading(true);
    setError(null);
    try {
      const daysInMonth = new Date(view.y, view.m + 1, 0).getDate();
      const records = await fetchEntries(
        isoDate(view.y, view.m, 1),
        isoDate(view.y, view.m, daysInMonth)
      );
      if (seq !== loadSeq.current) return;
      const byDate = {};
      records.forEach((record) => {
        byDate[record.date_absent] = record;
      });
      setEntries(byDate);
    } catch {
      if (seq !== loadSeq.current) return;
      setEntries({});
      setError(t('workload.load_error'));
    } finally {
      if (seq === loadSeq.current) setLoading(false);
    }
  }, [fetchEntries, view, t]);

  useEffect(() => {
    loadMonth();
  }, [loadMonth]);

  // The wish belongs to the employee, not to the month on screen, so it is
  // loaded once per calendar rather than again with every month change.
  useEffect(() => {
    if (!fetchMonthlyWish) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const value = await fetchMonthlyWish();
        if (!cancelled) setWish(value == null ? '' : String(value));
      } catch {
        // A wish that cannot be read must not hide the calendar.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [fetchMonthlyWish]);

  const shiftMonth = (delta) => {
    setView(({ y, m }) => {
      const date = new Date(y, m + delta, 1);
      return { y: date.getFullYear(), m: date.getMonth() };
    });
  };

  const putEntry = (dateStr, record) =>
    setEntries((previous) => ({ ...previous, [dateStr]: record }));

  const dropEntry = (dateStr) =>
    setEntries((previous) => {
      const next = { ...previous };
      delete next[dateStr];
      return next;
    });

  /** Advance one day to the next state in the cycle. */
  const cycleDay = async (dateStr) => {
    if (dateStr < todayStr) return;
    if (pendingRef.current.has(dateStr)) return;

    const existing = entries[dateStr] || null;
    const current = stateOfRecord(existing);
    const nextState =
      STATE_CYCLE[(STATE_CYCLE.indexOf(current) + 1) % STATE_CYCLE.length];
    pendingRef.current.add(dateStr);

    try {
      if (nextState === DAY_STATE.NONE) {
        if (existing?.id == null) return;
        dropEntry(dateStr);
        try {
          await deleteEntry(existing.id);
        } catch {
          putEntry(dateStr, existing);
          notify(t('workload.save_error'));
        }
        return;
      }

      const reason = REASON_BY_STATE[nextState];
      if (existing == null) {
        putEntry(dateStr, { id: null, date_absent: dateStr, reason });
        try {
          putEntry(dateStr, await createEntry(dateStr, reason));
        } catch {
          dropEntry(dateStr);
          notify(t('workload.save_error'));
        }
      } else {
        if (existing.id == null) return;
        putEntry(dateStr, { ...existing, reason });
        try {
          putEntry(dateStr, await updateEntry(existing.id, reason));
        } catch {
          putEntry(dateStr, existing);
          notify(t('workload.save_error'));
        }
      }
    } finally {
      pendingRef.current.delete(dateStr);
    }
  };

  const commitWish = async (raw) => {
    if (!saveMonthlyWish) return;
    const trimmed = raw.trim();
    const value = trimmed === '' ? null : Number(trimmed);
    if (value != null && (!Number.isInteger(value) || value < 0 || value > 31)) {
      notify(t('workload.wish_invalid'));
      return;
    }
    try {
      const saved = await saveMonthlyWish(value);
      setWish(saved == null ? '' : String(saved));
    } catch {
      notify(t('workload.save_error'));
    }
  };

  const stepper = (
    <PeriodStepper
      label={monthLabel}
      onPrevious={() => shiftMonth(-1)}
      onNext={() => shiftMonth(1)}
      previousLabel={t('workload.prev_month')}
      nextLabel={t('workload.next_month')}
      groupLabel={t('workload.month_nav')}
      todayLabel={isCurrentMonth ? null : t('schedule.current_month')}
      onToday={() => setView({ y: today.getFullYear(), m: today.getMonth() })}
    />
  );

  const markedStates = MARKABLE_STATES.filter((state) => counts[state]);

  return (
    <div className={`workload-calendar ${title ? '' : 'is-embedded'}`}>
      {title ? (
        <header className="page-header">
          <div>
            <TitleTag className="page-title">{title}</TitleTag>
            {subtitle && <p className="page-subtitle">{subtitle}</p>}
          </div>
          <div className="page-actions">{stepper}</div>
        </header>
      ) : (
        <div className="workload-toolbar">{stepper}</div>
      )}

      {isPastMonth && <div className="alert alert-info workload-alert">{t('workload.past_month')}</div>}
      {error && (
        <div className="alert alert-danger workload-alert" role="alert">
          <span>{error}</span>
          <button type="button" className="alert-action" onClick={loadMonth}>
            {t('workload.retry')}
          </button>
        </div>
      )}

      <div className="workload-card">
        <div className="workload-card-top">
          <div className="workload-legend">
            {MARKABLE_STATES.map((state) => (
              <span key={state} className={`workload-legend-item is-${state}`}>
                <span className="workload-legend-swatch" aria-hidden="true" />
                {t(`workload.states.${state}`)}
              </span>
            ))}
            <span className="workload-legend-item is-none">
              <span className="workload-legend-swatch" aria-hidden="true" />
              {t('workload.states.none')}
            </span>
          </div>

          {/* The wish is about the employee rather than this month, but it is
              set about as often as the days are marked, so it rides along. */}
          {saveMonthlyWish && (
            <div className="workload-wish">
              <label className="workload-wish-label" htmlFor={wishInputId}>
                {t('workload.wish_label')}
              </label>
              <input
                id={wishInputId}
                className="input input-sm workload-wish-input"
                type="number"
                min="0"
                max="31"
                inputMode="numeric"
                placeholder={t('workload.wish_placeholder')}
                value={wish}
                onChange={(event) => setWish(event.target.value)}
                onBlur={(event) => commitWish(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') event.currentTarget.blur();
                }}
              />
            </div>
          )}
        </div>

        <div className="workload-grid-head" aria-hidden="true">
          {dayLabels.map((label, index) => (
            <span key={label} className={index >= 5 ? 'is-weekend' : ''}>
              {label}
            </span>
          ))}
        </div>

        <div className={`workload-grid ${loading ? 'is-loading' : ''}`} aria-busy={loading || undefined}>
          {cells.map((day, index) => {
            if (day == null) {
              return <div key={`e${index}`} className="workload-cell-empty" />;
            }
            const dateStr = isoDate(view.y, view.m, day);
            const state = stateOfRecord(entries[dateStr]);
            const isToday = dateStr === todayStr;
            const isPast = dateStr < todayStr;
            const stateLabel = state === DAY_STATE.NONE ? '' : t(`workload.states.${state}`);
            return (
              <button
                type="button"
                key={dateStr}
                className={`workload-cell is-${state}${index % 7 >= 5 ? ' is-weekend' : ''}${
                  isToday ? ' is-today' : ''
                }${isPast ? ' is-past' : ''}`}
                onClick={() => cycleDay(dateStr)}
                disabled={isPast}
                aria-label={`${day}. ${monthLabel}${stateLabel ? `, ${stateLabel}` : ''}`}
                title={stateLabel || undefined}
              >
                <span className="workload-cell-top">
                  <span className="workload-cell-daynum" aria-current={isToday ? 'date' : undefined}>
                    {day}
                  </span>
                  {MARK_BY_STATE[state] && <MarkIcon>{MARK_BY_STATE[state]}</MarkIcon>}
                </span>
                {stateLabel && <span className="workload-cell-state">{stateLabel}</span>}
              </button>
            );
          })}
        </div>

        {markedStates.length > 0 && (
          <p className="workload-footer">
            {markedStates.map((state) => (
              <span key={state} className={`workload-footer-count is-${state}`}>
                <span className="workload-legend-swatch" aria-hidden="true" />
                {t(`workload.states.${state}`)}: <strong>{counts[state]}</strong>
              </span>
            ))}
          </p>
        )}
      </div>

      <Toast message={toast} />
    </div>
  );
};

export default WorkloadCalendar;
