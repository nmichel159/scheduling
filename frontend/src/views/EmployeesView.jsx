import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  fetchCompetences,
  fetchEmployeeCompetenceTable,
} from '../services/competenceService';
import {
  fetchEmployeeLoad,
  saveEmployeeSettings,
} from '../services/employeeService';
import { useWorkplace } from '../hooks/workplaceContext';
import EmployeeDetailDialog from '../components/EmployeeDetailDialog';
import { CoverageIcon, TeamScheduleIcon } from '../components/NavIcons';
import './EmployeesView.css';

/**
 * The scheduler's view of the people on one workplace.
 *
 * Two tabs over the same month, because the two questions asked here are
 * different: "rozvrh" shows which days each person actually got, and
 * "obsadenosť" counts them — how many duties, how many of them surcharged,
 * against the most the person wants. Both come from one response, so the
 * switch never refetches.
 *
 * Whether a duty is surcharged is decided on the backend from the selected
 * scenario and the special-day calendar, so these numbers are the ones the
 * generator worked with rather than a second opinion.
 *
 * Which workplace is shown comes from the header switcher, like everywhere
 * else. Competences stay read-only here — they are assigned in the matrix
 * on /departments, which is a draft with its own Save. What the row click
 * does edit is the person's own preferences: the monthly duty wish and
 * which kind of duty suits them.
 */

/** Zero-pad a number to two digits. */
const pad = (n) => String(n).padStart(2, '0');

/** Months since year zero, so two calendar months compare as numbers. */
const monthIndex = (year, month) => year * 12 + month;

/* Same bounds the schedule endpoints validate years against. */
const EARLIEST_MONTH_INDEX = monthIndex(2000, 0);
const LATEST_MONTH_INDEX = monthIndex(2100, 11);

