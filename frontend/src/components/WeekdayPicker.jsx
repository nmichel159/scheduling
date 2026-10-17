import { useTranslation } from 'react-i18next';
import { WEEKDAY_ANSWER, weekdaysOf } from '../services/unavailabilityService';
import './WeekdayPicker.css';

/** The order one weekday walks through, one click at a time. */
const CYCLE = [WEEKDAY_ANSWER.ANY, WEEKDAY_ANSWER.WANT, WEEKDAY_ANSWER.AVOID];

/**
 * Seven weekday toggles, Monday first; a click walks a day through
 * "no opinion" → "want" → "rather not". Without `onChange` it only shows.
 *
 * `compact` is the table-cell size used on the workplace screen.
 */
const WeekdayPicker = ({ value, onChange, compact = false, label, disabled = false }) => {
  const { t } = useTranslation();
  const answers = weekdaysOf(value);
  const readOnly = !onChange;

  const toggle = (index) => {
    const next = [...answers];
    next[index] = CYCLE[(CYCLE.indexOf(answers[index]) + 1) % CYCLE.length];
    onChange(next);
  };

  return (
    <div
      className={`weekday-picker${compact ? ' is-compact' : ''}`}
      role="group"
      aria-label={label}
    >
      {answers.map((answer, index) => {
        const dayLabel = t(`workload.days.${index}`);
        const title = `${dayLabel}: ${t(`conditions.answer.${answer}`)}`;
        return readOnly ? (
          <span key={index} className={`weekday-chip is-${answer}`} title={title}>
            {dayLabel}
          </span>
        ) : (
          <button
            key={index}
            type="button"
            className={`weekday-chip is-${answer}`}
            title={title}
            aria-label={title}
            disabled={disabled}
            onClick={() => toggle(index)}
          >
            {dayLabel}
          </button>
        );
      })}
    </div>
  );
};

export default WeekdayPicker;
