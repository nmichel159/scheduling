import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ISO_WEEKDAYS,
  normalizeWeekdayRequirements,
} from '../utils/competenceRequirements';
import './CompetenceCoverage.css';

/**
 * Weekly staffing demand of one ambulance: how many people of each
 * competence the workplace needs on each day of the week.
 *
 * This is the reference the manager checks against while generating or
 * editing a month — it is the target the solver is given, not what the
 * month currently contains. It is read-only here on purpose: the numbers
 * are part of the ambulance setup and are edited in the competence matrix
 * (Pracoviská), so the schedule screen can keep its single save action
 * for shifts alone.
 *
 * Laid out as a real table, one row per competence and one column per
 * weekday, because that is the only arrangement in which "how many people
 * of which competence on this day" is a single glance down a column. The
 * previous inline form ("Po · Ut · St · Št · Pi 2 So · Ne 1" per legend
 * entry) packed the same numbers into wrapping prose in a 240px sidebar,
 * where nothing lined up between competences.
 *
 * Props:
 * - competences: [{ id, name, description, color, weekday_requirements }] —
 *   already ordered and colored by the caller's competence map, so the row
 *   order and the swatches match the calendar chips and the legend.
 * - collapsed / onToggle: the panel sits above the calendar, so it can be
 *   folded away to a single title row when the numbers are settled.
 */
const WEEKEND_DAYS = new Set([5, 6]);

const CompetenceCoverage = ({ competences, collapsed, onToggle }) => {
  const { t } = useTranslation();

  /* Index by weekday: normalizeWeekdayRequirements always returns all seven
     days in ISO order, so position === weekday and a missing per-day record
     falls back to the competence's legacy flat count. */
  const rows = useMemo(
    () =>
      competences.map((competence) => ({
        ...competence,
        counts: normalizeWeekdayRequirements(competence).map(
          (item) => item.required_count
        ),
      })),
    [competences]
  );

  const totals = useMemo(
    () =>
      ISO_WEEKDAYS.map((weekday) =>
        rows.reduce((sum, row) => sum + row.counts[weekday], 0)
      ),
    [rows]
  );

  if (rows.length === 0) return null;

  const dayName = (weekday) => t(`workload.days.${weekday}`);

  return (
    <section className={`coverage ${collapsed ? 'is-collapsed' : ''}`}>
      <div className="coverage-head">
        <div className="coverage-head-text">
          <h2 className="coverage-title">{t('schedule_edit.coverage_title')}</h2>
          <p className="coverage-hint">{t('schedule_edit.coverage_hint')}</p>
        </div>
        <button
          type="button"
          className="coverage-toggle"
          onClick={onToggle}
          aria-expanded={!collapsed}
          title={
            collapsed
              ? t('schedule_edit.coverage_expand')
              : t('schedule_edit.coverage_collapse')
          }
        >
          {collapsed
            ? t('schedule_edit.coverage_expand')
            : t('schedule_edit.coverage_collapse')}
        </button>
      </div>

      {!collapsed && (
        <table className="coverage-table">
          <caption className="coverage-caption">
            {t('schedule_edit.coverage_title')}
          </caption>
          <thead>
            <tr>
              <th scope="col" className="coverage-corner">
                {t('schedule_edit.coverage_competence')}
              </th>
              {ISO_WEEKDAYS.map((weekday) => (
                <th
                  key={weekday}
                  scope="col"
                  className={`coverage-dayhead ${
                    WEEKEND_DAYS.has(weekday) ? 'is-weekend' : ''
                  }`}
                >
                  {dayName(weekday)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <th scope="row" className="coverage-name">
                  {/* The flex box has to sit inside the cell, not be the cell:
                      a display:flex on the <th> itself drops it out of the
                      table's column layout and the names stop lining up. */}
                  <span className="coverage-name-inner">
                    <span
                      className="coverage-swatch"
                      style={{ backgroundColor: row.color }}
                      aria-hidden="true"
                    />
                    <span
                      className="coverage-name-text"
                      title={row.description || row.name}
                    >
                      {row.name}
                    </span>
                  </span>
                </th>
                {ISO_WEEKDAYS.map((weekday) => {
                  const count = row.counts[weekday];
                  return (
                    <td
                      key={weekday}
                      className={`coverage-cell ${
                        WEEKEND_DAYS.has(weekday) ? 'is-weekend' : ''
                      } ${count === 0 ? 'is-zero' : ''}`}
                      /* `people`, not `count`: the latter is i18next's
                         pluralisation key and would send the lookup to
                         suffixed variants this project does not define. */
                      title={t('schedule_edit.coverage_cell', {
                        people: count,
                        competence: row.name,
                        day: dayName(weekday),
                      })}
                    >
                      {/* A dash rather than a 0: days the competence is not
                          needed should recede so the staffed days stand out. */}
                      {count > 0 ? count : <span aria-hidden="true">–</span>}
                      {count === 0 && (
                        <span className="coverage-sr-only">0</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row" className="coverage-name coverage-total-name">
                {t('schedule_edit.coverage_total')}
              </th>
              {ISO_WEEKDAYS.map((weekday) => (
                <td
                  key={weekday}
                  className={`coverage-cell coverage-total-cell ${
                    WEEKEND_DAYS.has(weekday) ? 'is-weekend' : ''
                  }`}
                >
                  {totals[weekday]}
                </td>
              ))}
            </tr>
          </tfoot>
        </table>
      )}
    </section>
  );
};

export default CompetenceCoverage;
