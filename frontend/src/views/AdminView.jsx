import { useState, useEffect, useCallback, useId, useMemo, useRef } from 'react';
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
import Toast from '../components/Toast';
import { useToast } from '../hooks/useToast';
import { ChevronDownIcon, CloseIcon, PlusIcon, TrashIcon } from '../components/NavIcons';
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
const MANAGER_ROLE_CODES = new Set(['LEADER', 'AMBULANCE_OVERSEER', 'ANALYST']);

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
const ManagerAutocomplete = ({
  managers,
  value,
  onChange,
  placeholder,
  emptyLabel,
  clearLabel,
  inputId,
}) => {
  const listId = useId();
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

  const pick = (manager) => {
    onChange(String(manager.id));
    setQuery('');
    setHighlight(0);
    setOpen(false);
  };

  const clear = () => {
    onChange('');
    setQuery('');
    setHighlight(0);
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
    } else if (e.key === 'Escape' && open) {
      // Zavrie len zoznam, nie celý dialóg okolo neho.
      e.stopPropagation();
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
          id={inputId}
          type="text"
          className="admin-autocomplete-input"
          value={open ? query : selected ? displayName(selected) : query}
          placeholder={placeholder}
          onChange={(e) => {
            setQuery(e.target.value);
            setHighlight(0);
            setOpen(true);
          }}
          onFocus={() => {
            setQuery('');
            setHighlight(0);
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
          aria-controls={open ? listId : undefined}
          aria-activedescendant={
            open && filtered[highlight] ? `${listId}-${filtered[highlight].id}` : undefined
          }
        />
        {selected && !open && (
          <button
            type="button"
            className="admin-autocomplete-clear"
            title={clearLabel}
            aria-label={clearLabel}
            onClick={clear}
          >
            <CloseIcon className="" />
          </button>
        )}
      </div>

      {open && (
        <ul className="admin-autocomplete-list" role="listbox" id={listId}>
          {filtered.length === 0 ? (
            <li className="admin-autocomplete-empty" role="presentation">
              {emptyLabel}
            </li>
          ) : (
            filtered.map((m, i) => (
              <li key={m.id} role="presentation">
                <button
                  type="button"
                  id={`${listId}-${m.id}`}
                  tabIndex={-1}
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
 *
 * Tabuľka pracovísk; nové aj existujúce pracovisko sa upravuje v jednom
 * dialógu, takže zakladanie aj úprava majú ten istý formulár — vrátane
 * našepkávača rozvrhára, ktorý úprava v riadku tabuľky predtým nemala.
 */
const AdminView = () => {
  const { t } = useTranslation();
  const dialogTitleId = useId();
  const nameInputId = useId();
  const descriptionInputId = useId();
  const managerInputId = useId();

  const [ambulances, setAmbulances] = useState([]);
  const [managers, setManagers] = useState([]);

  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState(null);
  const [toast, notify] = useToast();

  const [sortKey, setSortKey] = useState('name');
  const [sortDir, setSortDir] = useState('asc');

  // null = dialóg zatvorený; { id: null } = nové pracovisko; { id } = úprava.
  const [editor, setEditor] = useState(null);
  const [draft, setDraft] = useState(emptyDraft);
  const [saving, setSaving] = useState(false);
  // Kam vrátiť fokus po zatvorení dialógu (tlačidlo, ktoré ho otvorilo).
  const returnFocusRef = useRef(null);

  const [confirmState, setConfirmState] = useState(null);

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
      if (managerId == null) return null;
      const manager = managers.find((m) => m.id === managerId);
      return manager ? displayName(manager) : null;
    },
    [managers]
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
          return (managerName(a.managed_by_user_id) || t('admin.no_manager')).toLowerCase();
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
  }, [ambulances, sortKey, sortDir, managerName, t]);

  /* ---------- editor dialog ---------- */

  const openEditor = (ambulance) => {
    returnFocusRef.current = document.activeElement;
    if (ambulance) {
      setEditor({ id: ambulance.id, name: ambulance.name });
      setDraft({
        name: ambulance.name || '',
        description: ambulance.description || '',
        isurgent: !!ambulance.isurgent,
        managerId:
          ambulance.managed_by_user_id != null ? String(ambulance.managed_by_user_id) : '',
      });
    } else {
      setEditor({ id: null });
      setDraft(emptyDraft);
    }
  };

  const closeEditor = useCallback(() => {
    setEditor(null);
    setDraft(emptyDraft);
    returnFocusRef.current?.focus?.();
  }, []);

  // Escape zatvorí dialóg — ale nie, kým je nad ním otvorené potvrdenie
  // zmazania (to má vlastný Escape) alebo kým sa ukladá.
  useEffect(() => {
    if (!editor) return undefined;
    const onKeyDown = (e) => {
      if (e.key === 'Escape' && !confirmState && !saving) closeEditor();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [editor, confirmState, saving, closeEditor]);

  const submitEditor = async (e) => {
    e.preventDefault();
    if (!editor || !draft.name.trim() || saving) return;
    setSaving(true);
    try {
      if (editor.id == null) {
        // Backend (POST /ambulances) prijíma manager_id priamo v tele požiadavky
        // a overí ho cez _validate_manager(), takže ambulancia aj jej manažér
        // vzniknú v jednej atomickej operácii — netreba druhý PUT.
        await createAmbulance({
          name: draft.name.trim(),
          description: draft.description.trim() || null,
          isurgent: draft.isurgent,
          managerId: draft.managerId === '' ? null : Number(draft.managerId),
        });
        notify(t('admin.created'));
      } else {
        const id = editor.id;
        const original = ambulances.find((a) => a.id === id);
        const originalManagerId = original?.managed_by_user_id ?? null;
        const newManagerId = draft.managerId === '' ? null : Number(draft.managerId);

        await updateAmbulance(id, {
          name: draft.name.trim(),
          description: draft.description.trim() || null,
          isurgent: draft.isurgent,
        });

        if (newManagerId !== originalManagerId) {
          if (newManagerId == null) {
            await removeManagerFromAmbulance(id);
          } else {
            await assignManagerToAmbulance(id, newManagerId);
          }
        }
        notify(t('admin.saved'));
      }
      closeEditor();
      await load();
    } catch {
      notify(t('admin.action_error'));
    } finally {
      setSaving(false);
    }
  };

  /* ---------- delete ---------- */

  const askDelete = () => {
    if (!editor || editor.id == null) return;
    const { id, name } = editor;
    setConfirmState({
      message: t('admin.confirm_delete_named', { name }),
      onConfirm: async () => {
        setConfirmState(null);
        setSaving(true);
        try {
          await deleteAmbulance(id);
          notify(t('admin.deleted'));
          closeEditor();
          await load();
        } catch {
          notify(t('admin.action_error'));
        } finally {
          setSaving(false);
        }
      },
      onCancel: () => setConfirmState(null),
    });
  };

  /* ---------- render ---------- */

  const sortHeader = (key, label, className = '') => {
    const active = sortKey === key;
    return (
      <th
        className={className}
        aria-sort={active ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
      >
        <button
          type="button"
          className={`admin-sort${active ? ' is-active' : ''}`}
          onClick={() => toggleSort(key)}
        >
          {label}
          <ChevronDownIcon
            className={`admin-sort-icon${active && sortDir === 'asc' ? ' is-asc' : ''}`}
          />
        </button>
      </th>
    );
  };

  if (loading && ambulances.length === 0 && !error) {
    return (
      <div className="page admin">
        <div className="empty-state">
          <span className="spinner" aria-hidden="true" />
          {t('admin.loading')}
        </div>
      </div>
    );
  }

  if (forbidden) {
    return (
      <div className="page admin">
        <header className="page-header">
          <h1 className="page-title">{t('admin.title')}</h1>
        </header>
        <div className="alert alert-warning">{t('admin.forbidden')}</div>
      </div>
    );
  }

  const isNew = editor?.id == null;

  return (
    <div className="page admin">
      <header className="page-header">
        <div>
          <h1 className="page-title">{t('admin.title')}</h1>
        </div>
        <div className="page-actions">
          <button type="button" className="btn btn-primary" onClick={() => openEditor(null)}>
            <PlusIcon className="" />
            {t('admin.create_title')}
          </button>
        </div>
      </header>

      {error && (
        <div className="alert alert-danger admin-alert" role="alert">
          <span>{error}</span>
          <button type="button" className="alert-action" onClick={load}>
            {t('dashboard.retry')}
          </button>
        </div>
      )}

      {ambulances.length === 0 ? (
        !error && (
          <div className="card empty-state">
            <span className="empty-state-title">{t('admin.no_ambulances')}</span>
          </div>
        )
      ) : (
        <div className={`card admin-card ${loading ? 'is-loading' : ''}`}>
          <div className="admin-table-scroll">
            <table className="data-table admin-table">
              <thead>
                <tr>
                  {sortHeader('name', t('admin.col_name'))}
                  {sortHeader('description', t('admin.col_description'), 'admin-col-description')}
                  {sortHeader('isurgent', t('admin.col_urgent'), 'admin-col-urgent')}
                  {sortHeader('manager', t('admin.col_manager'))}
                  <th className="admin-col-actions">
                    <span className="visually-hidden">{t('admin.col_actions')}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {sortedAmbulances.map((a) => {
                  const manager = managerName(a.managed_by_user_id);
                  return (
                    <tr key={a.id}>
                      <td className="admin-name">{a.name}</td>
                      <td className="admin-col-description">
                        <span className="admin-desc" title={a.description || undefined}>
                          {a.description || <span className="admin-muted">—</span>}
                        </span>
                      </td>
                      <td className="admin-col-urgent">
                        {a.isurgent ? (
                          <span className="badge badge-warning">{t('admin.yes')}</span>
                        ) : (
                          <span className="admin-muted">{t('admin.no')}</span>
                        )}
                      </td>
                      <td>
                        {manager || <span className="admin-muted">{t('admin.no_manager')}</span>}
                      </td>
                      <td className="admin-col-actions">
                        <button
                          type="button"
                          className="btn btn-sm"
                          onClick={() => openEditor(a)}
                          aria-label={`${t('admin.edit')}: ${a.name}`}
                        >
                          {t('admin.edit')}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Inline rather than portaled: ConfirmDialog (delete) renders inline
          after it and has to land on top of it. */}
      {editor && (
        <div
          className="dialog-overlay"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget && !saving) closeEditor();
          }}
        >
          <form
            className="dialog admin-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby={dialogTitleId}
            onSubmit={submitEditor}
          >
            <div className="dialog-header">
              <h2 className="dialog-title" id={dialogTitleId}>
                {isNew ? t('admin.create_title') : t('admin.edit_title')}
              </h2>
              <button
                type="button"
                className="dialog-close"
                onClick={closeEditor}
                aria-label={t('admin.close')}
                title={t('admin.close')}
              >
                <CloseIcon className="" />
              </button>
            </div>

            <div className="dialog-body admin-dialog-body">
              <div className="field">
                <label className="field-label" htmlFor={nameInputId}>
                  {t('admin.name')}
                </label>
                <input
                  id={nameInputId}
                  className="input"
                  type="text"
                  value={draft.name}
                  placeholder={t('admin.name_placeholder')}
                  onChange={(e) => setDraft((prev) => ({ ...prev, name: e.target.value }))}
                  required
                  autoFocus
                />
              </div>

              <div className="field">
                <label className="field-label" htmlFor={descriptionInputId}>
                  {t('admin.description')}
                </label>
                <input
                  id={descriptionInputId}
                  className="input"
                  type="text"
                  value={draft.description}
                  placeholder={t('admin.description_placeholder')}
                  onChange={(e) =>
                    setDraft((prev) => ({ ...prev, description: e.target.value }))
                  }
                />
              </div>

              <div className="field">
                <label className="field-label" htmlFor={managerInputId}>
                  {t('admin.manager')}
                </label>
                <ManagerAutocomplete
                  inputId={managerInputId}
                  managers={managers}
                  value={draft.managerId}
                  onChange={(id) => setDraft((prev) => ({ ...prev, managerId: id }))}
                  placeholder={t('admin.manager_placeholder')}
                  emptyLabel={t('admin.manager_no_results')}
                  clearLabel={t('admin.manager_clear')}
                />
                {managers.length === 0 && (
                  <span className="field-hint admin-hint-warn">{t('admin.manager_empty')}</span>
                )}
              </div>

              <label className="admin-checkbox">
                <input
                  type="checkbox"
                  checked={draft.isurgent}
                  onChange={(e) => setDraft((prev) => ({ ...prev, isurgent: e.target.checked }))}
                />
                <span>{t('admin.isurgent')}</span>
              </label>
            </div>

            <div className="dialog-footer">
              {!isNew && (
                <button
                  type="button"
                  className="btn btn-danger-outline admin-delete"
                  onClick={askDelete}
                  disabled={saving}
                >
                  <TrashIcon className="" />
                  {t('admin.delete')}
                </button>
              )}
              <button type="button" className="btn" onClick={closeEditor} disabled={saving}>
                {t('admin.cancel')}
              </button>
              <button
                type="submit"
                className="btn btn-primary"
                disabled={saving || !draft.name.trim()}
              >
                {isNew ? t('admin.create') : t('admin.save')}
              </button>
            </div>
          </form>
        </div>
      )}

      <Toast message={toast} />

      <ConfirmDialog
        open={!!confirmState}
        title={t('admin.delete_title')}
        message={confirmState?.message}
        confirmLabel={t('admin.leave_anyway')}
        cancelLabel={t('admin.stay')}
        tone="danger"
        onConfirm={confirmState?.onConfirm}
        onCancel={confirmState?.onCancel}
      />
    </div>
  );
};

export default AdminView;
