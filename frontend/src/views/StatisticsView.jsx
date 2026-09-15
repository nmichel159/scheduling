import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { fetchYearlyStatistics } from '../services/statisticsService';
import { fetchAllAmbulances } from '../services/ambulanceService';
import { formatShortName } from '../utils/formatEmployeeName';
import './StatisticsView.css';

/**
 * Hospital-wide yearly statistics for the analyst role (level 4).
 *
 * Reports duties and people — not hours. A schedule row carries a date but no
 * duration, so hours are not in the data model and cannot be derived without
 * inventing a shift length; competences whose *name* holds a time range
 * ("15:00-19:00") do not make that machine-readable either. Adding a duration
 * field to Competence is what would turn these counts into hours.
 *
 * Two numbers run through the whole page and must not be confused:
 * - *planned* — every duty dated in the year, future ones included.
 * - *worked*  — the subset dated on or before the report's `through_date`,
 *   which the backend clamps to the year, so a finished year stops moving.
 *
 * The same screen serves the whole hospital and one workplace: picking a
 * workplace re-scopes every panel server-side, so the monthly chart and the
 * people ranking then describe that workplace alone rather than its share of
 * the hospital. The comparison table only makes sense unscoped, and the
 * workplace-count tile means nothing for a single workplace, so both drop out.
 */

/** Bar height floor, so a month with duties never renders as nothing. */
const MIN_BAR_PERCENT = 3;

const percent = (part, whole) => (whole > 0 ? Math.round((part / whole) * 100) : 0);

