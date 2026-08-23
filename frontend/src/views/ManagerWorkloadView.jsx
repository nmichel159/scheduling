import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { storeRoles } from '../hooks/useRoles';
import {
  fetchMyRoles,
  fetchRoleAssignments,
  updateUserRoles,
} from '../services/roleService';
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
          role.name === 'AMBULANCE_OVERSEER' || role.name === 'HOSPITAL_ADMIN'
        ));
        if (!stillAdmin) navigate('/dashboard', { replace: true });
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
    <section className="role-management">
      <div className="role-management-heading">
        <div>
          <h1>{t('role_management.title')}</h1>
          <p>{t('role_management.subtitle')}</p>
        </div>
        <label className="role-management-search">
          <span className="sr-only">{t('role_management.search')}</span>
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t('role_management.search')}
          />
        </label>
      </div>

      <div className="role-management-legend">
        {MANAGED_ROLES.map((role) => (
          <span key={role.id}>
            <strong>{role.id}</strong> {t(`role_management.${role.key}`)}
          </span>
        ))}
      </div>

      {message && (
        <div className={`role-management-message is-${message.type}`} role="status">
          {message.text}
        </div>
      )}

      {loading ? (
        <p className="role-management-state">{t('role_management.loading')}</p>
      ) : visibleUsers.length === 0 ? (
        <p className="role-management-state">{t('role_management.empty')}</p>
      ) : (
        <div className="role-management-list">
          {visibleUsers.map((user) => {
            const original = roleIdsOf(user);
            const selected = drafts[user.id] || [];
            const dirty = !sameIds(original, selected);

            return (
              <article className="role-management-card" key={user.id}>
                <div className="role-management-person">
                  <span className="role-management-identity">
                    <strong>{user.full_name || t('role_management.unnamed')}</strong>
                    <small>{user.email}</small>
                  </span>
                </div>

                <div className="role-management-options">
                  {MANAGED_ROLES.map((role) => (
                    <label className="role-management-option" key={role.id}>
                      <input
                        type="checkbox"
                        checked={selected.includes(role.id)}
                        disabled={savingId === user.id}
                        onChange={() => toggleRole(user.id, role.id)}
                      />
                      <span className="role-management-role-number">{role.id}</span>
                      <span>{t(`role_management.${role.key}`)}</span>
                    </label>
                  ))}
                </div>

                <button
                  type="button"
                  className="role-management-save"
                  disabled={!dirty || savingId === user.id}
                  onClick={() => save(user)}
                >
                  {savingId === user.id
                    ? t('role_management.saving')
                    : t('role_management.save')}
                </button>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
};

export default RoleManagementView;