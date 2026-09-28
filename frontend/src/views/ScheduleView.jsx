import { useState, useEffect, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { fetchMySchedule } from '../services/scheduleService';
import ShiftCalendar from '../components/ShiftCalendar';
import PeriodStepper from '../components/PeriodStepper';
import { localeFor } from '../utils/calendar';
import './ScheduleView.css';

/** Months since year zero, so two calendar months can be compared as numbers. */
const monthIndex = (year, month) => year * 12 + month;

/* Browsing is open in both directions, but not unbounded: the API rejects a
 * year outside this range (month_range in schedule_service), so the arrows stop
 * where they do rather than asking for a month that could never load. */
const EARLIEST_MONTH_INDEX = monthIndex(2000, 0);
const LATEST_MONTH_INDEX = monthIndex(2100, 11);

/**
 * Read-only monthly schedule for the logged-in employee (role 1).
 *
 * Any month the API accepts can be browsed, back through the duties already
 * worked and forward into the ones already planned. The backend returns only
 * manager-approved schedule packages, so a month whose schedule is still a
 * draft shows up as empty rather than as a promise.
 *
 * The grid itself is ShiftCalendar, the same one the dashboard shows.
 */
const ScheduleView = () => {
  const { t, i18n } = useTranslation();
  const today = useMemo(() => new Date(), []);

  const [shifts, setShifts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [view, setView] = useState({
    y: today.getFullYear(),
    m: today.getMonth(),
  });
  const viewMonthIndex = monthIndex(view.y, view.m);
  const isCurrentMonth =
    view.y === today.getFullYear() && view.m === today.getMonth();

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setShifts(await fetchMySchedule({ month: view.m + 1, year: view.y }));
    } catch {
      // Without this the previous month's duties would stay on screen under
      // the new month's name.
      setShifts([]);
      setError(t('schedule.load_error'));
    } finally {
      setLoading(false);
    }
  }, [t, view.m, view.y]);

  useEffect(() => {
    load();
  }, [load]);

  /* Group shifts by ISO date — a day can hold more than one. */
  const byDate = useMemo(() => {
    const map = {};
    shifts.forEach((s) => {
      (map[s.work_date] = map[s.work_date] || []).push(s);
    });
    return map;
  }, [shifts]);

  const monthLabel = useMemo(() => {
    const formatter = new Intl.DateTimeFormat(localeFor(i18n.language), {
      month: 'long',
      year: 'numeric',
    });
    return formatter.format(new Date(view.y, view.m, 1));
  }, [view.y, view.m, i18n.language]);

  const labelFor = (shift) =>
    shift.ambulance_name || t('schedule.ambulance_fallback', { id: shift.ambulance_id });

  /** Step by `offset` months, or jump back to the running month when null. */
  const changeMonth = (offset) => {
    if (offset === null) {
      setView({ y: today.getFullYear(), m: today.getMonth() });
      return;
    }
    const next = new Date(view.y, view.m + offset, 1);
    setView({ y: next.getFullYear(), m: next.getMonth() });
  };

  return (
    <div className="page schedule">
      <header className="page-header">
        <div>
          <h1 className="page-title">{t('schedule.title')}</h1>
          <p className="page-subtitle">{t('schedule.page_subtitle')}</p>
        </div>
        <div className="page-actions">
          {/* Months run far in both directions, so after browsing half a
              year back there is no cheap way home without "current month". */}
          <PeriodStepper
            label={monthLabel}
            onPrevious={() => changeMonth(-1)}
            onNext={() => changeMonth(1)}
            previousLabel={t('schedule.previous_month')}
            nextLabel={t('schedule.next_month')}
            previousDisabled={viewMonthIndex <= EARLIEST_MONTH_INDEX}
            nextDisabled={viewMonthIndex >= LATEST_MONTH_INDEX}
            todayLabel={isCurrentMonth ? null : t('schedule.current_month')}
            onToday={() => changeMonth(null)}
            groupLabel={t('workload.month_nav')}
          />
        </div>
      </header>

      {error && (
        <div className="alert alert-danger schedule-alert" role="alert">
          <span>{error}</span>
          <button type="button" className="alert-action" onClick={load}>
            {t('schedule.retry')}
          </button>
        </div>
      )}

      {!loading && !error && shifts.length === 0 && (
        <div className="alert alert-info schedule-alert">{t('schedule.empty')}</div>
      )}

      <div className="card schedule-card">
        <ShiftCalendar
          year={view.y}
          month={view.m}
          shiftsByDate={byDate}
          labelFor={labelFor}
          today={today}
          loading={loading}
          label={monthLabel}
        />
        <p className="schedule-footer">{t('schedule.shift_count', { count: shifts.length })}</p>
      </div>
    </div>
  );
};

export default ScheduleView;
