import { useState, useEffect, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { fetchMyManagedAmbulances, fetchCompetences } from '../services/competenceService';
import { fetchAmbulanceSchedule, updateAmbulanceSchedule } from '../services/scheduleService';
import './AmbulanceScheduleEditView.css';

const pad = (n) => String(n).padStart(2, '0');
const isoDate = (y, m, d) => `${y}-${pad(m + 1)}-${pad(d)}`;
const isoWeekday = (dateObj) => (dateObj.getDay() + 6) % 7;

/**
 * Fixed palette assigned to competences by their order (sorted by id).
 * Type 1 = blue, type 2 = red, ... per CALL 05. Cycles if there are more
 * competences than colors.
 */
const COMPETENCE_COLORS = [
  '#4f8ef7', // blue
  '#ef5350', // red
  '#66bb6a', // green
  '#ffb74d', // orange
  '#ab47bc', // purple
  '#26c6da', // cyan
  '#ec407a', // pink
  '#d4e157', // lime
  '#8d6e63', // brown
  '#78909c', // grey-blue
];
const FALLBACK_COLOR = '#9e9e9e';

function buildMonthCells(year, month) {
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const offset = isoWeekday(new Date(year, month, 1));
  const cells = [];
  for (let i = 0; i < offset; i += 1) cells.push(null);
  for (let d = 1; d <= daysInMonth; d += 1) cells.push(d);
  while (cells.length % 7 !== 0) cells.push(null);
  return cells;
}

/**
 * Editable ambulance schedule.
 * - Top action bar (ambulance name + month, save/cancel) instead of a page header.
 * - Competence map under the ambulance list: color legend ordered by competence id.
 * - Each day cell lists employees as colored chips (color = competence),
 *   ordered by the competence map; chips are draggable between days.
 * - Saving syncs via PUT /ambulances/{id}/schedule, which also updates each
 *   employee's personal calendar (same schedule entries).
 */
const AmbulanceScheduleEditView = () => {
  const { t, i18n } = useTranslation();
  const today = useMemo(() => new Date(), []);

  const [ambulances, setAmbulances] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [competences, setCompetences] = useState([]);
  const [shifts, setShifts] = useState([]); // Mutable during editing
  const [originalShifts, setOriginalShifts] = useState([]); // Baseline for dirty check
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [draggedShift, setDraggedShift] = useState(null);
  const [dragOverDate, setDragOverDate] = useState(null);
  const [selectedShiftForPreview, setSelectedShiftForPreview] = useState(null);

  const view = { y: today.getFullYear(), m: today.getMonth() };

  const loadAmbulances = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await fetchMyManagedAmbulances();
      setAmbulances(list);
      if (list.length > 0 && !selectedId) {
        setSelectedId(list[0].id);
      }
    } catch {
      setError(t('schedule_edit.load_ambulances_error'));
    } finally {
      setLoading(false);
    }
  }, [selectedId, t]);

  const loadSchedule = useCallback(async () => {
    if (!selectedId) return;
    setLoading(true);
    setError(null);
    try {
      const [scheduleData, competenceData] = await Promise.all([
        fetchAmbulanceSchedule(selectedId, { month: view.m + 1, year: view.y }),
        fetchCompetences(selectedId),
      ]);
      setShifts(scheduleData);
      setOriginalShifts(scheduleData);
      setCompetences(competenceData);
    } catch {
      setError(t('schedule_edit.load_schedule_error'));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, t]);

  useEffect(() => {
    loadAmbulances();
  }, [loadAmbulances]);

  useEffect(() => {
    loadSchedule();
  }, [loadSchedule]);

  /* --- Competence map: order + colors by competence id --- */

  const competenceMap = useMemo(() => {
    const sorted = [...competences].sort((a, b) => a.id - b.id);
    const map = {};
    sorted.forEach((c, idx) => {
      map[c.id] = {
        ...c,
        order: idx,
        color: COMPETENCE_COLORS[idx % COMPETENCE_COLORS.length],
      };
    });
    return map;
  }, [competences]);

  const legend = useMemo(
    () => Object.values(competenceMap).sort((a, b) => a.order - b.order),
    [competenceMap]
  );

  const competenceColor = (competenceId) =>
    competenceMap[competenceId]?.color || FALLBACK_COLOR;

  const competenceOrder = (competenceId) =>
    competenceMap[competenceId]?.order ?? Number.MAX_SAFE_INTEGER;

  const isDirty = useMemo(
    () => JSON.stringify(shifts) !== JSON.stringify(originalShifts),
    [shifts, originalShifts]
  );

  const shiftsByDate = useMemo(() => {
    const map = {};
    shifts.forEach((s) => {
      (map[s.work_date] = map[s.work_date] || []).push(s);
    });
    // Order employees inside each day by the competence map order, then name.
    Object.values(map).forEach((list) =>
      list.sort(
        (a, b) =>
          competenceOrder(a.competence_id) - competenceOrder(b.competence_id) ||
          (a.user_full_name || '').localeCompare(b.user_full_name || '')
      )
    );
    return map;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shifts, competenceMap]);

  const cells = useMemo(() => buildMonthCells(view.y, view.m), [view.y, view.m]);

  const monthLabel = useMemo(() => {
    const formatter = new Intl.DateTimeFormat(i18n.language === 'en' ? 'en-GB' : 'sk-SK', {
      month: 'long',
      year: 'numeric',
    });
    return formatter.format(new Date(view.y, view.m, 1));
  }, [view.y, view.m, i18n.language]);

  const dayLabels = useMemo(
    () => [0, 1, 2, 3, 4, 5, 6].map((i) => t(`workload.days.${i}`)),
    [t]
  );

  const selected = ambulances.find((a) => a.id === selectedId) || null;
  const showList = ambulances.length > 1;

  const previewCompetences = useMemo(() => {
    if (!selectedShiftForPreview) return [];
    const seen = new Map();
    shifts
      .filter((s) => s.user_id === selectedShiftForPreview.user_id)
      .forEach((s) => {
        if (s.competence_name && !seen.has(s.competence_id)) {
          seen.set(s.competence_id, {
            id: s.competence_id,
            name: s.competence_name,
            color: competenceColor(s.competence_id),
          });
        }
      });
    return [...seen.values()];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shifts, selectedShiftForPreview, competenceMap]);

  useEffect(() => {
    if (!selectedShiftForPreview) return undefined;
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') setSelectedShiftForPreview(null);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectedShiftForPreview]);

  /* --- Drag and drop --- */

  const handleDragStart = (e, shift, sourceDate) => {
    setDraggedShift({ shift, sourceDate });
    e.dataTransfer.effectAllowed = 'move';
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  };

  const handleDragEnter = (e, date) => {
    setDragOverDate(date);
  };

  const handleDragLeave = (e) => {
    if (e.currentTarget === e.target) {
      setDragOverDate(null);
    }
  };

  const handleDrop = (e, targetDate) => {
    e.preventDefault();
    setDragOverDate(null);

    if (!draggedShift) return;
    const { shift, sourceDate } = draggedShift;

    if (sourceDate === targetDate) {
      setDraggedShift(null);
      return; // No change
    }

    // Move the shift to the new date (persisted on save; the employee's
    // personal calendar reflects the change automatically after save).
    setShifts((prev) =>
      prev.map((s) => (s.id === shift.id ? { ...s, work_date: targetDate } : s))
    );
    setDraggedShift(null);
  };

  const handleRemoveShift = (shiftId) => {
    setShifts((prev) => prev.filter((s) => s.id !== shiftId));
  };

  const handleSave = async () => {
    if (!selectedId || !isDirty) return;
    setSaving(true);
    setError(null);
    try {
      const entries = shifts.map((s) => ({
        user_id: s.user_id,
        competence_id: s.competence_id,
        work_date: s.work_date,
      }));
      await updateAmbulanceSchedule(selectedId, entries, {
        month: view.m + 1,
        year: view.y,
      });
      // After save, reload from GET so the state matches the backend exactly.
      // PUT returns ScheduleResponse (flat), but GET returns UserMonthlySchedule
      // (grouped by employee) which we already know how to flatten correctly.
      const fresh = await fetchAmbulanceSchedule(selectedId, {
        month: view.m + 1,
        year: view.y,
      });
      setShifts(fresh);
      setOriginalShifts(fresh);
    } catch (err) {
       
      console.error('[schedule save]', err?.response?.status, err?.response?.data ?? err);
      setError(t('schedule_edit.save_error'));
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    if (isDirty && !window.confirm(t('schedule_edit.unsaved_warning'))) {
      return;
    }
    setShifts(originalShifts);
  };

  if (loading && !selected) {
    return (
      <div className="schedule-edit">
        <p>{t('schedule_edit.loading')}</p>
      </div>
    );
  }

  if (!selected) {
    return (
      <div className="schedule-edit">
        <p>{t('schedule_edit.no_ambulances')}</p>
      </div>
    );
  }

  return (
    <div className="schedule-edit">
      {error && (
        <div className="schedule-edit-banner schedule-edit-banner-error">{error}</div>
      )}

      <div className={`schedule-edit-layout ${showList ? '' : 'is-single'}`}>
        <nav className="schedule-edit-side">
          {showList && (
            <div className="schedule-edit-list">
              {ambulances.map((a) => (
                <button
                  type="button"
                  key={a.id}
                  className={`schedule-edit-item ${a.id === selectedId ? 'is-selected' : ''}`}
                  onClick={() => setSelectedId(a.id)}
                >
                  <span className="schedule-edit-item-name">{a.name}</span>
                  {a.description && (
                    <span className="schedule-edit-item-desc">{a.description}</span>
                  )}
                </button>
              ))}
            </div>
          )}

          <div className="schedule-edit-legend">
            <span className="schedule-edit-legend-title">
              {t('schedule_edit.legend_title')}
            </span>
            {legend.length > 0 ? (
              <ul className="schedule-edit-legend-list">
                {legend.map((c) => (
                  <li key={c.id} className="schedule-edit-legend-item">
                    <span
                      className="schedule-edit-legend-swatch"
                      style={{ backgroundColor: c.color }}
                    />
                    <span className="schedule-edit-legend-name">{c.name}</span>
                    {c.required_count != null && (
                      <span className="schedule-edit-legend-count">
                        {c.required_count}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="schedule-edit-legend-empty">
                {t('schedule_edit.legend_empty')}
              </p>
            )}
          </div>
        </nav>

        <div className="schedule-edit-detail">
          <div className="schedule-edit-topbar">
            <div className="schedule-edit-topbar-info">
              <span className="schedule-edit-topbar-name">{selected.name}</span>
              <span className="schedule-edit-topbar-month">{monthLabel}</span>
            </div>
            <div className="schedule-edit-topbar-actions">
              <span className="schedule-edit-status">
                {isDirty && <span className="schedule-edit-unsaved">●</span>}
                {isDirty ? t('schedule_edit.unsaved') : t('schedule_edit.saved')}
              </span>
              <button
                type="button"
                className="schedule-edit-btn schedule-edit-btn-cancel"
                onClick={handleCancel}
                disabled={!isDirty}
              >
                {t('schedule_edit.cancel')}
              </button>
              <button
                type="button"
                className="schedule-edit-btn schedule-edit-btn-primary"
                onClick={handleSave}
                disabled={!isDirty || saving}
              >
                {saving ? t('schedule_edit.saving') : t('schedule_edit.save')}
              </button>
            </div>
          </div>

          <div className={`schedule-edit-grid ${loading ? 'is-loading' : ''}`}>
            {dayLabels.map((label) => (
              <div key={label} className="schedule-edit-grid-head">
                {label}
              </div>
            ))}

            {cells.map((day, idx) => {
              if (day == null) {
                return (
                  <div key={`e${idx}`} className="schedule-edit-cell schedule-edit-cell-empty" />
                );
              }

              const dateStr = isoDate(view.y, view.m, day);
              const dayShifts = shiftsByDate[dateStr] || [];
              const isToday = day === today.getDate();
              const isDragOver = dragOverDate === dateStr;

              return (
                <div
                  key={dateStr}
                  className={`schedule-edit-cell ${isToday ? 'is-today' : ''} ${
                    isDragOver ? 'is-drag-over' : ''
                  }`}
                  onDragOver={handleDragOver}
                  onDragEnter={(e) => handleDragEnter(e, dateStr)}
                  onDragLeave={handleDragLeave}
                  onDrop={(e) => handleDrop(e, dateStr)}
                >
                  <span className="schedule-edit-cell-daynum">{day}</span>
                  <div className="schedule-edit-shifts">
                    {dayShifts.map((shift) => {
                      const color = competenceColor(shift.competence_id);
                      return (
                        <div
                          key={shift.id}
                          className="schedule-edit-shift"
                          style={{
                            borderLeftColor: color,
                            backgroundColor: `${color}26`,
                          }}
                          draggable
                          onDragStart={(e) => handleDragStart(e, shift, dateStr)}
                          onClick={() => setSelectedShiftForPreview(shift)}
                          title={shift.competence_name || ''}
                        >
                          <span className="schedule-edit-shift-name">
                            {shift.user_full_name || shift.user_email}
                          </span>
                          <button
                            type="button"
                            className="schedule-edit-shift-remove"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleRemoveShift(shift.id);
                            }}
                            title={t('schedule_edit.remove_shift')}
                          >
                            ✕
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {selectedShiftForPreview && (
        <div
          className="schedule-edit-competence-popup-overlay"
          onClick={(e) => {
            if (e.target === e.currentTarget) setSelectedShiftForPreview(null);
          }}
        >
          <div className="schedule-edit-competence-popup" role="dialog" aria-modal="true">
            <div className="schedule-edit-competence-popup-header">
              <span>
                {selectedShiftForPreview.user_full_name || selectedShiftForPreview.user_email}
              </span>
              <button
                type="button"
                className="schedule-edit-competence-popup-close"
                onClick={() => setSelectedShiftForPreview(null)}
                title={t('schedule_edit.close')}
              >
                ✕
              </button>
            </div>
            <ul className="schedule-edit-competence-popup-list">
              {previewCompetences.length > 0 ? (
                previewCompetences.map((c) => (
                  <li key={c.id} className="schedule-edit-competence-item">
                    <span
                      className="schedule-edit-legend-swatch"
                      style={{ backgroundColor: c.color }}
                    />
                    {c.name}
                  </li>
                ))
              ) : (
                <li className="schedule-edit-competence-item">
                  {t('schedule_edit.no_competences')}
                </li>
              )}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
};

export default AmbulanceScheduleEditView;
