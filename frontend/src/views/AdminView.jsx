import { useState, useEffect, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  fetchAllAmbulances,
  createAmbulance,
  updateAmbulance,
  deleteAmbulance,
  fetchUsersByRole,
  assignManagerToAmbulance,
  removeManagerFromAmbulance,
} from '../services/ambulanceService';
import ConfirmDialog from '../components/ConfirmDialog';
import './AdminView.css';

// Role IDs eligible to be assigned as an ambulance manager: 2 = LEADER, 3 = AMBULANCE_OVERSEER.
const MANAGER_ELIGIBLE_ROLE_IDS = [2, 3];

const emptyDraft = { name: '', description: '', isurgent: false, managerId: '' };

/**
 * Ambulance administration view for Role 3+ (AMBULANCE_OVERSEER).
 *
 * Lists every ambulance in the hospital with full CRUD and lets the admin
 * (re)assign which manager (Role Level >= 2) runs each one.
 */
const AdminView = () => {
  const { t } = useTranslation();

  const [ambulances, setAmbulances] = useState([]);
  const [managers, setManagers] = useState([]);

  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState(null);
  const [toast, setToast] = useState(null);

  const [sortKey, setSortKey] = useState('name');
  const [sortDir, setSortDir] = useState('asc');

  const [showCreateForm, setShowCreateForm] = useState(false);
  const [createDraft, setCreateDraft] = useState(emptyDraft);
  const [creating, setCreating] = useState(false);

  const [editingId, setEditingId] = useState(null);
  const [editDraft, setEditDraft] = useState(emptyDraft);
  const [savingId, setSavingId] = useState(null);

  const [confirmState, setConfirmState] = useState(null);

  const notify = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2400);
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [amb, ...roleResults] = await Promise.all([
        fetchAllAmbulances(),
        ...MANAGER_ELIGIBLE_ROLE_IDS.map(fetchUsersByRole),
      ]);
      setAmbulances(amb);

      // Merge + dedupe users appearing in more than one eligible role.
      const merged = new Map();
      roleResults.flat().forEach((u) => merged.set(u.id, u));
      const sortedManagers = Array.from(merged.values()).sort((a, b) =>
        (a.full_name || a.email).localeCompare(b.full_name || b.email)
      );
      setManagers(sortedManagers);
    } catch (err) {
      if (err?.response?.status === 403) setForbidden(true);
      else setError(t('admin.load_error'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    load();
  }, [load]);

  const managerName = useCallback(
    (managerId) => {
      if (managerId == null) return t('admin.no_manager');
      const manager = managers.find((m) => m.id === managerId);
      return manager ? manager.full_name || manager.email : t('admin.no_manager');
    },
    [managers, t]
  );

  /* ---------- sorting ---------- */

  const toggleSort = (key) => {
    if (key === sortKey) {
      setSortDir((prev) => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  };

  const sortedAmbulances = useMemo(() => {
    const dir = sortDir === 'asc' ? 1 : -1;
    const value = (a) => {
      switch (sortKey) {
        case 'id':
          return a.id;
        case 'isurgent':
          return a.isurgent ? 1 : 0;
        case 'manager':
          return managerName(a.managed_by_user_id).toLowerCase();
        case 'description':
          return (a.description || '').toLowerCase();
        default:
          return (a.name || '').toLowerCase();
      }
    };
    return [...ambulances].sort((a, b) => {
      const va = value(a);
      const vb = value(b);
      if (va < vb) return -1 * dir;
      if (va > vb) return 1 * dir;
      return 0;
    });
  }, [ambulances, sortKey, sortDir, managerName]);

  /* ---------- create ---------- */

  const handleCreate = async (e) => {
    e.preventDefault();
    if (!createDraft.name.trim() || creating) return;
    setCreating(true);
    try {
      await createAmbulance({
        name: createDraft.name.trim(),
        description: createDraft.description.trim() || null,
        isurgent: createDraft.isurgent,
      });
      notify(t('admin.created'));
      setCreateDraft(emptyDraft);
      setShowCreateForm(false);
      await load();
    } catch {
      notify(t('admin.action_error'));
    } finally {
      setCreating(false);
    }
  };

  /* ---------- edit ---------- */

  const startEdit = (ambulance) => {
    setEditingId(ambulance.id);
    setEditDraft({
      name: ambulance.name || '',
      description: ambulance.description || '',
      isurgent: !!ambulance.isurgent,
      managerId: ambulance.managed_by_user_id != null ? String(ambulance.managed_by_user_id) : '',
    });
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditDraft(emptyDraft);
  };

  const saveEdit = async (id) => {
    if (!editDraft.name.trim()) return;
    setSavingId(id);
    try {
      const original = ambulances.find((a) => a.id === id);
      const originalManagerId = original?.managed_by_user_id ?? null;
      const newManagerId = editDraft.managerId === '' ? null : Number(editDraft.managerId);

      await updateAmbulance(id, {
        name: editDraft.name.trim(),
        description: editDraft.description.trim() || null,
        isurgent: editDraft.isurgent,
      });

      if (newManagerId !== originalManagerId) {
        if (newManagerId == null) {
          await removeManagerFromAmbulance(id);
        } else {
          await assignManagerToAmbulance(id, newManagerId);
        }
      }

      notify(t('admin.saved'));
      cancelEdit();
      await load();
    } catch {
      notify(t('admin.action_error'));
    } finally {
      setSavingId(null);
    }
  };

  /* ---------- delete ---------- */

  const askDelete = (ambulance) => {
    setConfirmState({
      message: t('admin.confirm_delete_named', { name: ambulance.name }),
      onConfirm: async () => {
        setConfirmState(null);
        try {
          await deleteAmbulance(ambulance.id);
          notify(t('admin.deleted'));
          await load();
        } catch {
          notify(t('admin.action_error'));
        }
      },
      onCancel: () => setConfirmState(null),
    });
  };

  /* ---------- render ---------- */

  const sortIndicator = (key) => (sortKey === key ? (sortDir === 'asc' ? ' ▲' : ' ▼') : '');

  if (loading) {
    return <div className="admin"><p>{t('admin.loading')}</p></div>;
  }

  if (forbidden) {
    return (
      <div className="admin">
        <h1 className="admin-title">{t('admin.title')}</h1>
        <div className="admin-banner">{t('admin.forbidden')}</div>
      </div>
    );
  }

  return (
    <div className="admin">
      <h1 className="admin-title">{t('admin.title')}</h1>
      <p className="admin-subtitle">{t('admin.subtitle')}</p>

      {error && <div className="admin-banner">{error}</div>}

      <div className="admin-toolbar">
        <button
          type="button"
          className="admin-btn admin-btn-primary"
          onClick={() => setShowCreateForm((prev) => !prev)}
        >
          {t('admin.add_new')}
        </button>
      </div>

      {showCreateForm && (
        <form className="admin-create-form" onSubmit={handleCreate}>
          <h2 className="admin-create-title">{t('admin.create_title')}</h2>
          <div className="admin-form-row">
            <label className="admin-form-field">
              <span>{t('admin.name')}</span>
              <input
                type="text"
                value={createDraft.name}
                placeholder={t('admin.name_placeholder')}
                onChange={(e) => setCreateDraft((prev) => ({ ...prev, name: e.target.value }))}
                required
              />
            </label>
            <label className="admin-form-field admin-form-field-grow">
              <span>{t('admin.description')}</span>
              <input
                type="text"
                value={createDraft.description}
                placeholder={t('admin.description_placeholder')}
                onChange={(e) =>
                  setCreateDraft((prev) => ({ ...prev, description: e.target.value }))
                }
              />
            </label>
            <label className="admin-form-checkbox">
              <input
                type="checkbox"
                checked={createDraft.isurgent}
                onChange={(e) =>
                  setCreateDraft((prev) => ({ ...prev, isurgent: e.target.checked }))
                }
              />
              <span>{t('admin.isurgent')}</span>
            </label>
          </div>
          <div className="admin-form-actions">
            <button
              type="button"
              className="admin-btn"
              onClick={() => {
                setShowCreateForm(false);
                setCreateDraft(emptyDraft);
              }}
            >
              {t('admin.cancel')}
            </button>
            <button
              type="submit"
              className="admin-btn admin-btn-primary"
              disabled={creating || !createDraft.name.trim()}
            >
              {t('admin.create')}
            </button>
          </div>
        </form>
      )}

      {ambulances.length === 0 ? (
        <div className="admin-banner">{t('admin.no_ambulances')}</div>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th className="is-sortable" onClick={() => toggleSort('name')}>
                  {t('admin.col_name')}
                  {sortIndicator('name')}
                </th>
                <th className="is-sortable" onClick={() => toggleSort('description')}>
                  {t('admin.col_description')}
                  {sortIndicator('description')}
                </th>
                <th className="is-sortable" onClick={() => toggleSort('isurgent')}>
                  {t('admin.col_urgent')}
                  {sortIndicator('isurgent')}
                </th>
                <th className="is-sortable" onClick={() => toggleSort('manager')}>
                  {t('admin.col_manager')}
                  {sortIndicator('manager')}
                </th>
                <th>{t('admin.col_actions')}</th>
              </tr>
            </thead>
            <tbody>
              {sortedAmbulances.map((a) => {
                const isEditing = editingId === a.id;
                return (
                  <tr key={a.id} className={isEditing ? 'is-editing' : ''}>
                    {isEditing ? (
                      <>
                        <td>
                          <input
                            type="text"
                            value={editDraft.name}
                            onChange={(e) =>
                              setEditDraft((prev) => ({ ...prev, name: e.target.value }))
                            }
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            value={editDraft.description}
                            onChange={(e) =>
                              setEditDraft((prev) => ({ ...prev, description: e.target.value }))
                            }
                          />
                        </td>
                        <td>
                          <input
                            type="checkbox"
                            checked={editDraft.isurgent}
                            onChange={(e) =>
                              setEditDraft((prev) => ({ ...prev, isurgent: e.target.checked }))
                            }
                          />
                        </td>
                        <td>
                          <select
                            className="admin-table-select"
                            value={editDraft.managerId}
                            onChange={(e) =>
                              setEditDraft((prev) => ({ ...prev, managerId: e.target.value }))
                            }
                          >
                            <option value="">{t('admin.no_manager')}</option>
                            {managers.map((m) => (
                              <option key={m.id} value={m.id}>
                                {m.full_name || m.email}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td className="admin-actions">
                          <button
                            type="button"
                            className="admin-btn admin-btn-primary"
                            disabled={savingId === a.id || !editDraft.name.trim()}
                            onClick={() => saveEdit(a.id)}
                          >
                            {t('admin.save')}
                          </button>
                          <button type="button" className="admin-btn" onClick={cancelEdit}>
                            {t('admin.cancel')}
                          </button>
                          <button
                            type="button"
                            className="admin-btn admin-btn-outline-danger"
                            onClick={() => askDelete(a)}
                          >
                            {t('admin.delete')}
                          </button>
                        </td>
                      </>
                    ) : (
                      <>
                        <td>{a.name}</td>
                        <td className="admin-desc-cell">{a.description || '—'}</td>
                        <td>{a.isurgent ? t('admin.yes') : t('admin.no')}</td>
                        <td>{managerName(a.managed_by_user_id)}</td>
                        <td className="admin-actions">
                          <button
                            type="button"
                            className="admin-btn"
                            onClick={() => startEdit(a)}
                          >
                            {t('admin.edit')}
                          </button>
                        </td>
                      </>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {toast && (
        <div className="admin-toast" role="status">
          {toast}
        </div>
      )}

      <ConfirmDialog
        open={!!confirmState}
        message={confirmState?.message}
        confirmLabel={t('admin.leave_anyway')}
        cancelLabel={t('admin.stay')}
        onConfirm={confirmState?.onConfirm}
        onCancel={confirmState?.onCancel}
      />
    </div>
  );
};

export default AdminView;
