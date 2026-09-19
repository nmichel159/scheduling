import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  fetchCompetences,
  fetchEmployeeCompetenceTable,
} from '../services/competenceService';
import { useWorkplace } from '../hooks/workplaceContext';
import EmployeeDetailDialog from '../components/EmployeeDetailDialog';
import './EmployeesView.css';

/**
 * Employee roster of one workplace (scheduler screen).
 *
 * Read-only on purpose: this screen answers "who works here and what can
 * they do", nothing more. Assigning people to the workplace and ticking
 * their competences stays in the competence matrix (/departments), which
 * is an editable draft with its own Save — two screens writing the same
 * table from different places is how drafts get lost.
 *
 * Which workplace is shown comes from the header switcher, like everywhere
 * else. The data is the same bulk table the matrix loads, just presented
 * per person instead of as a grid.
 *
 * Clicking a row opens the shared employee dialog — the same one the
 * matrix opens, so when it grows an edit form both screens get it.
 */
const EmployeesView = () => {
  const { t } = useTranslation();

  const {
    activeId: selectedId,
    active: selected,
    loading: workplacesLoading,
    error: workplacesError,
    forbidden,
    workplaces,
  } = useWorkplace();

  const [employees, setEmployees] = useState([]);
  const [competences, setCompetences] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [filter, setFilter] = useState('');
  const [detailId, setDetailId] = useState(null);

  const load = useCallback(async () => {
    if (selectedId == null) return;
    setLoading(true);
    setLoadError(false);
    try {
      const [table, comps] = await Promise.all([
        fetchEmployeeCompetenceTable(selectedId),
        fetchCompetences(selectedId),
      ]);
      setEmployees(
        table.map((row) => ({
          user_id: row.user_id,
          email: row.email,
          full_name: row.full_name,
          competences: row.competences.map((c) => ({ id: c.id, name: c.name })),
        }))
      );
      setCompetences(comps);
    } catch {
      setEmployees([]);
      setCompetences([]);
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, [selectedId]);

  useEffect(() => {
    load();
  }, [load]);

  /* Name, e-mail and competence names are all searchable, so "kto vie
   * ultrazvuk" is one query away without leaving the list. */
  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return employees;
    return employees.filter(
      (e) =>
        (e.full_name || '').toLowerCase().includes(q) ||
        e.email.toLowerCase().includes(q) ||
        e.competences.some((c) => c.name.toLowerCase().includes(q))
    );
  }, [employees, filter]);

  const detail = employees.find((e) => e.user_id === detailId) || null;

  if (workplacesLoading) {
    return (
      <div className="employees">
        <p>{t('departments.loading')}</p>
      </div>
    );
  }

  if (forbidden || workplaces.length === 0) {
    return (
      <div className="employees">
        <h1 className="employees-title">{t('employees.title')}</h1>
        <div className="employees-banner">
          {forbidden ? t('departments.forbidden') : t('departments.no_ambulances')}
        </div>
      </div>
    );
  }

  return (
    <div className="employees">
      <h1 className="employees-title">{t('employees.title')}</h1>
      <p className="employees-subtitle">{t('employees.subtitle')}</p>

      {(workplacesError || loadError) && (
        <div className="employees-banner">{t('departments.load_error')}</div>
      )}

      <section className="employees-panel">
        <header className="employees-head">
          <div className="employees-heading">
            <h2 className="employees-workplace">{selected?.name}</h2>
            <span className="employees-count">
              {t('departments.employee_count', { count: employees.length })}
            </span>
          </div>

          <div className={`employees-filter ${filter ? 'is-active' : ''}`}>
            <span className="employees-filter-icon" aria-hidden="true">⌕</span>
            <input
              type="text"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder={t('employees.filter_placeholder')}
              aria-label={t('employees.filter_placeholder')}
            />
            {filter && (
              <button
                type="button"
                className="employees-filter-clear"
                onClick={() => setFilter('')}
                title={t('competences.clear_filter')}
                aria-label={t('competences.clear_filter')}
              >
                ✕
              </button>
            )}
          </div>
        </header>

        <div className={`employees-list ${loading ? 'is-loading' : ''}`}>
          {visible.length === 0 ? (
            <p className="employees-empty">
              {employees.length > 0
                ? t('competences.no_filter_match')
                : t('departments.no_employees')}
            </p>
          ) : (
            <ul className="employees-rows">
              {visible.map((e) => (
                <li key={e.user_id}>
                  {/* The whole row is the button — see the "clickable text =
                    * clickable field" rule in the README. */}
                  <button
                    type="button"
                    className="employees-row"
                    onClick={() => setDetailId(e.user_id)}
                    title={t('competences.employee_detail')}
                  >
                    <span className="employees-avatar" aria-hidden="true">
                      {(e.full_name || e.email).trim().charAt(0).toUpperCase()}
                    </span>
                    <span className="employees-identity">
                      <span className="employees-name">{e.full_name || e.email}</span>
                      <span className="employees-email">{e.email}</span>
                    </span>
                    <span className="employees-tags">
                      {e.competences.length === 0 ? (
                        <span className="employees-tag is-empty">
                          {t('employees.no_competences')}
                        </span>
                      ) : (
                        e.competences.map((c) => (
                          <span key={c.id} className="employees-tag">
                            {c.name}
                          </span>
                        ))
                      )}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {competences.length > 0 && (
          <footer className="employees-foot">
            {t('employees.competence_count', { count: competences.length })}
          </footer>
        )}
      </section>

      <EmployeeDetailDialog
        employee={detail}
        competences={detail ? detail.competences : []}
        onClose={() => setDetailId(null)}
      />
    </div>
  );
};

export default EmployeesView;
