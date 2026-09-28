import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { fetchMyAssignedAmbulances } from '../services/ambulanceService';
import {
  fetchMyMonthlyScheduleStatistics,
  fetchMyNextShift,
  fetchMySchedule,
  fetchMyWorkedScheduleStatistics,
} from '../services/scheduleService';
import ShiftCalendar from '../components/ShiftCalendar';
import { ChevronRightIcon, MyScheduleIcon } from '../components/NavIcons';
import { capitalizeFirst, localeFor } from '../utils/calendar';
import './DashboardView.css';

/** The signed-in user as LoginView stored it, or null if there is none or
 *  it cannot be read. */
const readStoredUser = () => {
  try {
    return JSON.parse(localStorage.getItem('user') || 'null');
  } catch {
    return null;
  }
};

/** Whom to greet: the full name, else the part of the e-mail before the @.
 *  An account without a name used to be greeted with a bare "Ahoj,". */
const greetingName = (user) =>
  user?.full_name?.trim() || user?.email?.split('@')[0]?.trim() || '';

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

  const user = useMemo(readStoredUser, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [scheduleResult, nextResult, monthlyResult, workedResult, ambulancesResult] =
        await Promise.allSettled([
          fetchMySchedule({ month: view.month + 1, year: view.year }),
          fetchMyNextShift(),
          fetchMyMonthlyScheduleStatistics(),
          fetchMyWorkedScheduleStatistics(),
          fetchMyAssignedAmbulances(),
        ]);

      if (scheduleResult.status === 'rejected') throw scheduleResult.reason;
      setSchedule(scheduleResult.value);
      setNextShift(nextResult.status === 'fulfilled' ? nextResult.value.next_shift : null);
      setMonthlyStatistics(monthlyResult.status === 'fulfilled' ? monthlyResult.value : null);
      setWorkedStatistics(workedResult.status === 'fulfilled' ? workedResult.value : null);
      setAmbulanceNames(
        ambulancesResult.status === 'fulfilled'
          ? Object.fromEntries(
              ambulancesResult.value.map((ambulance) => [ambulance.id, ambulance.name])
            )
          : {}
      );
      if ([nextResult, monthlyResult, workedResult, ambulancesResult].some(
        (result) => result.status === 'rejected'
      )) {
        setError(t('dashboard.load_error'));
      }
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

  const locale = localeFor(i18n.language);
  const monthLabel = capitalizeFirst(
    new Intl.DateTimeFormat(locale, { month: 'long', year: 'numeric' }).format(
      new Date(view.year, view.month, 1)
    )
  );
  const dateLabel = (dateString) =>
    capitalizeFirst(
      new Intl.DateTimeFormat(locale, {
        weekday: 'long',
        day: 'numeric',
        month: 'long',
        year: 'numeric',
      }).format(new Date(`${dateString}T00:00:00`))
    );
  const shiftLabel = (shift) =>
    ambulanceNames[shift.ambulance_id] ||
    t('schedule.ambulance_fallback', { id: shift.ambulance_id });

  if (!user) {
    return (
      <div className="page">
        <p className="empty-state">{t('dashboard.login_needed')}</p>
      </div>
    );
  }

  const name = greetingName(user);

  /** A figure, or a shimmer while the first answer is still on its way. */
  const statValue = (value) => {
    if (value != null) return value;
    return loading ? <span className="skeleton dashboard-stat-skeleton" /> : '–';
  };

  return (
    <div className="page dashboard">
      <header className="page-header">
        <div>
          <p className="page-eyebrow">{t('dashboard.overview')}</p>
          <h1 className="page-title">
            {name ? t('dashboard.greeting', { name }) : t('dashboard.greeting_anonymous')}
          </h1>
          <p className="page-subtitle">{t('dashboard.subtitle')}</p>
        </div>
      </header>

      {error && (
        <div className="alert alert-danger dashboard-alert" role="alert">
          <span>{error}</span>
          <button type="button" className="alert-action" onClick={load}>
            {t('dashboard.retry')}
          </button>
        </div>
      )}

      <section className={`dashboard-summary ${loading ? 'is-loading' : ''}`}>
        <article className="card dashboard-card dashboard-next-shift">
          <span className="dashboard-card-icon" aria-hidden="true">
            <MyScheduleIcon className="" />
          </span>
          <div className="dashboard-next-shift-body">
            <p className="dashboard-card-label">{t('dashboard.next_shift')}</p>
            {nextShift ? (
              <>
                <p className="dashboard-next-shift-date">{dateLabel(nextShift.work_date)}</p>
                <p className="dashboard-next-shift-meta">
                  {shiftLabel(nextShift)}
                  {nextShift.competence_name ? ` · ${nextShift.competence_name}` : ''}
                </p>
              </>
            ) : loading ? (
              <span className="skeleton dashboard-next-shift-skeleton" />
            ) : (
              <p className="dashboard-next-shift-empty">{t('dashboard.no_next_shift')}</p>
            )}
          </div>
        </article>

        <article className="card dashboard-card dashboard-stat">
          <p className="dashboard-card-label">{t('dashboard.planned_shifts')}</p>
          <strong className="dashboard-stat-value">
            {statValue(monthlyStatistics?.scheduled_shift_count)}
          </strong>
          <span className="dashboard-stat-hint">{t('dashboard.this_month')}</span>
        </article>

        <article className="card dashboard-card dashboard-stat">
          <p className="dashboard-card-label">{t('dashboard.worked_days')}</p>
          <strong className="dashboard-stat-value">
            {statValue(workedStatistics?.worked_day_count)}
          </strong>
          <span className="dashboard-stat-hint">{t('dashboard.until_today')}</span>
        </article>
      </section>

      <section className="card dashboard-calendar">
        <header className="card-header">
          <div>
            <h2 className="card-title">{t('dashboard.schedule_title')}</h2>
            <p className="card-subtitle">{monthLabel}</p>
          </div>
          <Link to="/schedule" className="btn btn-sm">
            {t('dashboard.open_schedule')}
            <ChevronRightIcon className="" />
          </Link>
        </header>
        <div className="dashboard-calendar-body">
          <ShiftCalendar
            year={view.year}
            month={view.month}
            shiftsByDate={shiftsByDate}
            labelFor={shiftLabel}
            today={today}
            loading={loading}
            label={t('dashboard.schedule_title')}
          />
        </div>
      </section>
    </div>
  );
};

export default DashboardView;
