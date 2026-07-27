import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
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
import { fetchAllRoles } from '../services/roleService';
import ConfirmDialog from '../components/ConfirmDialog';
import './AdminView.css';

// Rola je "manažérska" (dá sa priradiť ako správca ambulancie), ak má level >= 2 —
// presne to overuje backend v _validate_manager().
//
// LENŽE: GET /roles vracia iba { name, index } — pole `level` v odpovedi vôbec
// nie je. Number(undefined) === NaN a NaN >= 2 je false, takže filter na
// `role.level` neprepustil ani jednu rolu, nespravilo sa ani jedno volanie
// /users/by-role a zoznam manažérov ostal prázdny.
//
// Preto tu máme dve cesty:
//   1) ak backend `level` niekedy doplní, použije sa (žiadna zmena tu netreba),
//   2) inak sa role rozpoznajú podľa kódu (`name`) — tie tri kódy sú presne tie,
//      ktoré majú v číselníku level >= 2.
const MANAGER_ROLE_CODES = new Set(['LEADER', 'AMBULANCE_OVERSEER', 'HOSPITAL_ADMIN']);

const hasLevels = (roles) => roles.some((r) => Number.isFinite(Number(r.level)));

const pickManagerRoleIds = (roles) => {
  const eligible = hasLevels(roles)
    ? roles.filter((r) => Number(r.level) >= 2)
    : roles.filter((r) => MANAGER_ROLE_CODES.has(String(r.name || r.code || '').toUpperCase()));
  // Keby sa kódy rolí v databáze volali inak, radšej skúsime všetky role a
  // používateľov odfiltrujeme až podľa toho, akú rolu naozaj majú.
  return (eligible.length ? eligible : roles).map((r) => r.index);
};

const emptyDraft = { name: '', description: '', isurgent: false, managerId: '' };

/** Zobrazovaný názov používateľa (meno, inak email). */
const displayName = (user) => user.full_name || user.email;

/**
 * Našepkávač (autocomplete) na výber manažéra.
 *
 * Prečo nie obyčajný <select>: manažérov môže byť v nemocnici desiatky až stovky
 * a admin ich potrebuje nájsť podľa mena/emailu, nie skrolovať zoznam.
 *
 * value      – id vybraného manažéra ako string ('' = nepriradený)
 * onChange   – dostane nové id ako string ('' pri zrušení výberu)
 */
