import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { fetchCompetenceNeeds, setCustomDayDate } from '../services/competenceService';
import PeriodStepper from './PeriodStepper';
import { CheckIcon } from './NavIcons';
import { isoWeekday, localeFor } from '../utils/calendar';
import { clampShiftHours } from '../utils/competenceRequirements';
import { customDayHues, hueStyle } from '../utils/customDays';
import './CompetenceMonthNeeds.css';

/** Round hours for display without trailing zeros. */
const formatHours = (hours) => String(Math.round(hours * 10) / 10);

const PICKER_WIDTH = 240;

/**
 * The month as the generator will staff it: for every date, how many people
 * each competence needs, from a custom day, the day of rest or the weekday
 * of the scenario it is read from. A date's header opens a picker that
 * places it on one of the workplace's custom days or hands it back to the
 * calendar.
 *
 * Props:
 * - ambulanceId, scenario ({ id, name, is_selected })
 * - competences: [{ id, name }] in display order
 * - customDays: the workplace's custom days
 * - reloadKey: changes whenever the numbers were edited
 * - onDatesChanged(): a date was placed or handed back
 * - notify(message)
 */
const CompetenceMonthNeeds = ({
  ambulanceId,
  scenario,
  competences,
  customDays,
  reloadKey,
  onDatesChanged,
  notify,
}) => {
  const scenarioId = scenario?.id ?? null;
  const { t, i18n } = useTranslation();
  const locale = localeFor(i18n.language);
  const today = useMemo(() => new Date(), []);
  const [view, setView] = useState({ y: today.getFullYear(), m: today.getMonth() });
  const [needs, setNeeds] = useState(null);
  const [loading, setLoading] = useState(false);
  const [picker, setPicker] = useState(null); // { day, rect }
  const pickerRef = useRef(null);
  const seq = useRef(0);

  const loadNeeds = useCallback(async () => {
    const current = ++seq.current;
    if (ambulanceId == null || scenarioId == null) {
      setNeeds(null);
      return;
    }
    setLoading(true);
    try {
      const data = await fetchCompetenceNeeds(ambulanceId, view.y, view.m + 1, scenarioId);
      if (current === seq.current) setNeeds(data);
    } catch {
      if (current === seq.current) {
        setNeeds(null);
        notify(t('custom_days.load_error'));
      }
    } finally {
      if (current === seq.current) setLoading(false);
    }
  }, [ambulanceId, scenarioId, view.y, view.m, notify, t]);

  useEffect(() => {
    loadNeeds();
  }, [loadNeeds, reloadKey]);

  // The picker floats over the table; anything outside it closes it.
  useEffect(() => {
    if (!picker) return undefined;
    const handleDown = (e) => {
      if (pickerRef.current?.contains(e.target)) return;
      if (e.target.closest?.('.cneeds-day')) return;
      setPicker(null);
    };
    const handleKey = (e) => {
      if (e.key === 'Escape') setPicker(null);
    };
    const close = () => setPicker(null);
    document.addEventListener('mousedown', handleDown);
    window.addEventListener('keydown', handleKey);
    window.addEventListener('resize', close);
    return () => {
      document.removeEventListener('mousedown', handleDown);
      window.removeEventListener('keydown', handleKey);
      window.removeEventListener('resize', close);
    };
  }, [picker]);

  const [pickerPos, setPickerPos] = useState(null);
  useLayoutEffect(() => {
    if (!picker) {
      setPickerPos(null);
      return;
    }
    const { rect } = picker;
    const height = pickerRef.current?.offsetHeight ?? 0;
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - PICKER_WIDTH - 8));
    const below = rect.bottom + 4;
    const top = below + height > window.innerHeight - 8 ? Math.max(8, rect.top - height - 4) : below;
    setPickerPos({ left, top });
  }, [picker]);

  const hueById = useMemo(() => customDayHues(customDays), [customDays]);

  const customById = useMemo(
    () => new Map(customDays.map((item) => [item.id, item])),
    [customDays]
  );

  const monthLabel = useMemo(
    () =>
      new Intl.DateTimeFormat(locale, { month: 'long', year: 'numeric' }).format(
        new Date(view.y, view.m, 1)
      ),
    [view.y, view.m, locale]
  );

  const isCurrentMonth = view.y === today.getFullYear() && view.m === today.getMonth();

  const changeMonth = (offset) => {
    setPicker(null);
    if (offset === null) {
      setView({ y: today.getFullYear(), m: today.getMonth() });
      return;
    }
    const next = new Date(view.y, view.m + offset, 1);
    setView({ y: next.getFullYear(), m: next.getMonth() });
  };

  const days = useMemo(
    () =>
      (needs?.days || []).map((item) => {
        const date = new Date(`${item.day}T00:00:00`);
        const weekday = isoWeekday(date);
        return {
          ...item,
          date,
          weekday,
          dayNumber: date.getDate(),
          needsById: new Map(item.needs.map((need) => [need.competence_id, need])),
        };
      }),
    [needs]
  );

  const totals = useMemo(() => {
    const byCompetence = new Map();
    const byDay = new Map();
    let duties = 0;
    let hours = 0;
    days.forEach((day) => {
      let dayCount = 0;
      day.needs.forEach((need) => {
        const entry = byCompetence.get(need.competence_id) || { duties: 0, hours: 0 };
        entry.duties += need.required_count;
        entry.hours += need.required_count * need.shift_hours;
        byCompetence.set(need.competence_id, entry);
        dayCount += need.required_count;
        duties += need.required_count;
        hours += need.required_count * need.shift_hours;
      });
      byDay.set(day.day, dayCount);
    });
    return { byCompetence, byDay, duties, hours };
  }, [days]);

  /** Name of what a date is staffed as, for its header's title. */
  const dayKindLabel = (day) => {
    if (day.kind === 'custom') return customById.get(day.custom_day_id)?.name ?? '';
    if (day.kind === 'rest') return t('special_days.column_short');
    return t(`workload.days.${day.weekday}`);
  };

  const placeDate = async (dateStr, customDayId) => {
    setPicker(null);
    try {
      await setCustomDayDate(ambulanceId, dateStr, customDayId);
      await loadNeeds();
      onDatesChanged?.();
    } catch {
      notify(t('custom_days.save_error'));
    }
  };

  const pickedDay = picker ? days.find((day) => day.day === picker.day) : null;

  const dayClass = (day, base) =>
    [
      base,
      day.weekday >= 5 ? 'is-weekend' : '',
      day.weekday === 0 ? 'is-week-start' : '',
      day.kind === 'rest' ? 'is-rest' : '',
      day.kind === 'custom' ? 'is-custom' : '',
    ]
      .join(' ')
      .trim();

  return (
    <section className="card cneeds">
      <header className="card-header cneeds-head">
        <h2 className="card-title">{t('custom_days.month_title')}</h2>
        {scenario && (
          <span className="cneeds-scenario">
            {scenario.name}
            {scenario.is_selected && (
              <span className="badge badge-primary">{t('scenarios.active_badge')}</span>
            )}
          </span>
        )}
        <PeriodStepper
          label={monthLabel}
          onPrevious={() => changeMonth(-1)}
          onNext={() => changeMonth(1)}
          previousLabel={t('schedule.previous_month')}
          nextLabel={t('schedule.next_month')}
          todayLabel={isCurrentMonth ? null : t('schedule.current_month')}
          onToday={() => changeMonth(null)}
          todaySide="start"
          groupLabel={t('workload.month_nav')}
        />
      </header>

      <div
        className={`cneeds-scroll ${loading ? 'is-loading' : ''}`.trim()}
        aria-busy={loading || undefined}
      >
        <table className="cneeds-table">
          <thead>
            <tr>
              <th className="cneeds-col-name">{t('competence_manager.name')}</th>
              {days.map((day) => (
                <th
                  key={day.day}
                  className={dayClass(day, 'cneeds-day-head')}
                  style={hueStyle(day.kind === 'custom' ? hueById.get(day.custom_day_id) : null)}
                >
                  <button
                    type="button"
                    className={`cneeds-day ${picker?.day === day.day ? 'is-open' : ''}`.trim()}
                    title={dayKindLabel(day)}
                    aria-label={`${day.dayNumber}. ${dayKindLabel(day)}`}
                    aria-haspopup="menu"
                    aria-expanded={picker?.day === day.day}
                    onClick={(e) => {
                      const rect = e.currentTarget.getBoundingClientRect();
                      setPicker((prev) => (prev?.day === day.day ? null : { day: day.day, rect }));
                    }}
                  >
                    <em>{t(`workload.days.${day.weekday}`)}</em>
                    <b>{day.dayNumber}</b>
                    <i className="cneeds-tag">
                      {day.kind === 'custom'
                        ? customById.get(day.custom_day_id)?.name ?? ''
                        : day.kind === 'rest'
                          ? t('special_days.column_short')
                          : ''}
                    </i>
                  </button>
                </th>
              ))}
              <th className="cneeds-col-total">{t('custom_days.total')}</th>
            </tr>
          </thead>
          <tbody>
            {competences.length === 0 && (
              <tr>
                <td className="cmanager-empty-row" colSpan={days.length + 2}>
                  {t('competences.empty')}
                </td>
              </tr>
            )}
            {competences.map((competence) => {
              const total = totals.byCompetence.get(competence.id) || { duties: 0, hours: 0 };
              // Nobody needed on any day of the month: a row of dots.
              if (total.duties === 0) return null;
              return (
                <tr key={competence.id}>
                  <th scope="row" className="cneeds-col-name" title={competence.name}>
                    {competence.name}
                  </th>
                  {days.map((day) => {
                    const need = day.needsById.get(competence.id);
                    const count = need?.required_count ?? 0;
                    return (
                      <td
                        key={day.day}
                        className={[
                          dayClass(day, 'cneeds-cell'),
                          count === 0 ? 'is-zero' : '',
                          need?.is_surcharge && count > 0 ? 'is-surcharge' : '',
                        ]
                          .join(' ')
                          .trim()}
                        style={hueStyle(day.kind === 'custom' ? hueById.get(day.custom_day_id) : null)}
                        title={
                          count > 0
                            ? t('scenarios.hours_short', {
                                hours: clampShiftHours(need.shift_hours),
                              })
                            : undefined
                        }
                      >
                        {count > 0 ? count : '·'}
                      </td>
                    );
                  })}
                  <td className="cneeds-col-total">
                    <b>{total.duties}</b>
                    <em>{t('scenarios.hours_short', { hours: formatHours(total.hours) })}</em>
                  </td>
                </tr>
              );
            })}
          </tbody>
          {competences.length > 0 && (
            <tfoot>
              <tr>
                <th scope="row" className="cneeds-col-name">
                  {t('custom_days.people_total')}
                </th>
                {days.map((day) => (
                  <td
                    key={day.day}
                    className={dayClass(day, 'cneeds-cell')}
                    style={hueStyle(day.kind === 'custom' ? hueById.get(day.custom_day_id) : null)}
                  >
                    {totals.byDay.get(day.day) || '·'}
                  </td>
                ))}
                <td className="cneeds-col-total">
                  <b>{totals.duties}</b>
                  <em>{t('scenarios.hours_short', { hours: formatHours(totals.hours) })}</em>
                </td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      {picker && pickedDay && (
        <div
          ref={pickerRef}
          className="cneeds-picker"
          role="menu"
          style={{
            width: PICKER_WIDTH,
            left: pickerPos?.left ?? picker.rect.left,
            top: pickerPos?.top ?? picker.rect.bottom + 4,
            visibility: pickerPos ? 'visible' : 'hidden',
          }}
        >
          <div className="cneeds-picker-title">
            {new Intl.DateTimeFormat(locale, {
              weekday: 'long',
              day: 'numeric',
              month: 'long',
            }).format(pickedDay.date)}
          </div>
          <button
            type="button"
            role="menuitemradio"
            aria-checked={pickedDay.kind !== 'custom'}
            className="cneeds-option"
            onClick={() => placeDate(pickedDay.day, null)}
          >
            <span className="cneeds-option-mark">
              {pickedDay.kind !== 'custom' && <CheckIcon />}
            </span>
            {t('custom_days.by_calendar')}
            <span className="cneeds-option-meta">
              {pickedDay.is_rest_day
                ? t('special_days.column_short')
                : t(`workload.days.${pickedDay.weekday}`)}
            </span>
          </button>
          {customDays.map((item) => (
            <button
              type="button"
              key={item.id}
              role="menuitemradio"
              aria-checked={pickedDay.custom_day_id === item.id}
              className="cneeds-option"
              style={hueStyle(hueById.get(item.id))}
              onClick={() => placeDate(pickedDay.day, item.id)}
            >
              <span className="cneeds-option-mark">
                {pickedDay.custom_day_id === item.id ? (
                  <CheckIcon />
                ) : (
                  <i className="cneeds-swatch" aria-hidden="true" />
                )}
              </span>
              {item.name}
            </button>
          ))}
        </div>
      )}

    </section>
  );
};

export default CompetenceMonthNeeds;
