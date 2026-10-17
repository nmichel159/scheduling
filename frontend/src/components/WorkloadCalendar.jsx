import { useState, useEffect, useMemo, useCallback, useId, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import {
  stateOfRecord,
  DAY_STATE,
  MARKABLE_STATES,
  REASON_BY_STATE,
} from '../services/unavailabilityService';
import { isDayLimitError, isMonthLockedError } from '../services/availabilityService';
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

/* Both wishes as the inputs hold them: an empty string is "no opinion".
   The standing wish and the scheduler's cap ride along for display. */
const EMPTY_WISH = {
  max_shifts_per_month: '',
  max_surcharge_shifts_per_month: '',
  standing: null,
  cap: null,
};
const wishText = (wish) => ({
  standing: wish?.standing_max_shifts_per_month ?? null,
  cap: wish?.scheduler_max_shifts_per_month ?? null,
  max_shifts_per_month:
    wish?.max_shifts_per_month == null ? '' : String(wish.max_shifts_per_month),
  max_surcharge_shifts_per_month:
    wish?.max_surcharge_shifts_per_month == null
      ? ''
      : String(wish.max_surcharge_shifts_per_month),
});

/**
 * Reusable monthly restriction calendar; a click walks a day through the states.
 *
 * With a `title` it lays itself out as a page (page header, calendar card);
 * without one it is embedded — in the manager's availability dialog — and
 * shows only its controls and the grid.
 */
const WorkloadCalendar = ({
  title,
  titleLevel = 1,
  fetchEntries,
  createEntry,
  updateEntry,
  deleteEntry,
  fetchMonthlyWish,
  saveMonthlyWish,
  fetchMonthStatus,
}) => {
  const { t, i18n } = useTranslation();
  const TitleTag = `h${titleLevel}`;
  const wishInputId = useId();
  const surchargeWishInputId = useId();
  const today = useMemo(() => new Date(), []);
  const [view, setView] = useState({ y: today.getFullYear(), m: today.getMonth() });
  const [entries, setEntries] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [toast, notify] = useToast();
  const [wish, setWish] = useState(EMPTY_WISH);
  // Closed by the scheduler's window; only the employee's own calendar asks.
  const [monthLocked, setMonthLocked] = useState(false);
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

  useEffect(() => {
    setMonthLocked(false);
    if (!fetchMonthStatus) return undefined;
    let cancelled = false;
    fetchMonthStatus(view.y, view.m + 1)
      .then((status) => {
        if (!cancelled) setMonthLocked(Boolean(status.locked));
      })
      .catch(() => {
        // The server refuses a closed month anyway; the grid stays usable.
      });
    return () => {
      cancelled = true;
    };
  }, [fetchMonthStatus, view]);

  // The duty wish is the month's own (it falls back to the standing one
  // from the conditions screen), so it is loaded again with every month.
  const period = useMemo(() => ({ year: view.y, month: view.m + 1 }), [view]);
  useEffect(() => {
    if (!fetchMonthlyWish) return undefined;
    let cancelled = false;
    setWish(EMPTY_WISH);
    (async () => {
      try {
        const value = await fetchMonthlyWish(period);
        if (!cancelled) setWish(wishText(value));
      } catch {
        // A wish that cannot be read must not hide the calendar.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [fetchMonthlyWish, period]);

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

  const refuse = (error) => {
    if (isMonthLockedError(error)) {
      setMonthLocked(true);
      notify(t('workload.locked_month'));
    } else {
      notify(t('workload.save_error'));
    }
  };

  /** Write one state onto a day; resolves to the record, rejects on refusal. */
  const writeState = async (dateStr, existing, nextState) => {
    const reason = REASON_BY_STATE[nextState];
    if (existing == null) {
      putEntry(dateStr, { id: null, date_absent: dateStr, reason });
      try {
        const record = await createEntry(dateStr, reason);
        putEntry(dateStr, record);
        return record;
      } catch (error) {
        dropEntry(dateStr);
        throw error;
      }
    }
    putEntry(dateStr, { ...existing, reason });
    try {
      const record = await updateEntry(existing.id, reason);
      putEntry(dateStr, record);
      return record;
    } catch (error) {
      putEntry(dateStr, existing);
      throw error;
    }
  };

  /** Advance one day to the next state in the cycle. A state whose limit for
   *  the day is used up is stepped over to the one after it. */
  const cycleDay = async (dateStr) => {
    if (dateStr < todayStr || monthLocked) return;
    if (pendingRef.current.has(dateStr)) return;

    const existing = entries[dateStr] || null;
    if (existing && existing.id == null) return;
    const current = stateOfRecord(existing);
    pendingRef.current.add(dateStr);
    const full = [];

    try {
      let index = STATE_CYCLE.indexOf(current);
      for (;;) {
        index = (index + 1) % STATE_CYCLE.length;
        const nextState = STATE_CYCLE[index];

        if (nextState === DAY_STATE.NONE) {
          if (existing?.id != null) {
            dropEntry(dateStr);
            try {
              await deleteEntry(existing.id);
            } catch (error) {
              putEntry(dateStr, existing);
              refuse(error);
              return;
            }
          }
          break;
        }

        try {
          await writeState(dateStr, existing, nextState);
          break;
        } catch (error) {
          if (!isDayLimitError(error)) {
            refuse(error);
            return;
          }
          full.push(t(`workload.states.${nextState}`));
        }
      }
      if (full.length > 0) notify(t('workload.day_full', { states: full.join(', ') }));
    } finally {
      pendingRef.current.delete(dateStr);
    }
  };

  const commitWish = async (field, raw) => {
    if (!saveMonthlyWish) return;
    const trimmed = raw.trim();
    const value = trimmed === '' ? null : Number(trimmed);
    if (value != null && (!Number.isInteger(value) || value < 0 || value > 31)) {
      notify(t('workload.wish_invalid'));
      return;
    }
    try {
      setWish(wishText(await saveMonthlyWish({ [field]: value }, period)));
    } catch {
      notify(t('workload.save_error'));
    }
  };

  const wishField = (field, inputId, labelKey, placeholder) => (
    <div className="workload-wish">
      <label className="workload-wish-label" htmlFor={inputId}>
        {t(labelKey)}
      </label>
      <input
        id={inputId}
        className="input input-sm workload-wish-input"
        type="number"
        min="0"
        max="31"
        inputMode="numeric"
        placeholder={placeholder ?? t('workload.wish_placeholder')}
        value={wish[field]}
        onChange={(event) => {
          const { value } = event.target;
          setWish((previous) => ({ ...previous, [field]: value }));
        }}
        onBlur={(event) => commitWish(field, event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') event.currentTarget.blur();
        }}
      />
    </div>
  );

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
          </div>
          <div className="page-actions">{stepper}</div>
        </header>
      ) : (
        <div className="workload-toolbar">{stepper}</div>
      )}

      {isPastMonth && <div className="alert alert-info workload-alert">{t('workload.past_month')}</div>}
      {!isPastMonth && monthLocked && (
        <div className="alert alert-info workload-alert">{t('workload.locked_month')}</div>
      )}
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

          {/* The duty wish is this month's; the surcharge wish is the
              employee's standing one, set about as often, so it rides along. */}
          {saveMonthlyWish && (
            <div className="workload-wishes">
              {wishField(
                'max_shifts_per_month',
                wishInputId,
                'workload.wish_label',
                wish.standing != null ? String(wish.standing) : undefined
              )}
              {wish.cap != null && (
                <div className="workload-wish">
                  <span className="workload-wish-label">{t('workload.scheduler_cap')}</span>
                  <span className="workload-wish-cap">{wish.cap}</span>
                </div>
              )}
              {wishField(
                'max_surcharge_shifts_per_month',
                surchargeWishInputId,
                'workload.surcharge_wish_label'
              )}
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
            const isClosed = isPast || monthLocked;
            const stateLabel = state === DAY_STATE.NONE ? '' : t(`workload.states.${state}`);
            return (
              <button
                type="button"
                key={dateStr}
                className={`workload-cell is-${state}${index % 7 >= 5 ? ' is-weekend' : ''}${
                  isToday ? ' is-today' : ''
                }${isPast ? ' is-past' : ''}`}
                onClick={() => cycleDay(dateStr)}
                disabled={isClosed}
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
