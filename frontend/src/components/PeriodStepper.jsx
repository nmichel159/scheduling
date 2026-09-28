import { ChevronLeftIcon, ChevronRightIcon } from './NavIcons';
import { capitalizeFirst } from '../utils/calendar';
import './PeriodStepper.css';

/**
 * "‹ september 2026 ›" — the one control every month or year screen pages
 * with, so the calendars, the overview and the statistics all step the same
 * way and look the same doing it.
 *
 * Props:
 * - label: the period on screen; its first letter is upper-cased
 * - onPrevious / onNext, previousLabel / nextLabel (accessible names)
 * - previousDisabled / nextDisabled, or disabled for both arrows and "today"
 * - todayLabel + onToday: a way back to the running period. The caller
 *   passes them only while the view has wandered off it.
 * - unit: 'month' (default) or 'year' — sizes the label so the arrows do not
 *   move when a longer month name comes round
 * - groupLabel: accessible name of the whole control
 */
const PeriodStepper = ({
  label,
  onPrevious,
  onNext,
  previousLabel,
  nextLabel,
  previousDisabled = false,
  nextDisabled = false,
  disabled = false,
  todayLabel,
  onToday,
  unit = 'month',
  groupLabel,
}) => (
  <div className={`period-stepper is-${unit}`}>
    {todayLabel && onToday && (
      <button type="button" className="btn" onClick={onToday} disabled={disabled}>
        {todayLabel}
      </button>
    )}
    <div className="period-stepper-control" role="group" aria-label={groupLabel}>
      <button
        type="button"
        className="period-stepper-arrow"
        onClick={onPrevious}
        disabled={disabled || previousDisabled}
        aria-label={previousLabel}
        title={previousLabel}
      >
        <ChevronLeftIcon className="" />
      </button>
      <span className="period-stepper-label" aria-live="polite">
        {capitalizeFirst(String(label))}
      </span>
      <button
        type="button"
        className="period-stepper-arrow"
        onClick={onNext}
        disabled={disabled || nextDisabled}
        aria-label={nextLabel}
        title={nextLabel}
      >
        <ChevronRightIcon className="" />
      </button>
    </div>
  </div>
);

export default PeriodStepper;
