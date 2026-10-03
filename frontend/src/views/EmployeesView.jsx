import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  fetchCompetences,
  fetchEmployeeCompetenceTable,
  saveEmployeeCompetenceTable,
} from '../services/competenceService';
import {
  fetchEmployeeLoad,
  saveEmployeeSettings,
} from '../services/employeeService';
import { useWorkplace } from '../hooks/workplaceContext';
import EmployeeDetailDialog from '../components/EmployeeDetailDialog';
import EmployeeAvailabilityDialog from '../components/EmployeeAvailabilityDialog';
import { ChevronLeftIcon, CloseIcon, LimitsIcon } from '../components/NavIcons';
import { compareNames } from '../utils/formatEmployeeName';
import { personInitials } from '../utils/personInitials';
import PeriodStepper from '../components/PeriodStepper';
import PageSkeleton, { SkeletonRows } from '../components/Skeleton';
import './EmployeesView.css';

/**
 * The scheduler's view of the people on one workplace.
 *
 * One list, one row per person, answering the three questions asked here
 * at once: who it is, what they are allowed to do, and how loaded they
 * already are in the shown month. The days themselves are the detail of
 * that load, so they live in the profile the row opens rather than in the
 * row, which keeps the count against the person's own monthly wish.
 *
 * Whether a duty is surcharged is decided on the backend from the selected
 * scenario and the special-day calendar, so these numbers are the ones the
 * generator worked with rather than a second opinion.
 *
 * Two things are editable from here, both through the profile: the
 * person's competences and their own preferences (the monthly duty wish
 * and which kind of duty suits them). The competence matrix on
 * /departments still edits the whole table at once; saving one person
 * here only touches that person's row.
 */

/** Zero-pad a number to two digits. */
const pad = (n) => String(n).padStart(2, '0');

/** Months since year zero, so two calendar months compare as numbers. */
const monthIndex = (year, month) => year * 12 + month;

/* Same bounds the schedule endpoints validate years against. */
const EARLIEST_MONTH_INDEX = monthIndex(2000, 0);
const LATEST_MONTH_INDEX = monthIndex(2100, 11);

/* How many competence chips a row prints before folding the rest into a
 * "+N" chip. Three keep a row on one line on a laptop; the profile the row
 * opens lists all of them. */
