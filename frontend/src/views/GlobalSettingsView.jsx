import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import AvailabilityWindowCard from '../components/AvailabilityWindowCard';
import { CloseIcon } from '../components/NavIcons';
import PageSkeleton from '../components/Skeleton';
import PeriodStepper from '../components/PeriodStepper';
import Toast from '../components/Toast';
import { useToast } from '../hooks/useToast';
import { useWorkplace } from '../hooks/workplaceContext';
import {
  LIMITED_REASONS,
  fetchDayDetail,
  fetchDayLimits,
  fetchMonthOverview,
  fetchWorkplaceMonthStatus,
  saveDayLimits,
  setMonthLock,
} from '../services/availabilityService';
import {
  buildMonthCells,
  capitalizeFirst,
  isoDate,
  localeFor,
} from '../utils/calendar';
import './GlobalSettingsView.css';

/** Every reason the calendar shows, in the order it shows them. */
const REASONS = [...LIMITED_REASONS, 'SOFT_DECLINE', 'PREFERRED'];

/** The restriction-calendar state each reason is drawn as, for its colour. */
const STATE_OF_REASON = {
  PREFERRED: 'preferred',
  SOFT_DECLINE: 'soft-decline',
  UNAVAILABLE: 'unavailable',
  VACATION: 'vacation',
  BUSINESS_TRIP: 'business-trip',
};

const WEEKDAYS = [0, 1, 2, 3, 4, 5, 6];

/** The month being filled in now: always the next calendar month. */
const upcomingMonth = () => {
  const today = new Date();
  return new Date(today.getFullYear(), today.getMonth() + 1, 1);
};

const limitText = (limits) =>
  Object.fromEntries(
    LIMITED_REASONS.map((reason) => [
      reason,
      limits?.[reason] == null ? '' : String(limits[reason]),
    ])
  );

/** A whole number 0..1000, `null` for an empty field, `undefined` if invalid. */
const parseLimit = (text) => {
  const trimmed = text.trim();
  if (trimmed === '') return null;
  const value = Number(trimmed);
  return Number.isInteger(value) && value >= 0 && value <= 1000 ? value : undefined;
};

/**
 * How the people of the selected workplace fill in their restrictions.
 *
 * - How many of the workplace's people may be away on the same day, per kind
 *   of absence. An employee filling in a day that is full in any of their
 *   workplaces is refused; the scheduler entering it for them is not.
 * - The window in which a month is filled in: the reminder day and the lock
 *   day (AvailabilityWindowCard).
 * - An overview calendar of what the workplace's people entered, month by
 *   month, with the month's lock switch. A day opens the list of who entered
 *   it, per reason in the order it was entered -- the order in which a limit
 *   was used up.
 */
