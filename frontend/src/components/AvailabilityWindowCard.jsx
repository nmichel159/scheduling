import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  fetchAvailabilityWindow,
  saveAvailabilityWindow,
  setMonthLock,
} from '../services/availabilityService';
import { capitalizeFirst, localeFor } from '../utils/calendar';

/** Only whole days that exist in every month. */
const parseDay = (text) => {
  const value = Number(text);
  return Number.isInteger(value) && value >= 1 && value <= 28 ? value : null;
};

/**
 * The window in which employees fill in next month: the day the server
 * reminds them, the day the month closes, and the switch that closes or
 * opens it by hand.
 *
 * `onDaysSaved` lets the page refresh the message below, whose due date
 * follows the lock day.
 */
const AvailabilityWindowCard = ({ onDaysSaved }) => {
  const { t, i18n } = useTranslation();
  const [windowState, setWindowState] = useState(null);
  const [reminderDay, setReminderDay] = useState('');
  const [lockDay, setLockDay] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const adopt = useCallback((data) => {
    setWindowState(data);
    setReminderDay(String(data.reminder_day));
    setLockDay(String(data.lock_day));
  }, []);

  useEffect(() => {
    fetchAvailabilityWindow()
      .then(adopt)
      .catch(() => setError(t('availability_window.load_error')));
  }, [adopt, t]);

  const locale = localeFor(i18n.language);
  const formatDate = useCallback(
    (iso) =>
      new Intl.DateTimeFormat(locale, {
        day: 'numeric',
        month: 'numeric',
        year: 'numeric',
      }).format(new Date(`${iso}T00:00:00`)),
    [locale]
  );

  const upcoming = windowState?.upcoming;
  const monthLabel = useMemo(() => {
    if (!upcoming) return '';
    return capitalizeFirst(
      new Intl.DateTimeFormat(locale, { month: 'long', year: 'numeric' }).format(
        new Date(upcoming.year, upcoming.month - 1, 1)
      )
    );
  }, [upcoming, locale]);

  if (!windowState) {
    return error ? (
      <div className="alert alert-danger smail-alert" role="alert">
        {error}
      </div>
    ) : null;
  }

  const reminderValue = parseDay(reminderDay);
  const lockValue = parseDay(lockDay);
  const daysValid =
    reminderValue != null && lockValue != null && reminderValue < lockValue;
  const daysChanged =
    reminderValue !== windowState.reminder_day || lockValue !== windowState.lock_day;

  const saveDays = async () => {
    setBusy(true);
    setError(null);
    try {
      adopt(await saveAvailabilityWindow(reminderValue, lockValue));
      onDaysSaved?.();
    } catch {
      setError(t('availability_window.save_failed'));
    } finally {
      setBusy(false);
    }
  };

  const toggleLock = async () => {
    setBusy(true);
    setError(null);
    try {
      const status = await setMonthLock(upcoming.year, upcoming.month, !upcoming.locked);
      setWindowState((current) => ({ ...current, upcoming: status }));
    } catch {
      setError(t('availability_window.save_failed'));
    } finally {
      setBusy(false);
    }
  };

  const reminderState = upcoming.reminder_status
    ? t(`availability_window.reminder_status.${upcoming.reminder_status}`, {
        count: upcoming.reminder_recipients ?? 0,
      })
    : t('availability_window.reminder_status.planned');

  return (
    <section className="card smail-window" aria-labelledby="smail-window-title">
      <div className="card-header">
        <h2 id="smail-window-title" className="card-title">
          {t('availability_window.title', { month: monthLabel })}
        </h2>
        <span
          className={`badge ${upcoming.locked ? 'badge-danger' : 'badge-success'}`}
          aria-live="polite"
        >
          {upcoming.locked
            ? t('availability_window.locked')
            : t('availability_window.open')}
          {upcoming.manual != null && ` · ${t('availability_window.manual')}`}
        </span>
        <button
          type="button"
          className={`btn btn-sm smail-window-toggle ${
            upcoming.locked ? 'btn-secondary' : 'btn-danger-outline'
          }`}
          disabled={busy}
          onClick={toggleLock}
        >
          {upcoming.locked ? t('availability_window.unlock') : t('availability_window.lock')}
        </button>
      </div>

      <div className="card-pad smail-window-body">
        <dl className="smail-window-facts">
          <div>
            <dt>{t('availability_window.reminder')}</dt>
            <dd>
              {formatDate(upcoming.reminder_date)} · {reminderState}
            </dd>
          </div>
          <div>
            <dt>{t('availability_window.lock_date')}</dt>
            <dd>{formatDate(upcoming.lock_date)}</dd>
          </div>
        </dl>

        <div className="smail-window-days">
          <label className="field">
            <span className="field-label">{t('availability_window.reminder_day')}</span>
            <input
              type="number"
              className="input input-sm"
              min={1}
              max={27}
              inputMode="numeric"
              value={reminderDay}
              onChange={(event) => setReminderDay(event.target.value)}
            />
          </label>
          <label className="field">
            <span className="field-label">{t('availability_window.lock_day')}</span>
            <input
              type="number"
              className="input input-sm"
              min={2}
              max={28}
              inputMode="numeric"
              value={lockDay}
              onChange={(event) => setLockDay(event.target.value)}
            />
          </label>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={busy || !daysChanged || !daysValid}
            onClick={saveDays}
          >
            {t('availability_window.save')}
          </button>
        </div>

        {!daysValid && (
          <p className="field-error" role="alert">
            {t('availability_window.invalid_days')}
          </p>
        )}
        {error && (
          <div className="alert alert-danger" role="alert">
            {error}
          </div>
        )}
      </div>
    </section>
  );
};

export default AvailabilityWindowCard;