const EmployeesView = () => {
  const { t, i18n } = useTranslation();
  const today = useMemo(() => new Date(), []);

  const {
    activeId: selectedId,
    active: selected,
    loading: workplacesLoading,
    error: workplacesError,
    forbidden,
    workplaces,
  } = useWorkplace();

  const [employees, setEmployees] = useState([]);
  const [competences, setCompetences] = useState([]);
  const [load, setLoad] = useState({}); // { user_id: load row }
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [filter, setFilter] = useState('');
  const [detailId, setDetailId] = useState(null);
  const [saving, setSaving] = useState(false);
  const [tab, setTab] = useState('schedule'); // 'schedule' | 'coverage'
  const [view, setView] = useState({ y: today.getFullYear(), m: today.getMonth() });

  const viewMonthIndex = monthIndex(view.y, view.m);
  const isCurrentMonth =
    view.y === today.getFullYear() && view.m === today.getMonth();

  const loadData = useCallback(async () => {
    if (selectedId == null) return;
    setLoading(true);
    setLoadError(false);
    try {
      const [table, comps, monthly] = await Promise.all([
        fetchEmployeeCompetenceTable(selectedId),
        fetchCompetences(selectedId),
        fetchEmployeeLoad(selectedId, view.m + 1, view.y),
      ]);
      setEmployees(
        table.map((row) => ({
          user_id: row.user_id,
          email: row.email,
          full_name: row.full_name,
          competences: row.competences.map((c) => ({ id: c.id, name: c.name })),
        }))
      );
      setCompetences(comps);
      const byId = {};
      (monthly.employees || []).forEach((row) => {
        byId[row.user_id] = row;
      });
      setLoad(byId);
    } catch {
      setEmployees([]);
      setCompetences([]);
      setLoad({});
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, [selectedId, view.m, view.y]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  /* Name, e-mail and competence names are all searchable, so "kto vie
   * ultrazvuk" is one query away without leaving the list. */
  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return employees;
    return employees.filter(
      (e) =>
        (e.full_name || '').toLowerCase().includes(q) ||
        e.email.toLowerCase().includes(q) ||
        e.competences.some((c) => c.name.toLowerCase().includes(q))
    );
  }, [employees, filter]);

  const monthLabel = useMemo(() => {
    const formatter = new Intl.DateTimeFormat(
      i18n.language === 'en' ? 'en-GB' : 'sk-SK',
      { month: 'long', year: 'numeric' }
    );
    return formatter.format(new Date(view.y, view.m, 1));
  }, [view.y, view.m, i18n.language]);

  /** Step by `offset` months, or jump back to the running month when null. */
  const changeMonth = (offset) => {
    if (offset === null) {
      setView({ y: today.getFullYear(), m: today.getMonth() });
      return;
    }
    const next = new Date(view.y, view.m + offset, 1);
    setView({ y: next.getFullYear(), m: next.getMonth() });
  };

  const detail = employees.find((e) => e.user_id === detailId) || null;
  const detailLoad = detail ? load[detail.user_id] : null;

  const handleSave = async (settings) => {
    if (!detail || selectedId == null) return;
    setSaving(true);
    try {
      const saved = await saveEmployeeSettings(selectedId, detail.user_id, settings);
      setLoad((prev) => ({
        ...prev,
        [detail.user_id]: { ...(prev[detail.user_id] || {}), ...saved },
      }));
      setDetailId(null);
    } catch {
      setLoadError(true);
    } finally {
      setSaving(false);
    }
  };

  if (workplacesLoading) {
    return (
      <div className="employees">
        <p>{t('departments.loading')}</p>
      </div>
    );
  }

  if (forbidden || workplaces.length === 0) {
    return (
      <div className="employees">
        <h1 className="employees-title">{t('employees.title')}</h1>
        <div className="employees-banner">
          {forbidden ? t('departments.forbidden') : t('departments.no_ambulances')}
        </div>
      </div>
    );
  }

  /** The month's duties of one employee, oldest first. */
  const daysOf = (userId) => (load[userId] && load[userId].days) || [];

  /** One employee's counters, zeroed when the month holds nothing yet. */
  const statsOf = (userId) => {
    const row = load[userId] || {};
    return {
      shifts: row.shift_count || 0,
      surcharge: row.surcharge_shift_count || 0,
      hours: row.total_hours || 0,
      max: row.max_shifts_per_month,
      preference: row.shift_preference || 'any',
    };
  };

  return (
    <div className="employees">
      <h1 className="employees-title">{t('employees.title')}</h1>

      {(workplacesError || loadError) && (
        <div className="employees-banner">{t('departments.load_error')}</div>
      )}

      <section className="employees-panel">
        <header className="employees-head">
          <div className="employees-heading">
            <h2 className="employees-workplace">{selected?.name}</h2>
            <span className="employees-count">
              {t('departments.employee_count', { count: employees.length })}
            </span>
          </div>

          <div
            className="employees-switch"
            role="group"
            aria-label={t('employees.view_switcher')}
          >
            <button
              type="button"
              className={`employees-switch-button ${tab === 'schedule' ? 'is-active' : ''}`}
              onClick={() => setTab('schedule')}
              aria-pressed={tab === 'schedule'}
            >
              <TeamScheduleIcon className="employees-switch-icon" />
              {t('employees.view_schedule')}
            </button>
            <button
              type="button"
              className={`employees-switch-button ${tab === 'coverage' ? 'is-active' : ''}`}
              onClick={() => setTab('coverage')}
              aria-pressed={tab === 'coverage'}
            >
              <CoverageIcon className="employees-switch-icon" />
              {t('employees.view_coverage')}
            </button>
          </div>

          <div className="employees-month">
            <button
              type="button"
              className="employees-month-button"
              onClick={() => changeMonth(-1)}
              disabled={viewMonthIndex <= EARLIEST_MONTH_INDEX}
              aria-label={t('schedule.previous_month')}
            >
              ‹
            </button>
            <span className="employees-monthlabel">{monthLabel}</span>
            <button
              type="button"
              className="employees-month-button"
              onClick={() => changeMonth(1)}
              disabled={viewMonthIndex >= LATEST_MONTH_INDEX}
              aria-label={t('schedule.next_month')}
            >
              ›
            </button>
            {!isCurrentMonth && (
              <button
                type="button"
                className="employees-month-today"
                onClick={() => changeMonth(null)}
              >
                {t('schedule.current_month')}
              </button>
            )}
          </div>

          <div className={`employees-filter ${filter ? 'is-active' : ''}`}>
            <span className="employees-filter-icon" aria-hidden="true">⌕</span>
            <input
              type="text"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder={t('employees.filter_placeholder')}
              aria-label={t('employees.filter_placeholder')}
            />
            {filter && (
              <button
                type="button"
                className="employees-filter-clear"
                onClick={() => setFilter('')}
                title={t('competences.clear_filter')}
                aria-label={t('competences.clear_filter')}
              >
                ✕
              </button>
            )}
          </div>
        </header>

        <div className={`employees-list ${loading ? 'is-loading' : ''}`}>
          {visible.length === 0 ? (
            <p className="employees-empty">
              {employees.length > 0
                ? t('competences.no_filter_match')
                : t('departments.no_employees')}
            </p>
          ) : (
            <ul className="employees-rows">
              {visible.map((e) => {
                const stats = statsOf(e.user_id);
                return (
                  <li key={e.user_id}>
                    {/* The whole row is the button — see the "clickable text =
                      * clickable field" rule in the README. */}
                    <button
                      type="button"
                      className="employees-row"
                      onClick={() => setDetailId(e.user_id)}
                      title={t('competences.employee_detail')}
                    >
                      <span className="employees-avatar" aria-hidden="true">
                        {(e.full_name || e.email).trim().charAt(0).toUpperCase()}
                      </span>
                      <span className="employees-identity">
                        <span className="employees-name">{e.full_name || e.email}</span>
                        <span className="employees-email">{e.email}</span>
                      </span>

                      {tab === 'schedule' ? (
                        <span className="employees-days">
                          {daysOf(e.user_id).length === 0 ? (
                            <span className="employees-tag is-empty">
                              {t('employees.no_shifts')}
                            </span>
                          ) : (
                            daysOf(e.user_id).map((d) => (
                              <span
                                key={`${d.work_date}-${d.competence_id}`}
                                className={`employees-day ${
                                  d.is_surcharge ? 'is-surcharge' : ''
                                }`}
                                title={`${d.work_date}${
                                  d.competence_name ? ` – ${d.competence_name}` : ''
                                }`}
                              >
                                {Number(d.work_date.slice(8, 10))}.
                                {pad(Number(d.work_date.slice(5, 7)))}.
                              </span>
                            ))
                          )}
                        </span>
                      ) : (
                        <span className="employees-stats">
                          <span className="employees-stat">
                            <span className="employees-stat-value">
                              {stats.max != null
                                ? `${stats.shifts} / ${stats.max}`
                                : stats.shifts}
                            </span>
                            <span className="employees-stat-label">
                              {t('employees.stat_shifts')}
                            </span>
                          </span>
                          <span className="employees-stat is-surcharge">
                            <span className="employees-stat-value">{stats.surcharge}</span>
                            <span className="employees-stat-label">
                              {t('employees.stat_surcharge')}
                            </span>
                          </span>
                          <span className="employees-stat">
                            <span className="employees-stat-value">{stats.hours}</span>
                            <span className="employees-stat-label">
                              {t('employees.stat_hours')}
                            </span>
                          </span>
                          <span className={`employees-pref is-${stats.preference}`}>
                            {t(`employees.preference_${stats.preference}`)}
                          </span>
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {competences.length > 0 && (
          <footer className="employees-foot">
            {t('employees.competence_count', { count: competences.length })}
          </footer>
        )}
      </section>

      <EmployeeDetailDialog
        key={detailId ?? 'none'}
        employee={detail}
        competences={detail ? detail.competences : []}
        settings={
          detail
            ? {
                max_shifts_per_month:
                  detailLoad && detailLoad.max_shifts_per_month != null
                    ? detailLoad.max_shifts_per_month
                    : null,
                shift_preference: (detailLoad && detailLoad.shift_preference) || 'any',
              }
            : null
        }
        saving={saving}
        onSave={handleSave}
        onClose={() => setDetailId(null)}
      />
    </div>
  );
};

export default EmployeesView;