const GlobalSettingsView = () => {
  const { t, i18n } = useTranslation();
  const locale = localeFor(i18n.language);
  const [toast, notify] = useToast(3200);
  const {
    workplaces,
    activeId: ambulanceId,
    loading: workplacesLoading,
    forbidden,
  } = useWorkplace();

  const [limits, setLimits] = useState(null);
  const [limitDraft, setLimitDraft] = useState(limitText(null));
  const [savingLimits, setSavingLimits] = useState(false);

  const [month, setMonth] = useState(upcomingMonth);
  const [overview, setOverview] = useState(null);
  const [status, setStatus] = useState(null);
  const [loadError, setLoadError] = useState(false);
  const [lockBusy, setLockBusy] = useState(false);
  const [windowKey, setWindowKey] = useState(0);

  const [openDay, setOpenDay] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailError, setDetailError] = useState(false);

  const year = month.getFullYear();
  const monthNumber = month.getMonth() + 1;

  useEffect(() => {
    setLimits(null);
    setLimitDraft(limitText(null));
    if (ambulanceId == null) return undefined;
    let current = true;
    fetchDayLimits(ambulanceId)
      .then((data) => {
        if (!current) return;
        setLimits(data);
        setLimitDraft(limitText(data));
      })
      .catch(() => current && setLoadError(true));
    return () => {
      current = false;
    };
  }, [ambulanceId]);

  // Only the answer for the month still on screen is kept.
  const requestRef = useRef(0);
  const loadMonth = useCallback(async () => {
    if (ambulanceId == null) return;
    const request = ++requestRef.current;
    setLoadError(false);
    try {
      const [monthOverview, monthStatus] = await Promise.all([
        fetchMonthOverview(ambulanceId, year, monthNumber),
        fetchWorkplaceMonthStatus(ambulanceId, year, monthNumber),
      ]);
      if (request !== requestRef.current) return;
      setOverview(monthOverview);
      setStatus(monthStatus);
    } catch {
      if (request === requestRef.current) setLoadError(true);
    }
  }, [ambulanceId, year, monthNumber]);

  useEffect(() => {
    setOpenDay(null);
    setOverview(null);
    setStatus(null);
    loadMonth();
  }, [loadMonth]);

  const countsByDay = useMemo(
    () =>
      Object.fromEntries((overview?.days ?? []).map((day) => [day.date, day.counts])),
    [overview]
  );
  const shownLimits = overview?.limits ?? limits ?? {};

  const monthLabel = capitalizeFirst(
    new Intl.DateTimeFormat(locale, { month: 'long', year: 'numeric' }).format(month)
  );
  const isUpcoming =
    year === upcomingMonth().getFullYear() && month.getMonth() === upcomingMonth().getMonth();

  const reasonLabel = (reason) => t(`global_settings.reasons.${reason}`);

  /* ---- day limits ---- */

  const parsedLimits = Object.fromEntries(
    LIMITED_REASONS.map((reason) => [reason, parseLimit(limitDraft[reason])])
  );
  const limitsValid = Object.values(parsedLimits).every((value) => value !== undefined);
  const limitsChanged =
    limits != null &&
    LIMITED_REASONS.some((reason) => parsedLimits[reason] !== (limits[reason] ?? null));

  const saveLimits = async () => {
    setSavingLimits(true);
    try {
      const saved = await saveDayLimits(ambulanceId, parsedLimits);
      setLimits(saved);
      setLimitDraft(limitText(saved));
      setOverview((current) => (current ? { ...current, limits: saved } : current));
      notify(t('global_settings.saved'));
    } catch {
      notify(t('global_settings.save_error'));
    } finally {
      setSavingLimits(false);
    }
  };

  /* ---- month lock ---- */

  const toggleLock = async () => {
    setLockBusy(true);
    try {
      setStatus(await setMonthLock(ambulanceId, year, monthNumber, !status.locked));
      if (isUpcoming) setWindowKey((key) => key + 1);
    } catch {
      notify(t('global_settings.save_error'));
    } finally {
      setLockBusy(false);
    }
  };

  /* ---- day detail ---- */

  const openDetail = async (day) => {
    setOpenDay(day);
    setDetail(null);
    setDetailError(false);
    try {
      setDetail(await fetchDayDetail(ambulanceId, day));
    } catch {
      setDetailError(true);
    }
  };

  const closeDetail = () => setOpenDay(null);

  useEffect(() => {
    if (!openDay) return undefined;
    const onKey = (event) => {
      if (event.key === 'Escape') setOpenDay(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [openDay]);

  const groupedEntries = useMemo(() => {
    if (!detail) return [];
    return REASONS.map((reason) => ({
      reason,
      entries: detail.entries.filter((entry) => entry.reason === reason),
    })).filter((group) => group.entries.length > 0);
  }, [detail]);

  const formatDay = (iso) =>
    capitalizeFirst(
      new Intl.DateTimeFormat(locale, {
        weekday: 'long',
        day: 'numeric',
        month: 'numeric',
        year: 'numeric',
      }).format(new Date(`${iso}T00:00:00`))
    );
  const formatMoment = (iso) =>
    iso
      ? new Intl.DateTimeFormat(locale, {
          day: 'numeric',
          month: 'numeric',
          year: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
        }).format(new Date(iso))
      : '—';

  if (workplacesLoading) {
    return (
      <PageSkeleton
        className="page gset"
        title={t('global_settings.title')}
        variant="grid"
        label={t('departments.loading')}
      />
    );
  }

  if (forbidden || workplaces.length === 0) {
    return (
      <div className="page gset">
        <header className="page-header">
          <h1 className="page-title">{t('global_settings.title')}</h1>
        </header>
        <div className="alert alert-warning">
          {forbidden ? t('departments.forbidden') : t('departments.no_ambulances')}
        </div>
      </div>
    );
  }

  const cells = buildMonthCells(year, month.getMonth());
  const todayIso = (() => {
    const now = new Date();
    return isoDate(now.getFullYear(), now.getMonth(), now.getDate());
  })();

  return (
    <div className="page gset">
      <header className="page-header">
        <div>
          <h1 className="page-title">{t('global_settings.title')}</h1>
        </div>
      </header>

      <div className="gset-top">
        <section className="card gset-limits" aria-labelledby="gset-limits-title">
          <div className="card-header">
            <h2 id="gset-limits-title" className="card-title">
              {t('global_settings.limits_title')}
            </h2>
          </div>
          <div className="card-pad gset-limits-body">
            {LIMITED_REASONS.map((reason) => (
              <label key={reason} className="field gset-limit">
                <span className="field-label">
                  <span className={`gset-dot is-${STATE_OF_REASON[reason]}`} aria-hidden="true" />
                  {reasonLabel(reason)}
                </span>
                <input
                  type="number"
                  className="input input-sm"
                  min={0}
                  max={1000}
                  inputMode="numeric"
                  placeholder={t('global_settings.no_limit')}
                  value={limitDraft[reason]}
                  disabled={limits == null}
                  aria-invalid={parsedLimits[reason] === undefined}
                  onChange={(event) =>
                    setLimitDraft((current) => ({ ...current, [reason]: event.target.value }))
                  }
                />
              </label>
            ))}
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={savingLimits || !limitsChanged || !limitsValid}
              onClick={saveLimits}
            >
              {t('global_settings.save')}
            </button>
            {!limitsValid && (
              <p className="field-error gset-limits-error" role="alert">
                {t('global_settings.invalid_limit')}
              </p>
            )}
          </div>
        </section>

        <AvailabilityWindowCard
          ambulanceId={ambulanceId}
          refreshKey={windowKey}
          onDaysSaved={() => {
            fetchWorkplaceMonthStatus(ambulanceId, year, monthNumber)
              .then(setStatus)
              .catch(() => {});
          }}
        />
      </div>

      <section className="card gset-calendar" aria-labelledby="gset-calendar-title">
        <div className="card-header gset-calendar-header">
          <h2 id="gset-calendar-title" className="card-title">
            {t('global_settings.overview_title')}
          </h2>
          {status && (
            <span
              className={`badge ${status.locked ? 'badge-danger' : 'badge-success'}`}
              aria-live="polite"
            >
              {status.locked
                ? t('availability_window.locked')
                : t('availability_window.open')}
              {status.manual != null && !status.is_past && ` · ${t('availability_window.manual')}`}
            </span>
          )}
          {status && !status.is_past && (
            <button
              type="button"
              className={`btn btn-sm ${status.locked ? 'btn-secondary' : 'btn-danger-outline'}`}
              disabled={lockBusy}
              onClick={toggleLock}
            >
              {status.locked
                ? t('global_settings.unlock_month')
                : t('global_settings.lock_month')}
            </button>
          )}
          <div className="gset-stepper">
            <PeriodStepper
              label={monthLabel}
              onPrevious={() => setMonth(new Date(year, month.getMonth() - 1, 1))}
              onNext={() => setMonth(new Date(year, month.getMonth() + 1, 1))}
              previousLabel={t('workload.prev_month')}
              nextLabel={t('workload.next_month')}
              todayLabel={t('global_settings.back_to_upcoming')}
              onToday={() => setMonth(upcomingMonth())}
              compactToday
              todayDisabled={isUpcoming}
              groupLabel={t('workload.month_nav')}
            />
          </div>
        </div>

        <div className="card-pad">
          <ul className="gset-legend">
            {REASONS.filter((reason) =>
              (overview?.days ?? []).some((day) => day.counts?.[reason] > 0)
            ).map((reason) => (
              <li key={reason}>
                <span className={`gset-dot is-${STATE_OF_REASON[reason]}`} aria-hidden="true" />
                {reasonLabel(reason)}
              </li>
            ))}
          </ul>

          {loadError ? (
            <div className="alert alert-danger" role="alert">
              {t('global_settings.load_error')}{' '}
              <button type="button" className="btn btn-sm" onClick={loadMonth}>
                {t('workload.retry')}
              </button>
            </div>
          ) : (
            <div className="gset-grid" role="grid" aria-busy={!overview}>
              <div className="gset-row gset-weekdays" role="row">
                {WEEKDAYS.map((day) => (
                  <div key={day} role="columnheader" className="gset-weekday">
                    {t(`workload.days.${day}`)}
                  </div>
                ))}
              </div>
              {Array.from({ length: cells.length / 7 }, (_, row) => (
                <div key={row} className="gset-row" role="row">
                  {cells.slice(row * 7, row * 7 + 7).map((day, index) => {
                    if (day == null) {
                      return <div key={`blank-${index}`} className="gset-cell is-blank" role="gridcell" />;
                    }
                    const iso = isoDate(year, month.getMonth(), day);
                    const counts = countsByDay[iso] ?? {};
                    const total = Object.values(counts).reduce((sum, n) => sum + n, 0);
                    const full = LIMITED_REASONS.some(
                      (reason) =>
                        shownLimits[reason] != null && (counts[reason] ?? 0) >= shownLimits[reason]
                    );
                    return (
                      <button
                        key={iso}
                        type="button"
                        role="gridcell"
                        className={`gset-cell${full ? ' is-full' : ''}${
                          iso === todayIso ? ' is-today' : ''
                        }${index >= 5 ? ' is-weekend' : ''}`}
                        onClick={() => openDetail(iso)}
                        aria-label={`${formatDay(iso)}: ${t('global_settings.people', {
                          count: total,
                        })}`}
                      >
                        <span className="gset-day">{day}</span>
                        <span className="gset-counts">
                          {REASONS.filter((reason) => counts[reason]).map((reason) => {
                            const limit = LIMITED_REASONS.includes(reason)
                              ? shownLimits[reason]
                              : null;
                            const over = limit != null && counts[reason] >= limit;
                            return (
                              <span
                                key={reason}
                                className={`gset-count is-${STATE_OF_REASON[reason]}${
                                  over ? ' is-over' : ''
                                }`}
                                title={reasonLabel(reason)}
                              >
                                {counts[reason]}
                                {limit != null && <span className="gset-of">/{limit}</span>}
                              </span>
                            );
                          })}
                        </span>
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      {openDay && (
        <div
          className="dialog-overlay"
          onClick={(event) => {
            if (event.target === event.currentTarget) closeDetail();
          }}
        >
          <div
            className="dialog dialog-lg gset-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="gset-dialog-title"
          >
            <div className="dialog-header">
              <h2 id="gset-dialog-title" className="dialog-title">
                {formatDay(openDay)}
              </h2>
              <button
                type="button"
                className="dialog-close"
                onClick={closeDetail}
                title={t('global_settings.close')}
                aria-label={t('global_settings.close')}
              >
                <CloseIcon />
              </button>
            </div>
            <div className="dialog-body">
              {detailError && (
                <div className="alert alert-danger" role="alert">
                  {t('global_settings.load_error')}
                </div>
              )}
              {!detail && !detailError && <p className="gset-muted">…</p>}
              {detail && groupedEntries.length === 0 && (
                <p className="empty-state">{t('global_settings.nobody')}</p>
              )}
              {groupedEntries.map(({ reason, entries }) => {
                const limit = LIMITED_REASONS.includes(reason) ? detail.limits[reason] : null;
                return (
                  <section key={reason} className="gset-group">
                    <h3 className="gset-group-title">
                      <span className={`gset-dot is-${STATE_OF_REASON[reason]}`} aria-hidden="true" />
                      {reasonLabel(reason)}
                      <span
                        className={`badge${
                          limit != null && entries.length >= limit ? ' badge-danger' : ''
                        }`}
                      >
                        {limit != null ? `${entries.length} / ${limit}` : entries.length}
                      </span>
                    </h3>
                    <table className="data-table gset-table">
                      <thead>
                        <tr>
                          <th scope="col" className="gset-order">#</th>
                          <th scope="col">{t('global_settings.col_employee')}</th>
                          <th scope="col">{t('global_settings.col_workplaces')}</th>
                          <th scope="col">{t('global_settings.col_entered_at')}</th>
                          <th scope="col">{t('global_settings.col_entered_by')}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {entries.map((entry, index) => (
                          <tr
                            key={entry.id}
                            className={limit != null && index >= limit ? 'is-over' : undefined}
                          >
                            <td className="gset-order">{index + 1}.</td>
                            <td>{entry.full_name || entry.email}</td>
                            <td>{entry.workplaces.join(', ') || '—'}</td>
                            <td className="gset-moment">{formatMoment(entry.entered_at)}</td>
                            <td>
                              {entry.entered_by_user_id == null
                                ? '—'
                                : entry.entered_by_user_id === entry.user_id
                                  ? t('global_settings.entered_self')
                                  : entry.entered_by_name}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </section>
                );
              })}
            </div>
          </div>
        </div>
      )}

      <Toast message={toast} />
    </div>
  );
};

export default GlobalSettingsView;
