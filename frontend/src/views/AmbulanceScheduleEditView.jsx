import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { fetchMyManagedAmbulances } from '../services/competenceService';
import { fetchAmbulanceSchedule, updateAmbulanceSchedule } from '../services/scheduleService';
import './AmbulanceScheduleEditView.css';

const pad = (n) => String(n).padStart(2, '0');
const isoDate = (y, m, d) => `${y}-${pad(m + 1)}-${pad(d)}`;
const isoWeekday = (dateObj) => (dateObj.getDay() + 6) % 7;

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
 * Editable ambulance schedule (kanban-style).
 * Managers drag shifts between days and save bulk.
 * Each day is a drop zone; shifts are draggable cards.
 */
const AmbulanceScheduleEditView = () => {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const today = useMemo(() => new Date(), []);

  const [ambulances, setAmbulances] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
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
      const data = await fetchAmbulanceSchedule(selectedId);
      setShifts(data);
      setOriginalShifts(data);
    } catch {
      setError(t('schedule_edit.load_schedule_error'));
    } finally {
      setLoading(false);
    }
  }, [selectedId, t]);

  useEffect(() => {
    loadAmbulances();
  }, [loadAmbulances]);

  useEffect(() => {
    loadSchedule();
  }, [loadSchedule]);

  const isDirty = useMemo(
    () => JSON.stringify(shifts) !== JSON.stringify(originalShifts),
    [shifts, originalShifts]
  );

  const shiftsByDate = useMemo(() => {
    const map = {};
    shifts.forEach((s) => {
      (map[s.work_date] = map[s.work_date] || []).push(s);
    });
    return map;
  }, [shifts]);

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
    const names = shifts
      .filter((s) => s.user_id === selectedShiftForPreview.user_id)
      .map((s) => s.competence_name)
      .filter(Boolean);
    return [...new Set(names)];
  }, [shifts, selectedShiftForPreview]);

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

    // Move shift to new date
    setShifts((prev) =>
      prev.map((s) =>
        s.id === shift.id ? { ...s, work_date: targetDate } : s
      )
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
      const updated = await updateAmbulanceSchedule(selectedId, entries);
      setShifts(updated);
      setOriginalShifts(updated);
    } catch {
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

  if (loading) {
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
      <header className="schedule-edit-head">
        <button type="button" className="schedule-edit-back" onClick={() => navigate(-1)}>
          ‹
        </button>
        <div>
          <h1 className="schedule-edit-title">{t('schedule_edit.title')}</h1>
          <p className="schedule-edit-subtitle">
            {selected.name} — {monthLabel}
          </p>
        </div>
      </header>

      {error && (
        <div className="schedule-edit-banner schedule-edit-banner-error">
          {error}
        </div>
      )}

      <div className={`schedule-edit-layout ${showList ? '' : 'is-single'}`}>
        {showList && (
          <nav className="schedule-edit-list">
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
          </nav>
        )}

        <div className="schedule-edit-detail">
          <div className={`schedule-edit-grid ${loading ? 'is-loading' : ''}`}>
            {dayLabels.map((label) => (
              <div key={label} className="schedule-edit-grid-head">
                {label}
              </div>
            ))}

            {cells.map((day, idx) => {
              if (day == null) {
                // eslint-disable-next-line react/no-array-index-key
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
                    {dayShifts.map((shift) => (
                      <div
                        key={shift.id}
                        className="schedule-edit-shift"
                        draggable
                        onDragStart={(e) => handleDragStart(e, shift, dateStr)}
                      >
                        <span className="schedule-edit-shift-name">
                          {shift.user_full_name || shift.user_email}
                        </span>
                        {shift.competence_name && (
                          <span className="schedule-edit-shift-competence">
                            {shift.competence_name}
                          </span>
                        )}
                        <button
                          type="button"
                          className="schedule-edit-shift-preview"
                          onClick={() => setSelectedShiftForPreview(shift)}
                          title={t('schedule_edit.view_competences')}
                        >
                          ⋮
                        </button>
                        <button
                          type="button"
                          className="schedule-edit-shift-remove"
                          onClick={() => handleRemoveShift(shift.id)}
                          title={t('schedule_edit.remove_shift')}
                        >
                          ✕
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="schedule-edit-actions">
            <button
              type="button"
              className="schedule-edit-btn schedule-edit-btn-cancel"
              onClick={handleCancel}
              disabled={!isDirty}
            >
              {t('schedule_edit.cancel')}
            </button>
            <span className="schedule-edit-status">
              {isDirty && <span className="schedule-edit-unsaved">●</span>}
              {isDirty ? t('schedule_edit.unsaved') : t('schedule_edit.saved')}
            </span>
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
                previewCompetences.map((name) => (
                  <li key={name} className="schedule-edit-competence-item">
                    {name}
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
