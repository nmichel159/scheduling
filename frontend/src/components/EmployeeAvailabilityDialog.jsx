import { useCallback, useLayoutEffect } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import WorkloadCalendar from './WorkloadCalendar';
import {
  createEmployeeUnavailability,
  deleteEmployeeUnavailability,
  fetchEmployeeMonthlyWish,
  fetchEmployeeUnavailabilities,
  saveEmployeeMonthlyWish,
  updateEmployeeUnavailability,
} from '../services/unavailabilityService';
import './EmployeeAvailabilityDialog.css';

/**
 * One employee's availability calendar, opened by their manager.
 *
 * The calendar itself is the same component the employee sees on
 * /workload; only the six functions it reads and writes through are
 * swapped for the workplace-scoped routes, which check that the caller
 * manages the workplace and that the person is one of its employees. A
 * day is therefore marked here exactly as the employee would mark it,
 * and the generator reads the result the same way.
 *
 * Every click writes immediately, the way the employee's own calendar
 * does, so there is nothing to save and closing loses nothing.
 *
 * Props:
 * - employee: { user_id, full_name, email } | null — null renders nothing
 * - ambulanceId: number
 * - onClose() — the opening screen reloads the month afterwards
 */
const EmployeeAvailabilityDialog = ({ employee, ambulanceId, onClose }) => {
  const { t } = useTranslation();
  const userId = employee ? employee.user_id : null;

  const fetchEntries = useCallback(
    (dateFrom, dateTo) =>
      fetchEmployeeUnavailabilities(ambulanceId, userId, dateFrom, dateTo),
    [ambulanceId, userId]
  );
  const createEntry = useCallback(
    (dateAbsent, reason) =>
      createEmployeeUnavailability(ambulanceId, userId, dateAbsent, reason),
    [ambulanceId, userId]
  );
  const updateEntry = useCallback(
    (id, reason) => updateEmployeeUnavailability(ambulanceId, userId, id, reason),
    [ambulanceId, userId]
  );
  const deleteEntry = useCallback(
    (id) => deleteEmployeeUnavailability(ambulanceId, userId, id),
    [ambulanceId, userId]
  );
  const loadWish = useCallback(
    () => fetchEmployeeMonthlyWish(ambulanceId, userId),
    [ambulanceId, userId]
  );
  const storeWish = useCallback(
    (value) => saveEmployeeMonthlyWish(ambulanceId, userId, value),
    [ambulanceId, userId]
  );

  useLayoutEffect(() => {
    if (!employee) return;
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [employee, onClose]);

  if (!employee || ambulanceId == null) return null;

  const label = employee.full_name || employee.email;

  return createPortal(
    <div
      className="availdlg-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="availdlg" role="dialog" aria-modal="true">
        <header className="availdlg-head">
          <div className="availdlg-avatar" aria-hidden="true">
            {label.trim().charAt(0).toUpperCase()}
          </div>
          <div className="availdlg-heading">
            <h3 className="availdlg-title">{label}</h3>
            <p className="availdlg-subtitle">{t('employees.availability')}</p>
          </div>
          <button
            type="button"
            className="availdlg-close"
            onClick={onClose}
            title={t('competences.close_detail')}
            aria-label={t('competences.close_detail')}
          >
            ✕
          </button>
        </header>

        <div className="availdlg-body workload">
          <WorkloadCalendar
            titleLevel={4}
            fetchEntries={fetchEntries}
            createEntry={createEntry}
            updateEntry={updateEntry}
            deleteEntry={deleteEntry}
            fetchMonthlyWish={loadWish}
            saveMonthlyWish={storeWish}
          />
        </div>
      </div>
    </div>,
    document.body
  );
};

export default EmployeeAvailabilityDialog;
