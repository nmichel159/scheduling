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
 * Lives in the left column of the schedule editor, in place of the old
 * competence map — it is the same colour -> competence legend, with the
 * per-day head-counts laid out as a small seven-column table instead of
 * the wrapping text they used to be ("Po · Ut · St · Št · Pi 2 So · Ne 1"
 * under every entry, where nothing lined up between competences).
 *
 * It is sized to a ~260px rail, so every measurement here is deliberately
 * tight: the day columns are fixed-width and the name column takes what is
 * left, ellipsised with the full name on hover.
 *
 * Read-only on purpose: the numbers are part of the ambulance setup and
 * are edited in the competence matrix (Pracoviská), which keeps the
 * schedule screen's single save action about shifts alone.
 *
 * Props:
 * - competences: [{ id, name, description, color, weekday_requirements }] —
 *   already ordered and coloured by the caller's competence map, so the row
 *   order and the swatches match the calendar chips.
 * - emptyLabel: shown when the ambulance has no competences yet.
 */
const WEEKEND_DAYS = new Set([5, 6]);

const CompetenceCoverage = ({ competences, emptyLabel }) => {
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

  const dayName = (weekday) => t(`workload.days.${weekday}`);

  return (
    <section className="coverage">
      <span className="coverage-title" title={t('schedule_edit.coverage_hint')}>
        {t('schedule_edit.coverage_title')}
      </span>

      {rows.length === 0 ? (
        <p className="coverage-empty">{emptyLabel}</p>
      ) : (
        <table className="coverage-table">
          <caption className="coverage-caption">
            {t('schedule_edit.coverage_hint')}
          </caption>
          <thead>
            <tr>
              <th scope="col" className="coverage-corner">
                <span className="coverage-sr-only">
                  {t('schedule_edit.coverage_competence')}
                </span>
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
