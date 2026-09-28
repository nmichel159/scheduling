import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { buildMonthCells, isoDate } from '../utils/calendar';
import './ShiftCalendar.css';

/**
 * Read-only month grid of one employee's duties — the dashboard's current
 * month and the browsable "my schedule" screen are the same picture, so they
 * share it rather than keep two copies in step.
 *
 * Props:
 * - year, month (0-11)
 * - shiftsByDate: { 'YYYY-MM-DD': [shift, ...] } — a day can hold several
 * - labelFor(shift): the workplace name shown on a chip
 * - today: Date
 * - loading: dims the grid while a month is in flight
 * - label: accessible name of the grid
 */
const ShiftCalendar = ({ year, month, shiftsByDate, labelFor, today, loading, label }) => {
  const { t } = useTranslation();
  const cells = useMemo(() => buildMonthCells(year, month), [year, month]);
  const dayLabels = useMemo(
    () => [0, 1, 2, 3, 4, 5, 6].map((index) => t(`workload.days.${index}`)),
    [t]
  );
  const isCurrentMonth = year === today.getFullYear() && month === today.getMonth();

  return (
    <div
      className={`shiftcal ${loading ? 'is-loading' : ''}`}
      aria-busy={loading || undefined}
      aria-label={label}
      role="group"
    >
      <div className="shiftcal-head" aria-hidden="true">
        {dayLabels.map((dayLabel, index) => (
          <span key={dayLabel} className={index >= 5 ? 'is-weekend' : ''}>
            {dayLabel}
          </span>
        ))}
      </div>
      <div className="shiftcal-grid">
        {cells.map((day, index) => {
          const weekend = index % 7 >= 5 ? ' is-weekend' : '';
          if (day == null) {
            return <div key={`blank-${index}`} className={`shiftcal-cell is-blank${weekend}`} />;
          }
          const date = isoDate(year, month, day);
          const shifts = shiftsByDate[date] || [];
          const isToday = isCurrentMonth && day === today.getDate();
          return (
            <div
              key={date}
              className={`shiftcal-cell${weekend}${isToday ? ' is-today' : ''}${
                shifts.length ? ' has-shift' : ''
              }`}
            >
              <span className="shiftcal-day" aria-current={isToday ? 'date' : undefined}>
                {day}
              </span>
              {shifts.map((shift) => {
                const name = labelFor(shift);
                return (
                  <span
                    key={shift.id}
                    className="shiftcal-shift"
                    title={shift.competence_name ? `${name} · ${shift.competence_name}` : name}
                  >
                    <span className="shiftcal-shift-name">{name}</span>
                    {shift.competence_name && (
                      <span className="shiftcal-shift-meta">{shift.competence_name}</span>
                    )}
                  </span>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default ShiftCalendar;
