import { useState, useEffect, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import {
  fetchManagerAmbulances,
  fetchEmployees,
  addEmployee,
  removeEmployee,
  fetchUsers,
} from '../services/ambulanceService';
import './DepartmentsView.css';

/**
 * Department (ambulance) management view for managers.
 * Shows all ambulances the current user manages; selecting one lists
 * its employees with the ability to add or remove them at any time.
 * When the manager leads only a single ambulance, the side list is
 * hidden and the detail is shown directly (full width).
 */
const DepartmentsView = () => {
  const { t } = useTranslation();

  const currentUser = useMemo(() => {
    try {
      return JSON.parse(localStorage.getItem('user')) || null;
    } catch {
      return null;
    }
  }, []);

  const [ambulances, setAmbulances] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [employees, setEmployees] = useState([]);
  const [allUsers, setAllUsers] = useState([]);

  const [loading, setLoading] = useState(true);
  const [employeesLoading, setEmployeesLoading] = useState(false);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState(null);
  const [toast, setToast] = useState(null);

  const [pickerValue, setPickerValue] = useState('');
  const [confirmingId, setConfirmingId] = useState(null);

  const notify = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2400);
  };

  /* ---------- initial load: my ambulances + user list ---------- */

  useEffect(() => {
    if (!currentUser?.id) return;
    let cancelled = false;

    (async () => {
      setLoading(true);
      setError(null);
      try {
        const [myAmbulances, users] = await Promise.all([
          fetchManagerAmbulances(currentUser.id),
          fetchUsers().catch((err) => {
            // 403 here just means the user is not a manager.
            if (err?.response?.status === 403) setForbidden(true);
            return [];
          }),
        ]);
        if (cancelled) return;
        setAmbulances(myAmbulances);
        setAllUsers(users);
        if (myAmbulances.length > 0) setSelectedId(myAmbulances[0].id);
      } catch {
        if (!cancelled) setError(t('departments.load_error'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [currentUser, t]);

  /* ---------- employees of the selected ambulance ---------- */

  const loadEmployees = useCallback(async () => {
    if (selectedId == null) return;
    setEmployeesLoading(true);
    setConfirmingId(null);
    try {
      const list = await fetchEmployees(selectedId);
      setEmployees(list);
    } catch {
      setEmployees([]);
      notify(t('departments.load_error'));
    } finally {
      setEmployeesLoading(false);
    }
  }, [selectedId, t]);

  useEffect(() => {
    loadEmployees();
  }, [loadEmployees]);

  /* ---------- actions ---------- */

  const availableUsers = useMemo(() => {
    const assigned = new Set(employees.map((e) => e.user_id));
    return allUsers.filter((u) => !assigned.has(u.id));
  }, [allUsers, employees]);

  const handleAdd = async () => {
    const userId = Number(pickerValue);
    if (!userId || selectedId == null) return;
    try {
      await addEmployee(selectedId, userId);
      setPickerValue('');
      notify(t('departments.added'));
      loadEmployees();
    } catch (err) {
      notify(
        err?.response?.status === 409
          ? t('departments.already_assigned')
          : t('departments.action_error')
      );
    }
  };

  const handleRemove = async (userId) => {
    if (selectedId == null) return;
    try {
      await removeEmployee(selectedId, userId);
      setConfirmingId(null);
      notify(t('departments.removed'));
      loadEmployees();
    } catch {
      notify(t('departments.action_error'));
    }
  };

  /* ---------- render ---------- */

  const selected = ambulances.find((a) => a.id === selectedId) || null;
  const showList = ambulances.length > 1; // 1 klinika = bez bočného zoznamu

  if (loading) {
    return <div className="departments"><p>{t('departments.loading')}</p></div>;
  }

  if (forbidden || (!loading && ambulances.length === 0)) {
    return (
      <div className="departments">
        <h1 className="departments-title">{t('departments.title')}</h1>
        <div className="departments-banner">
          {forbidden ? t('departments.forbidden') : t('departments.no_ambulances')}
        </div>
      </div>
    );
  }

  return (
    <div className="departments">
      <h1 className="departments-title">{t('departments.title')}</h1>
      <p className="departments-subtitle">{t('departments.subtitle')}</p>

      {error && <div className="departments-banner">{error}</div>}

      <div className={`departments-layout ${showList ? '' : 'is-single'}`}>
        {/* left: my ambulances — zobrazí sa len pri viacerých klinikách */}
        {showList && (
          <nav className="departments-list" aria-label={t('departments.my_ambulances')}>
            {ambulances.map((a) => (
              <button
                type="button"
                key={a.id}
                className={`departments-item ${a.id === selectedId ? 'is-selected' : ''}`}
                onClick={() => setSelectedId(a.id)}
              >
                <span className="departments-item-name">{a.name}</span>
                {a.description && <span className="departments-item-desc">{a.description}</span>}
              </button>
            ))}
          </nav>
        )}

        {/* right: employees of the selected ambulance */}
        <section className="departments-detail">
          {selected && (
            <>
              <header className="departments-detail-head">
                <h2 className="departments-detail-title">{selected.name}</h2>
                {!showList && selected.description && (
                  <p className="departments-detail-desc">{selected.description}</p>
                )}
                <span className="departments-count">
                  {t('departments.employee_count', { count: employees.length })}
                </span>
              </header>

              <div className="departments-add">
                <select
                  value={pickerValue}
                  onChange={(e) => setPickerValue(e.target.value)}
                  aria-label={t('departments.pick_user')}
                >
                  <option value="">{t('departments.pick_user')}</option>
                  {availableUsers.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.full_name || u.email} ({u.email})
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="departments-btn departments-btn-primary"
                  disabled={!pickerValue}
                  onClick={handleAdd}
                >
                  {t('departments.add')}
                </button>
              </div>

              <ul className={`departments-employees ${employeesLoading ? 'is-loading' : ''}`}>
                {employees.length === 0 && !employeesLoading && (
                  <li className="departments-empty">{t('departments.no_employees')}</li>
                )}
                {employees.map((e) => (
                  <li key={e.user_id} className="departments-employee">
                    <div className="departments-employee-info">
                      <span className="departments-employee-name">{e.full_name || e.email}</span>
                      <span className="departments-employee-email">{e.email}</span>
                    </div>
                    {confirmingId === e.user_id ? (
                      <div className="departments-confirm">
                        <span>{t('departments.confirm_remove')}</span>
                        <button
                          type="button"
                          className="departments-btn departments-btn-danger"
                          onClick={() => handleRemove(e.user_id)}
                        >
                          {t('departments.yes')}
                        </button>
                        <button
                          type="button"
                          className="departments-btn"
                          onClick={() => setConfirmingId(null)}
                        >
                          {t('departments.no')}
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        className="departments-btn departments-btn-outline-danger"
                        onClick={() => setConfirmingId(e.user_id)}
                      >
                        {t('departments.remove')}
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      </div>

      {toast && (
        <div className="departments-toast" role="status">
          {toast}
        </div>
      )}
    </div>
  );
};

export default DepartmentsView;