const ManagerAutocomplete = ({ managers, value, onChange, placeholder, emptyLabel, clearLabel }) => {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const wrapRef = useRef(null);

  const selected = useMemo(
    () => managers.find((m) => String(m.id) === String(value)) || null,
    [managers, value]
  );

  // Zatvorenie po kliknutí mimo komponentu.
  useEffect(() => {
    if (!open) return undefined;
    const onDocMouseDown = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', onDocMouseDown);
    return () => document.removeEventListener('mousedown', onDocMouseDown);
  }, [open]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return managers;
    return managers.filter(
      (m) =>
        (m.full_name || '').toLowerCase().includes(q) ||
        (m.email || '').toLowerCase().includes(q)
    );
  }, [managers, query]);

  useEffect(() => {
    setHighlight(0);
  }, [query, open]);

  const pick = (manager) => {
    onChange(String(manager.id));
    setQuery('');
    setOpen(false);
  };

  const clear = () => {
    onChange('');
    setQuery('');
    setOpen(false);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setOpen(true);
      setHighlight((h) => Math.min(h + 1, filtered.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === 'Enter') {
      // Dôležité: formulár nesmie odoslať pri potvrdzovaní návrhu.
      if (open && filtered[highlight]) {
        e.preventDefault();
        pick(filtered[highlight]);
      }
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  };

  return (
    <div className="admin-autocomplete" ref={wrapRef}>
      <div className={`admin-autocomplete-control${selected ? ' is-selected' : ''}`}>
        {/*
          Chrome ignoruje autoComplete="off" na poliach, ktoré vyzerajú ako meno
          alebo email, a napcháva sem uložené adresy ("Manage addresses...").
          Jediná hodnota, ktorú spoľahlivo rešpektuje, je "new-password";
          data-lpignore / data-form-type vypínajú LastPass a 1Password.
          role="combobox" zároveň prehliadaču povie, že si zoznam riadime sami.
        */}
        <input
          type="text"
          className="admin-autocomplete-input"
          value={open ? query : selected ? displayName(selected) : query}
          placeholder={placeholder}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => {
            setQuery('');
            setOpen(true);
          }}
          onKeyDown={handleKeyDown}
          name="ambulance-manager-search"
          autoComplete="new-password"
          autoCorrect="off"
          autoCapitalize="off"
          spellCheck={false}
          data-lpignore="true"
          data-form-type="other"
          role="combobox"
          aria-expanded={open}
          aria-autocomplete="list"
        />
        {selected && !open && (
          <button
            type="button"
            className="admin-autocomplete-clear"
            title={clearLabel}
            aria-label={clearLabel}
            onClick={clear}
          >
            ×
          </button>
        )}
      </div>

      {open && (
        <ul className="admin-autocomplete-list" role="listbox">
          {filtered.length === 0 ? (
            <li className="admin-autocomplete-empty">{emptyLabel}</li>
          ) : (
            filtered.map((m, i) => (
              <li key={m.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={String(m.id) === String(value)}
                  className={`admin-autocomplete-option${i === highlight ? ' is-active' : ''}${
                    String(m.id) === String(value) ? ' is-picked' : ''
                  }`}
                  onMouseEnter={() => setHighlight(i)}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => pick(m)}
                >
                  <span className="admin-autocomplete-name">{displayName(m)}</span>
                  {m.full_name && m.email && (
                    <span className="admin-autocomplete-mail">{m.email}</span>
                  )}
                </button>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
};

/**
 * Ambulance administration view for Role 3+ (AMBULANCE_OVERSEER).
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
      const [amb, allRoles] = await Promise.all([fetchAllAmbulances(), fetchAllRoles()]);
      setAmbulances(amb);

      const managerRoleIds = pickManagerRoleIds(allRoles);
      const managerRoleIdSet = new Set(managerRoleIds.map(Number));

      // .catch(() => []) je dôležité: keby jedna rola medzitým zmizla, vrátil by
      // /users/by-role 404 a Promise.all by zamietol celý load() — presne to
      // hlásenie "Nepodarilo sa načítať ambulancie" a prázdna obrazovka.
      const roleResults = await Promise.all(
        managerRoleIds.map((id) => fetchUsersByRole(id).catch(() => []))
      );

      // Merge + dedupe. Filter na roles[] je poistka pre prípad, že sme museli
      // stiahnuť používateľov všetkých rolí — bežných zamestnancov tu nechceme.
      const merged = new Map();
      roleResults.flat().forEach((u) => merged.set(u.id, u));

      const isManagerUser = (u) => {
        if (!Array.isArray(u.roles) || u.roles.length === 0) return true;
        return u.roles.some(
          (r) =>
            managerRoleIdSet.has(Number(r.id)) ||
            MANAGER_ROLE_CODES.has(String(r.code || '').toUpperCase())
        );
      };

      const sortedManagers = Array.from(merged.values())
        .filter(isManagerUser)
        .sort((a, b) => displayName(a).localeCompare(displayName(b)));
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
      return manager ? displayName(manager) : t('admin.no_manager');
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
      // Backend (POST /ambulances) prijíma manager_id priamo v tele požiadavky
      // a overí ho cez _validate_manager(), takže ambulancia aj jej manažér
      // vzniknú v jednej atomickej operácii — netreba druhý PUT.
      await createAmbulance({
        name: createDraft.name.trim(),
        description: createDraft.description.trim() || null,
        isurgent: createDraft.isurgent,
        managerId: createDraft.managerId === '' ? null : Number(createDraft.managerId),
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

          {/* Výber manažéra už pri zakladaní ambulancie. */}
          <div className="admin-form-row">
            <div className="admin-form-field admin-form-field-manager">
              <span>{t('admin.manager')}</span>
              <ManagerAutocomplete
                managers={managers}
                value={createDraft.managerId}
                onChange={(id) => setCreateDraft((prev) => ({ ...prev, managerId: id }))}
                placeholder={t('admin.manager_placeholder')}
                emptyLabel={t('admin.manager_no_results')}
                clearLabel={t('admin.manager_clear')}
              />
              {managers.length === 0 && (
                <small className="admin-form-hint is-warn">{t('admin.manager_empty')}</small>
              )}
            </div>
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
                                {displayName(m)}
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