const StatisticsView = () => {
  const { t, i18n } = useTranslation();
  const currentYear = useMemo(() => new Date().getFullYear(), []);

  const [year, setYear] = useState(currentYear);
  // null = the whole hospital; otherwise the ambulance every figure is scoped to.
  const [ambulanceId, setAmbulanceId] = useState(null);
  const [ambulances, setAmbulances] = useState([]);
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // The switcher's options come from the ambulance list, not from the report:
  // a scoped report only describes the one workplace it was asked about, so it
  // cannot offer the others to switch to.
  useEffect(() => {
    let cancelled = false;
    fetchAllAmbulances()
      .then((list) => {
        if (!cancelled) setAmbulances(list);
      })
      // A failed list only costs the switcher; the report itself still loads.
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const loadStatistics = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setReport(await fetchYearlyStatistics(year, ambulanceId));
    } catch {
      setReport(null);
      setError(t('statistics.load_error'));
    } finally {
      setLoading(false);
    }
  }, [ambulanceId, t, year]);

  useEffect(() => {
    loadStatistics();
  }, [loadStatistics]);

  const monthLabels = useMemo(() => {
    const formatter = new Intl.DateTimeFormat(
      i18n.language === 'en' ? 'en-GB' : 'sk-SK',
      { month: 'short' }
    );
    return Array.from({ length: 12 }, (_, index) =>
      formatter.format(new Date(2026, index, 1))
    );
  }, [i18n.language]);

  const throughLabel = useMemo(() => {
    if (!report?.through_date) return '';
    const formatter = new Intl.DateTimeFormat(
      i18n.language === 'en' ? 'en-GB' : 'sk-SK',
      { day: 'numeric', month: 'numeric', year: 'numeric' }
    );
    return formatter.format(new Date(`${report.through_date}T00:00:00`));
  }, [report, i18n.language]);

  // The tallest month sets the scale; without duties there is nothing to chart.
  const peakMonth = useMemo(
    () =>
      (report?.by_month || []).reduce(
        (peak, item) => Math.max(peak, item.shift_count),
        0
      ),
    [report]
  );

  // One decimal: the average is a rough fairness signal, and more digits
  // would suggest a precision the head count does not carry.
  const averagePerPerson =
    report && report.employee_count > 0
      ? Math.round((report.total_shift_count / report.employee_count) * 10) / 10
      : 0;

  const workplaces = report?.workplaces || [];
  // The busiest workplace sets the width of every load bar, so the rows are
  // comparable to each other rather than each filling its own cell.
  const peakWorkplace = workplaces.reduce(
    (peak, item) => Math.max(peak, item.shift_count),
    0
  );

  const changeYear = (offset) => setYear((current) => current + offset);

  return (
    <div className="stats">
      {error && <div className="stats-banner is-error">{error}</div>}

      <div className="stats-topbar">
        <div className="stats-year-navigation">
          <button
            type="button"
            className="stats-year-button"
            onClick={() => changeYear(-1)}
            disabled={loading}
            aria-label={t('statistics.previous_year')}
          >
            &#8249;
          </button>
          <span className="stats-year">{year}</span>
          <button
            type="button"
            className="stats-year-button"
            onClick={() => changeYear(1)}
            disabled={loading}
            aria-label={t('statistics.next_year')}
          >
            &#8250;
          </button>
          {year !== currentYear && (
            <button
              type="button"
              className="stats-year-today"
              onClick={() => setYear(currentYear)}
              disabled={loading}
            >
              {t('statistics.current_year')}
            </button>
          )}
        </div>
        {ambulances.length > 0 && (
          <label className="stats-scope">
            <span className="stats-sr-only">{t('statistics.scope')}</span>
            <select
              className="stats-scope-select"
              value={ambulanceId ?? ''}
              onChange={(e) =>
                setAmbulanceId(e.target.value === '' ? null : Number(e.target.value))
              }
              disabled={loading}
            >
              <option value="">{t('statistics.scope_all')}</option>
              {ambulances.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
        )}

        {report && (
          <span className="stats-through">
            {t('statistics.through', { date: throughLabel })}
          </span>
        )}
      </div>

      {!report ? (
        <p className="stats-empty">
          {loading ? t('statistics.loading') : t('statistics.no_data')}
        </p>
      ) : (
        <div className={`stats-body ${loading ? 'is-loading' : ''}`}>
          {/* --- headline numbers --- */}
          <section className="stats-kpis">
            <article className="stats-kpi">
              <span className="stats-kpi-value">{report.worked_shift_count}</span>
              <span className="stats-kpi-label">{t('statistics.kpi_worked')}</span>
            </article>
            <article className="stats-kpi">
              <span className="stats-kpi-value">{averagePerPerson}</span>
              <span className="stats-kpi-label">{t('statistics.kpi_average')}</span>
            </article>
            {ambulanceId === null && (
              <article className="stats-kpi">
                <span className="stats-kpi-value">
                  {report.staffed_workplace_count}
                  <span className="stats-kpi-of">/{report.workplace_count}</span>
                </span>
                <span className="stats-kpi-label">
                  {t('statistics.kpi_workplaces')}
                </span>
              </article>
            )}
          </section>

          {/* --- duties per month --- */}
          <section className="stats-card">
            <h2 className="stats-card-title">{t('statistics.by_month_title')}</h2>
            {peakMonth === 0 ? (
              <p className="stats-card-empty">{t('statistics.no_data')}</p>
            ) : (
              <div className="stats-chart">
                {report.by_month.map((item, index) => {
                  const planned = item.shift_count;
                  const worked = item.worked_shift_count;
                  return (
                    <div
                      className="stats-chart-col"
                      key={item.month}
                      title={t('statistics.month_tooltip', {
                        month: monthLabels[index],
                        planned,
                        worked,
                      })}
                    >
                      <span className="stats-chart-value">
                        {planned > 0 ? planned : ''}
                      </span>
                      <div className="stats-chart-track">
                        {/* One bar for what is planned, an inner fill for the
                            part already worked — the same two numbers as the
                            KPI row, so the year reads at a glance. */}
                        <div
                          className="stats-chart-bar"
                          style={{
                            height:
                              planned > 0
                                ? `${Math.max(
                                    MIN_BAR_PERCENT,
                                    (planned / peakMonth) * 100
                                  )}%`
                                : 0,
                          }}
                        >
                          <div
                            className="stats-chart-worked"
                            style={{ height: `${percent(worked, planned)}%` }}
                          />
                        </div>
                      </div>
                      <span className="stats-chart-label">{monthLabels[index]}</span>
                    </div>
                  );
                })}
              </div>
            )}
            <p className="stats-legend">
              <span className="stats-legend-item">
                <span className="stats-swatch is-worked" />
                {t('statistics.legend_worked')}
              </span>
              <span className="stats-legend-item">
                <span className="stats-swatch is-planned" />
                {t('statistics.legend_planned')}
              </span>
            </p>
          </section>

          {/* --- per workplace: a comparison, so only when unscoped --- */}
          {ambulanceId === null && (
            <section className="stats-card">
              <h2 className="stats-card-title">
                {t('statistics.by_workplace_title')}
              </h2>
              <div className="stats-scroll">
                <table className="stats-table">
                  <thead>
                    <tr>
                      <th scope="col">{t('statistics.workplace')}</th>
                      <th scope="col" className="stats-num">
                        {t('statistics.worked')}
                      </th>
                      <th scope="col" className="stats-num">
                        {t('statistics.planned')}
                      </th>
                      <th scope="col" className="stats-num">
                        {t('statistics.people')}
                      </th>
                      <th scope="col" className="stats-load">
                        {t('statistics.load')}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {workplaces.map((item) => (
                      <tr
                        key={item.ambulance_id}
                        className={item.shift_count === 0 ? 'is-idle' : ''}
                      >
                        <th scope="row" className="stats-name">
                          {item.ambulance_name}
                        </th>
                        <td className="stats-num">{item.worked_shift_count}</td>
                        <td className="stats-num">{item.shift_count}</td>
                        <td className="stats-num">{item.employee_count}</td>
                        <td className="stats-load">
                          <div className="stats-load-track">
                            <div
                              className="stats-load-bar"
                              style={{
                                width: `${percent(item.shift_count, peakWorkplace)}%`,
                              }}
                            />
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {/* --- busiest people --- */}
          {report.employees.length > 0 && (
            <section className="stats-card">
              <h2 className="stats-card-title">
                {t('statistics.by_employee_title')}
              </h2>
              <div className="stats-scroll">
                <table className="stats-table">
                  <thead>
                    <tr>
                      <th scope="col">{t('statistics.employee')}</th>
                      <th scope="col" className="stats-num">
                        {t('statistics.worked')}
                      </th>
                      <th scope="col" className="stats-num">
                        {t('statistics.planned')}
                      </th>
                      <th scope="col" className="stats-num">
                        {t('statistics.workplaces')}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.employees.map((item) => (
                      <tr key={item.user_id}>
                        <th scope="row" className="stats-name" title={item.email}>
                          {formatShortName(item.full_name) || item.email}
                        </th>
                        <td className="stats-num">{item.worked_shift_count}</td>
                        <td className="stats-num">{item.shift_count}</td>
                        <td className="stats-num">{item.ambulance_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

        </div>
      )}
    </div>
  );
};

export default StatisticsView;
