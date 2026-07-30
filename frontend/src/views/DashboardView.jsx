import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { fetchMyAssignedAmbulances } from '../services/ambulanceService';
import {
  fetchMyMonthlyScheduleStatistics,
  fetchMyNextShift,
  fetchMySchedule,
  fetchMyWorkedScheduleStatistics,
} from '../services/scheduleService';
import './DashboardView.css';

const pad = (value) => String(value).padStart(2, '0');
const isoDate = (year, month, day) => `${year}-${pad(month + 1)}-${pad(day)}`;
const isoWeekday = (date) => (date.getDay() + 6) % 7;

function buildMonthCells(year, month) {
  const cells = Array(isoWeekday(new Date(year, month, 1))).fill(null);
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  for (let day = 1; day <= daysInMonth; day += 1) cells.push(day);
  while (cells.length % 7 !== 0) cells.push(null);
  return cells;
}

const DashboardView = () => {
  const { t, i18n } = useTranslation();
  const today = useMemo(() => new Date(), []);
  const view = { year: today.getFullYear(), month: today.getMonth() };
  const [schedule, setSchedule] = useState([]);
  const [nextShift, setNextShift] = useState(null);
  const [monthlyStatistics, setMonthlyStatistics] = useState(null);
  const [workedStatistics, setWorkedStatistics] = useState(null);
  const [ambulanceNames, setAmbulanceNames] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const userString = localStorage.getItem('user');
  const user = userString ? JSON.parse(userString) : null;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [scheduleResult, nextResult, monthlyResult, workedResult, ambulancesResult] =
        await Promise.all([
          fetchMySchedule({ month: view.month + 1, year: view.year }),
          fetchMyNextShift(),
          fetchMyMonthlyScheduleStatistics(),
          fetchMyWorkedScheduleStatistics(),
          fetchMyAssignedAmbulances(),
        ]);

      setSchedule(scheduleResult);
      setNextShift(nextResult.next_shift);
      setMonthlyStatistics(monthlyResult);
      setWorkedStatistics(workedResult);
      setAmbulanceNames(
        Object.fromEntries(ambulancesResult.map((ambulance) => [ambulance.id, ambulance.name]))
      );
    } catch {
      setError(t('dashboard.load_error'));
    } finally {
      setLoading(false);
    }
  }, [t, view.month, view.year]);

  useEffect(() => {
    load();
  }, [load]);

  const shiftsByDate = useMemo(() => {
    const grouped = {};
    schedule.forEach((shift) => {
      (grouped[shift.work_date] = grouped[shift.work_date] || []).push(shift);
    });
    return grouped;
  }, [schedule]);

  const cells = useMemo(
    () => buildMonthCells(view.year, view.month),
    [view.year, view.month]
  );
  const dayLabels = useMemo(
    () => [0, 1, 2, 3, 4, 5, 6].map((day) => t(`workload.days.${day}`)),
    [t]
  );
  const locale = i18n.language === 'en' ? 'en-GB' : 'sk-SK';
  const monthLabel = new Intl.DateTimeFormat(locale, {
    month: 'long',
    year: 'numeric',
  }).format(new Date(view.year, view.month, 1));
  const dateLabel = (dateString) =>
    new Intl.DateTimeFormat(locale, {
      weekday: 'long',
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    }).format(new Date(`${dateString}T00:00:00`));
  const shiftLabel = (shift) =>
    ambulanceNames[shift.ambulance_id] ||
    t('schedule.ambulance_fallback', { id: shift.ambulance_id });

  if (!user) return <p className="dashboard-login-needed">{t('dashboard.login_needed')}</p>;

  return (
    <main className="dashboard">
      <header className="dashboard-header">
        <div>
          <p className="dashboard-eyebrow">{t('dashboard.overview')}</p>
          <h1>{t('dashboard.greeting', { name: user.full_name })}</h1>
          <p className="dashboard-subtitle">{t('dashboard.subtitle')}</p>
        </div>
        <span className="dashboard-month">{monthLabel}</span>
      </header>

      {error && (
        <div className="dashboard-error">
          {error}{' '}
          <button type="button" onClick={load}>{t('dashboard.retry')}</button>
        </div>
      )}

      <section className={`dashboard-summary ${loading ? 'is-loading' : ''}`}>
        <article className="dashboard-card dashboard-next-shift">
          <span className="dashboard-card-icon" aria-hidden="true">◷</span>
          <div>
            <p className="dashboard-card-label">{t('dashboard.next_shift')}</p>
            {nextShift ? (
              <>
                <h2>{dateLabel(nextShift.work_date)}</h2>
                <p>{shiftLabel(nextShift)}{nextShift.competence_name ? ` · ${nextShift.competence_name}` : ''}</p>
              </>
            ) : (
              <h2>{t('dashboard.no_next_shift')}</h2>
            )}
          </div>
        </article>

        <article className="dashboard-card dashboard-stat-card">
          <p className="dashboard-card-label">{t('dashboard.planned_shifts')}</p>
          <strong>{monthlyStatistics?.scheduled_shift_count ?? '–'}</strong>
          <span>{t('dashboard.this_month')}</span>
        </article>

        <article className="dashboard-card dashboard-stat-card">
          <p className="dashboard-card-label">{t('dashboard.worked_days')}</p>
          <strong>{workedStatistics?.worked_day_count ?? '–'}</strong>
          <span>{t('dashboard.until_today')}</span>
        </article>
      </section>

      <section className={`dashboard-calendar-card ${loading ? 'is-loading' : ''}`}>
        <div className="dashboard-calendar-heading">
          <div>
            <h2>{t('dashboard.schedule_title')}</h2>
            <p>{t('dashboard.schedule_subtitle')}</p>
          </div>
          <span>{monthLabel}</span>
        </div>

        <div className="dashboard-calendar" aria-label={t('dashboard.schedule_title')}>
          {dayLabels.map((label) => (
            <div key={label} className="dashboard-calendar-day-label">{label}</div>
          ))}
          {cells.map((day, index) => {
            if (day == null) return <div key={`empty-${index}`} className="dashboard-calendar-empty" />;
            const date = isoDate(view.year, view.month, day);
            const shifts = shiftsByDate[date] || [];
            const isToday =
              day === today.getDate() &&
              view.month === today.getMonth() &&
              view.year === today.getFullYear();
            return (
              <div key={date} className={`dashboard-calendar-cell ${isToday ? 'is-today' : ''}`}>
                <span className="dashboard-calendar-day-number">{day}</span>
                {shifts.map((shift) => (
                  <span key={shift.id} className="dashboard-calendar-shift" title={shiftLabel(shift)}>
                    <b>{shiftLabel(shift)}</b>
                    {shift.competence_name && <small>{shift.competence_name}</small>}
                  </span>
                ))}
              </div>
            );
          })}
        </div>
      </section>
    </main>
  );
};

export default DashboardView;