const VISIBLE_TAGS = 3;

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
  const [competenceFilter, setCompetenceFilter] = useState(null); // competence id
  const [sort, setSort] = useState('name'); // 'name' | 'load'
  const [detailId, setDetailId] = useState(null);
  const [availabilityId, setAvailabilityId] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(false);
  const [view, setView] = useState({ y: today.getFullYear(), m: today.getMonth() });
  // Only the newest month's answer may land: stepping through months
  // quickly would otherwise let a slower, older request win.
  const loadSeq = useRef(0);

  const viewMonthIndex = monthIndex(view.y, view.m);
  const isCurrentMonth =
    view.y === today.getFullYear() && view.m === today.getMonth();

  const loadData = useCallback(async () => {
    if (selectedId == null) return;
    const seq = ++loadSeq.current;
    setLoading(true);
    setLoadError(false);
    try {
      const [table, comps, monthly] = await Promise.all([
        fetchEmployeeCompetenceTable(selectedId),
        fetchCompetences(selectedId),
        fetchEmployeeLoad(selectedId, view.m + 1, view.y),
      ]);
      if (seq !== loadSeq.current) return;
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
      if (seq !== loadSeq.current) return;
      setEmployees([]);
      setCompetences([]);
      setLoad({});
      setLoadError(true);
    } finally {
      if (seq === loadSeq.current) setLoading(false);
    }
  }, [selectedId, view.m, view.y]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  /** The month's duties of one employee, oldest first. */
  const daysOf = useCallback(
    (userId) => (load[userId] && load[userId].days) || [],
    [load]
  );

  /**
   * One employee's counters, zeroed when the month holds nothing yet.
   *
   * The backend sends what only it can know — how the duties were valued
   * by the selected scenario, and how the person filled their
   * availability calendar. The rest is arithmetic on the day list, done
   * here so the screen can show it without a second request.
   */
  const statsOf = useCallback(
    (userId) => {
      const row = load[userId] || {};
      const days = row.days || [];
      const shifts = row.shift_count || 0;
      const surcharge = row.surcharge_shift_count || 0;
      const hours = row.total_hours || 0;
      const max = row.max_shifts_per_month;

      const weekend = days.filter((d) => {
        const day = new Date(`${d.work_date}T00:00:00`).getDay();
        return day === 0 || day === 6;
      }).length;

      /* The longest run of duties on consecutive calendar days — two
       * people with the same count are not equally worn out if one of
       * them worked their days back to back. */
      const dates = [...new Set(days.map((d) => d.work_date))].sort();
      let streak = 0;
      let run = 0;
      let previous = null;
      dates.forEach((iso) => {
        const at = new Date(`${iso}T00:00:00`);
        const consecutive =
          previous !== null && (at - previous) / 86400000 === 1;
        run = consecutive ? run + 1 : 1;
        if (run > streak) streak = run;
        previous = at;
      });

      return {
        shifts,
        surcharge,
        standard: shifts - surcharge,
        hours,
        weekend,
        streak,
        max,
        free: max != null ? max - shifts : null,
        avgHours: shifts > 0 ? Math.round((hours / shifts) * 10) / 10 : 0,
        preference: row.shift_preference || 'any',
        marked: row.marked_days || 0,
        preferred: row.preferred_days || 0,
        declined: row.declined_days || 0,
        blocked: row.blocked_days || 0,
      };
    },
    [load]
  );

  const locale = i18n.language === 'en' ? 'en-GB' : 'sk-SK';

  /* Name, e-mail and competence names are all searchable, so "kto vie
   * ultrazvuk" is one query away without leaving the list. Clicking a
   * competence chip in a row narrows the list the same way, except it
   * matches the competence itself rather than its name. */
  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase();
    let rows = employees;
    if (q) {
      rows = rows.filter(
        (e) =>
          (e.full_name || '').toLowerCase().includes(q) ||
          e.email.toLowerCase().includes(q) ||
          e.competences.some((c) => c.name.toLowerCase().includes(q))
      );
    }
    if (competenceFilter != null) {
      rows = rows.filter((e) => e.competences.some((c) => c.id === competenceFilter));
    }
    if (sort === 'load') {
      /* Busiest first; among people with the same number of duties the
       * one closer to their own monthly wish is the more interesting
       * one, so that is what ties fall back to. */
      rows = [...rows].sort((a, b) => {
        const sa = statsOf(a.user_id);
        const sb = statsOf(b.user_id);
        if (sb.shifts !== sa.shifts) return sb.shifts - sa.shifts;
        const fa = sa.max ? sa.shifts / sa.max : 0;
        const fb = sb.max ? sb.shifts / sb.max : 0;
        return fb - fa;
      });
    } else {
      rows = [...rows].sort((a, b) =>
        compareNames(a.full_name || a.email, b.full_name || b.email, locale)
      );
    }
    return rows;
  }, [employees, filter, competenceFilter, sort, statsOf, locale]);

  const monthLabel = useMemo(() => {
    const formatter = new Intl.DateTimeFormat(locale, { month: 'long', year: 'numeric' });
    return formatter.format(new Date(view.y, view.m, 1));
  }, [view.y, view.m, locale]);

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

  /**
   * Save the profile: the person's competences and their own preferences.
   *
   * The competence table endpoint replaces the rows of the users it is
   * given and leaves everyone else alone, so one person is sent here
   * rather than the whole table the matrix on /departments submits.
   */
  const handleSave = async ({ competence_ids: competenceIds, ...settings }) => {
    if (!detail || selectedId == null) return;
    setSaving(true);
    setSaveError(false);
    try {
      const before = detail.competences.map((c) => c.id);
      const changed =
        competenceIds.length !== before.length ||
        competenceIds.some((id) => !before.includes(id));
      if (changed) {
        const rows = await saveEmployeeCompetenceTable(selectedId, [
          { user_id: detail.user_id, competence_ids: competenceIds },
        ]);
        const row = rows.find((r) => r.user_id === detail.user_id);
        if (row) {
          setEmployees((prev) =>
            prev.map((e) =>
              e.user_id === detail.user_id
                ? {
                    ...e,
                    competences: row.competences.map((c) => ({
                      id: c.id,
                      name: c.name,
                    })),
                  }
                : e
            )
          );
        }
      }
      const saved = await saveEmployeeSettings(selectedId, detail.user_id, settings);
      setLoad((prev) => ({
        ...prev,
        [detail.user_id]: { ...(prev[detail.user_id] || {}), ...saved },
      }));
      setDetailId(null);
    } catch {
      /* Said inside the dialog, which stays open with the edit in it —
       * not as the page's "could not load" banner behind the overlay. */
      setSaveError(true);
    } finally {
      setSaving(false);
    }
  };

  const openDetail = (userId) => {
    setSaveError(false);
    setDetailId(userId);
  };

  if (workplacesLoading) {
    return (
      <PageSkeleton
        className="page employees"
        title={t('employees.title')}
        label={t('departments.loading')}
      />
    );
  }

  if (forbidden || workplaces.length === 0) {
    return (
      <div className="page employees">
        <header className="page-header">
          <h1 className="page-title">{t('employees.title')}</h1>
        </header>
        <div className="alert alert-info">
          {forbidden ? t('departments.forbidden') : t('departments.no_ambulances')}
        </div>
      </div>
    );
  }

  const activeCompetence = competences.find((c) => c.id === competenceFilter) || null;

  return (
    <div className="page employees">
      <header className="page-header">
        <div className="employees-heading">
          <h1 className="page-title">{t('employees.title')}</h1>
          <p className="page-subtitle">
            <span className="employees-workplace">{selected?.name}</span>
            <span className="employees-count">
              {t('departments.employee_count', { count: employees.length })}
            </span>
          </p>
        </div>

        {/* The month is what every number in the list is about, so it
          * stands at the page level rather than among the list's filters. */}
        <div className="page-actions">
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

      {(workplacesError || loadError) && (
        <div className="alert alert-danger employees-alert" role="alert">
          {t('departments.load_error')}
          <button type="button" className="alert-action" onClick={loadData}>
            {t('employees.retry')}
          </button>
        </div>
      )}

      <section className="card employees-card">
        <div className="employees-toolbar">
          <div className="employees-filter">
            <input
              type="text"
              className="input search-input"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape' && filter) setFilter('');
              }}
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
                <CloseIcon className="icon-sm" />
              </button>
            )}
          </div>

          {activeCompetence && (
            <button
              type="button"
              className="employees-activefilter"
              onClick={() => setCompetenceFilter(null)}
              title={t('competences.clear_filter')}
              aria-label={`${t('competences.clear_filter')}: ${activeCompetence.name}`}
            >
              {activeCompetence.name}
              <CloseIcon className="employees-activefilter-icon" />
            </button>
          )}

          <div
            className="segmented employees-sort"
            role="group"
            aria-label={t('employees.sort')}
          >
            <button
              type="button"
              onClick={() => setSort('name')}
              aria-pressed={sort === 'name'}
            >
              {t('employees.sort_name')}
            </button>
            <button
              type="button"
              onClick={() => setSort('load')}
              aria-pressed={sort === 'load'}
            >
              {t('employees.sort_load')}
            </button>
          </div>
        </div>

        <div className={`employees-list ${loading ? 'is-loading' : ''}`.trim()}>
          {visible.length === 0 && loading ? (
            <SkeletonRows label={t('departments.loading')} />
          ) : visible.length === 0 ? (
            <p className="empty-state">
              {employees.length > 0
                ? t('competences.no_filter_match')
                : t('departments.no_employees')}
            </p>
          ) : (
            <>
              {/* One template for the legend and the rows, so every label
                * stands over the numbers it names. */}
              <div className="employees-legend" aria-hidden="true">
                <span className="employees-legend-person">{t('competences.employee')}</span>
                <span className="employees-legend-tags">{t('competences.title')}</span>
                <span className="employees-stats">
                  <span className="employees-cell">{t('employees.stat_shifts')}</span>
                  <span className="employees-cell">{t('employees.stat_surcharge')}</span>
                  <span className="employees-cell">{t('employees.stat_weekend')}</span>
                  <span className="employees-cell">{t('employees.stat_hours')}</span>
                  <span className="employees-cell">{t('employees.stat_marked')}</span>
                </span>
              </div>
              <ul className="employees-rows">
                {visible.map((e) => {
                  const stats = statsOf(e.user_id);
                  const name = e.full_name || e.email;
                  const fill = stats.max > 0 ? Math.min(1, stats.shifts / stats.max) : 0;
                  let meterState = '';
                  if (!stats.max) meterState = 'is-open';
                  else if (stats.shifts > stats.max) meterState = 'is-over';
                  else if (stats.shifts === stats.max) meterState = 'is-full';
                  /* The chip the list is narrowed to goes first, so it is
                   * never the one folded into "+N". */
                  const tags =
                    competenceFilter == null
                      ? e.competences
                      : [
                          ...e.competences.filter((c) => c.id === competenceFilter),
                          ...e.competences.filter((c) => c.id !== competenceFilter),
                        ];
                  const shownTags = tags.slice(0, VISIBLE_TAGS);
                  const hiddenTags = tags.slice(VISIBLE_TAGS);
                  return (
                    <li key={e.user_id} className="employees-item">
                      {/* The overlay is the row's button, so a click anywhere
                        * that is not a competence chip opens the profile —
                        * the chips sit above it and filter instead. */}
                      <button
                        type="button"
                        className="employees-open"
                        onClick={() => openDetail(e.user_id)}
                        aria-label={`${name} — ${t('competences.employee_detail')}`}
                      />
                      <div className="employees-row">
                        <span className="employees-avatar" aria-hidden="true">
                          {personInitials(name)}
                        </span>
                        <span className="employees-identity">
                          <span className="employees-name" title={name}>
                            {name}
                          </span>
                          {e.full_name && (
                            <span className="employees-email" title={e.email}>
                              {e.email}
                            </span>
                          )}
                        </span>

                        <span className="employees-tags">
                          {e.competences.length === 0 ? (
                            <span className="employees-tag is-empty">
                              {t('employees.no_competences')}
                            </span>
                          ) : (
                            shownTags.map((c) => (
                              <button
                                key={c.id}
                                type="button"
                                className={`employees-tag ${
                                  competenceFilter === c.id ? 'is-picked' : ''
                                }`.trim()}
                                onClick={() =>
                                  setCompetenceFilter((prev) =>
                                    prev === c.id ? null : c.id
                                  )
                                }
                                aria-pressed={competenceFilter === c.id}
                              >
                                {c.name}
                              </button>
                            ))
                          )}
                          {hiddenTags.length > 0 && (
                            <span
                              className="employees-tag is-more"
                              title={hiddenTags.map((c) => c.name).join(', ')}
                            >
                              +{hiddenTags.length}
                            </span>
                          )}
                        </span>

                        {/* The column labels are printed once above the list
                          * (and beside each number on a phone); every cell
                          * also repeats its full label in `title`. */}
                        <span className="employees-stats">
                          <span
                            className={`employees-cell employees-meter ${meterState}`.trim()}
                            title={t('employees.stat_shifts_full')}
                            data-label={t('employees.stat_shifts')}
                          >
                            <span className="employees-meter-value">
                              {stats.shifts}
                              {stats.max != null && (
                                <span className="employees-meter-max">/{stats.max}</span>
                              )}
                            </span>
                            <span className="employees-meter-track" aria-hidden="true">
                              <span
                                className="employees-meter-fill"
                                style={{ width: `${Math.round(fill * 100)}%` }}
                              />
                            </span>
                          </span>

                          <span
                            className={`employees-cell ${
                              stats.surcharge > 0 ? 'is-accent' : 'is-muted'
                            }`}
                            title={t('employees.stat_surcharge_full')}
                            data-label={t('employees.stat_surcharge')}
                          >
                            {stats.surcharge}
                          </span>
                          <span
                            className={`employees-cell ${stats.weekend === 0 ? 'is-muted' : ''}`.trim()}
                            title={t('employees.stat_weekend_full')}
                            data-label={t('employees.stat_weekend')}
                          >
                            {stats.weekend}
                          </span>
                          <span
                            className={`employees-cell ${stats.hours === 0 ? 'is-muted' : ''}`.trim()}
                            title={t('employees.stat_hours_full')}
                            data-label={t('employees.stat_hours')}
                          >
                            {stats.hours}
                          </span>
                          <span
                            className={`employees-cell ${stats.marked === 0 ? 'is-muted' : ''}`.trim()}
                            title={t('employees.stat_marked_breakdown', {
                              preferred: stats.preferred,
                              declined: stats.declined,
                              blocked: stats.blocked,
                            })}
                            data-label={t('employees.stat_marked')}
                          >
                            {stats.marked}
                          </span>
                        </span>

                        {/* Its own button rather than a second click
                          * target inside the profile: the calendar writes
                          * every click straight through, so it must not
                          * sit behind an unsaved form. */}
                        <button
                          type="button"
                          className="btn btn-ghost btn-icon btn-sm employees-calendar"
                          onClick={() => setAvailabilityId(e.user_id)}
                          title={t('employees.availability')}
                          aria-label={`${name} — ${t('employees.availability')}`}
                        >
                          <LimitsIcon />
                        </button>

                        <ChevronLeftIcon className="employees-chevron" />
                      </div>
                    </li>
                  );
                })}
              </ul>
            </>
          )}
        </div>
      </section>

      <EmployeeDetailDialog
        key={detailId ?? 'none'}
        employee={detail}
        competences={detail ? detail.competences : []}
        allCompetences={competences}
        days={detail ? daysOf(detail.user_id) : []}
        monthLabel={monthLabel}
        daysInMonth={new Date(view.y, view.m + 1, 0).getDate()}
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
        stats={detail ? statsOf(detail.user_id) : null}
        formatDay={(d) =>
          `${Number(d.work_date.slice(8, 10))}.${pad(Number(d.work_date.slice(5, 7)))}.`
        }
        saving={saving}
        error={saveError ? t('departments.save_error') : null}
        onSave={handleSave}
        onClose={() => setDetailId(null)}
      />

      <EmployeeAvailabilityDialog
        key={`cal-${availabilityId ?? 'none'}`}
        employee={employees.find((e) => e.user_id === availabilityId) || null}
        ambulanceId={selectedId}
        onClose={() => {
          setAvailabilityId(null);
          /* The month's filled-in count is what the list shows, and the
           * calendar has just been writing to it. */
          loadData();
        }}
      />
    </div>
  );
};

export default EmployeesView;
