import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { landingPathFor, storeRoles } from '../hooks/useRoles';
import {
  fetchMyRoles,
  fetchRoleAssignments,
  updateUserRoles,
} from '../services/roleService';
import { personInitials } from '../utils/personInitials';
import './RoleManagementView.css';

const MANAGED_ROLES = [
  { id: 1, key: 'employee' },
  { id: 2, key: 'leader' },
  { id: 3, key: 'overseer' },
];

const roleIdsOf = (user) => user.roles
  .map((role) => role.id)
  .filter((roleId) => roleId <= 3)
  .sort((a, b) => a - b);

const sameIds = (left, right) => (
  left.length === right.length && left.every((id, index) => id === right[index])
);

const RoleManagementView = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [users, setUsers] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState(null);
  const [message, setMessage] = useState(null);

  const load = async () => {
    setLoading(true);
    setMessage(null);
    try {
      const result = await fetchRoleAssignments();
      setUsers(result);
      setDrafts(Object.fromEntries(result.map((user) => [user.id, roleIdsOf(user)])));
    } catch (error) {
      setMessage({
        type: 'error',
        text: error.response?.status === 403
          ? t('role_management.forbidden')
          : t('role_management.load_error'),
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const visibleUsers = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    if (!query) return users;
    return users.filter((user) => (
      `${user.full_name || ''} ${user.email}`.toLocaleLowerCase().includes(query)
    ));
  }, [search, users]);

  const toggleRole = (userId, roleId) => {
    setMessage(null);
    setDrafts((current) => {
      const selected = new Set(current[userId] || []);
      if (selected.has(roleId)) selected.delete(roleId);
      else selected.add(roleId);
      return { ...current, [userId]: [...selected].sort((a, b) => a - b) };
    });
  };

  const save = async (user) => {
    setSavingId(user.id);
    setMessage(null);
    try {
      const updated = await updateUserRoles(user.id, drafts[user.id] || []);
      setUsers((current) => current.map((item) => item.id === user.id ? updated : item));
      setDrafts((current) => ({ ...current, [user.id]: roleIdsOf(updated) }));
      setMessage({
        type: 'success',
        text: t('role_management.saved_for', {
          name: updated.full_name || updated.email,
        }),
      });

      const signedInUser = JSON.parse(localStorage.getItem('user') || 'null');
      if (signedInUser?.id === user.id) {
        const myRoles = await fetchMyRoles();
        storeRoles(myRoles);
        const stillAdmin = myRoles.some((role) => (
          role.name === 'AMBULANCE_OVERSEER' || role.name === 'ANALYST'
        ));
        if (!stillAdmin) navigate(landingPathFor(myRoles), { replace: true });
      }
    } catch (error) {
      setMessage({
        type: 'error',
        text: error.response?.status === 403
          ? t('role_management.forbidden')
          : t('role_management.save_error'),
      });
    } finally {
      setSavingId(null);
    }
  };

  return (
    <div className="page role-management">
      <header className="page-header">
        <div>
          <h1 className="page-title">{t('role_management.title')}</h1>
        </div>
        <div className="page-actions role-management-search">
          <label className="visually-hidden" htmlFor="role-management-search">
            {t('role_management.search')}
          </label>
          <input
            id="role-management-search"
            className="input search-input"
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t('role_management.search')}
          />
        </div>
      </header>

      {message && (
        <div
          className={`alert ${message.type === 'error' ? 'alert-danger' : 'alert-success'} role-management-message`}
          role={message.type === 'error' ? 'alert' : 'status'}
        >
          {message.text}
        </div>
      )}

      {loading ? (
        <div className="card empty-state">
          <span className="spinner" aria-hidden="true" />
          {t('role_management.loading')}
        </div>
      ) : visibleUsers.length === 0 ? (
        <div className="card empty-state">{t('role_management.empty')}</div>
      ) : (
        <ul className="card role-management-list">
          {visibleUsers.map((user) => {
            const original = roleIdsOf(user);
            const selected = drafts[user.id] || [];
            const dirty = !sameIds(original, selected);
            const saving = savingId === user.id;

            return (
              <li className="role-management-row" key={user.id}>
                <div className="role-management-person">
                  <span className="role-management-avatar" aria-hidden="true">
                    {personInitials(user.full_name || user.email)}
                  </span>
                  <span className="role-management-identity">
                    <strong>{user.full_name || t('role_management.unnamed')}</strong>
                    <small>{user.email}</small>
                  </span>
                </div>

                <div
                  className="role-management-options"
                  role="group"
                  aria-label={user.full_name || user.email}
                >
                  {MANAGED_ROLES.map((role) => (
                    <label className="role-management-option" key={role.id}>
                      <input
                        type="checkbox"
                        checked={selected.includes(role.id)}
                        disabled={saving}
                        onChange={() => toggleRole(user.id, role.id)}
                      />
                      <span className="role-management-role-number">{role.id}</span>
                      <span className="role-management-role-name">
                        {t(`role_management.${role.key}`)}
                      </span>
                    </label>
                  ))}
                </div>

                {/* Only a row with unsaved changes offers to save; the slot
                    keeps its width either way, so the rows stay aligned. */}
                <button
                  type="button"
                  className={`btn btn-sm btn-primary role-management-save${
                    dirty || saving ? '' : ' is-idle'
                  }`}
                  disabled={!dirty || saving}
                  onClick={() => save(user)}
                >
                  {saving ? t('role_management.saving') : t('role_management.save')}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
};

export default RoleManagementView;
