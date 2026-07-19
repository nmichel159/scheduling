import { useState, useEffect, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { fetchMySchedule } from '../services/scheduleService';
import { fetchMyAssignedAmbulances } from '../services/ambulanceService';
import './ScheduleView.css';

/* Local calendar helpers — same shape as the ones in WorkloadView. Kept
 * local on purpose so this view can ship without touching that file; if a
 * third calendar view ever appears, pull them into src/utils/calendar.js. */

/** Zero-pad a number to two digits. */
const pad = (n) => String(n).padStart(2, '0');

/** Build an ISO date string from year, month index (0-11) and day. */
const isoDate = (y, m, d) => `${y}-${pad(m + 1)}-${pad(d)}`;

/** ISO weekday index: 0=Monday ... 6=Sunday. */
const isoWeekday = (dateObj) => (dateObj.getDay() + 6) % 7;

/** Flat array of day numbers for a month grid (null = filler cell). */
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
 * Read-only monthly schedule for the logged-in employee (role 1).
 *
 * The backend decides the month: GET /schedules/me is fixed to the running
 * month, so the view labels whichever month that is and offers no month
 * navigation. Adding year/month query params server-side is all that stands
 * between this and a browsable calendar.
 */
const ScheduleView = () => {
  const { t, i18n } = useTranslation();
  const today = useMemo(() => new Date(), []);

  const [shifts, setShifts] = useState([]);
  const [ambulanceNames, setAmbulanceNames] = useState({}); // { id: name }
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const view = { y: today.getFullYear(), m: today.getMonth() };

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      /* The ambulance lookup is a nice-to-have: ScheduleResponse carries
       * competence_name but only ambulance_id, so names come from the
       * assignment list. A failure there must not blank out the schedule,
       * hence allSettled rather than Promise.all. */
      const [scheduleResult, ambulancesResult] = await Promise.allSettled([
        fetchMySchedule(),
        fetchMyAssignedAmbulances(),
      ]);

      if (scheduleResult.status === 'rejected') throw scheduleResult.reason;
      setShifts(scheduleResult.value);

      if (ambulancesResult.status === 'fulfilled') {
        const byId = {};
        ambulancesResult.value.forEach((a) => {
          byId[a.id] = a.name;
        });
        setAmbulanceNames(byId);
      }
    } catch {
      setError(t('schedule.load_error'));
    } finally {
      setLoading(false);
    }
  }, [t]);

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

  const cells = useMemo(() => buildMonthCells(view.y, view.m), [view.y, view.m]);

  const monthLabel = useMemo(() => {
    const formatter = new Intl.DateTimeFormat(i18n.language === 'en' ? 'en-GB' : 'sk-SK', {
      month: 'long',
      year: 'numeric',
    });
    return formatter.format(new Date(view.y, view.m, 1));
  }, [view.y, view.m, i18n.language]);

  const dayLabels = useMemo(
    () => [0, 1, 2, 3, 4, 5, 6].map((i) => t(`workload.days.${i}`)),
    [t]
  );

  const labelFor = (shift) =>
    ambulanceNames[shift.ambulance_id] || t('schedule.ambulance_fallback', { id: shift.ambulance_id });

  return (
    <div className="schedule">
      <header className="schedule-head">
        <h1 className="schedule-title">{t('schedule.title')}</h1>
        <span className="schedule-monthlabel">{monthLabel}</span>
      </header>

      <p className="schedule-subtitle">{t('schedule.subtitle')}</p>

      {error && (
        <div className="schedule-banner schedule-banner-error">
          {error}{' '}
          <button type="button" className="schedule-linkbtn" onClick={load}>
            {t('schedule.retry')}
          </button>
        </div>
      )}

      {!loading && !error && shifts.length === 0 && (
        <div className="schedule-banner">{t('schedule.empty')}</div>
      )}

      <div className={`schedule-grid ${loading ? 'is-loading' : ''}`}>
        {dayLabels.map((label) => (
          <div key={label} className="schedule-grid-head">
            {label}
          </div>
        ))}
        {cells.map((day, idx) => {
          if (day == null) {
            // eslint-disable-next-line react/no-array-index-key
            return <div key={`e${idx}`} className="schedule-cell schedule-cell-empty" />;
          }
          const dateStr = isoDate(view.y, view.m, day);
          const dayShifts = byDate[dateStr] || [];
          const isToday = day === today.getDate();
          return (
            <div
              key={dateStr}
              className={`schedule-cell ${dayShifts.length > 0 ? 'has-shift' : ''} ${
                isToday ? 'is-today' : ''
              }`}
            >
              <span className="schedule-cell-daynum">{day}</span>
              {dayShifts.map((s) => (
                <span key={s.id} className="schedule-shift" title={labelFor(s)}>
                  <span className="schedule-shift-ambulance">{labelFor(s)}</span>
                  {s.competence_name && (
                    <span className="schedule-shift-competence">{s.competence_name}</span>
                  )}
                </span>
              ))}
            </div>
          );
        })}
      </div>

      <p className="schedule-footer">{t('schedule.shift_count', { count: shifts.length })}</p>
    </div>
  );
};

export default ScheduleView;
