import { NavLink, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useRoles } from '../hooks/useRoles';
import client from '../api/client';
import logo from '../assets/logo.jpg';
import './Sidebar.css';

const Sidebar = ({ open, onToggle }) => {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { hasEmployee, hasManager, hasAdmin } = useRoles();

  const logout = async () => {
    try {
      await client.post('/auth/logout');
    } catch {
      // The local browser state must be cleared even if the session expired.
    }
    localStorage.removeItem('user');
    localStorage.removeItem('roles');
    localStorage.removeItem('sidebarOpen');
    navigate('/');
  };

  return (
    <aside className={`sidebar ${open ? 'is-open' : ''}`}>
      <button className="logo-btn" onClick={onToggle}
              title={open ? t('sidebar.close_menu') : t('sidebar.open_menu')}>
        <img src={logo} alt="UPJŠ" className="logo-img" />
        <span className="toggle-icon">{open ? '◀' : '▶'}</span>
      </button>

      <nav className="sidebar-nav">
        <NavLink to="/dashboard" className="nav-item">
          <span className="icon">🏠</span><span className="label">{t('sidebar.dashboard')}</span>
        </NavLink>
        {hasEmployee && (
          <NavLink to="/schedule" className="nav-item">
            <span className="icon">🗓️</span><span className="label">{t('sidebar.schedule')}</span>
          </NavLink>
        )}
        {hasManager && (
          <NavLink to="/ambulances/schedule" className="nav-item">
            <span className="icon">📅</span><span className="label">{t('sidebar.ambulance_schedule')}</span>
          </NavLink>
        )}
        {hasEmployee && (
          <NavLink to="/workload" className="nav-item">
            <span className="icon">📋</span><span className="label">{t('sidebar.workload')}</span>
          </NavLink>
        )}
        {hasManager && (
          <NavLink to="/departments" className="nav-item">
            <span className="icon">🏥</span><span className="label">{t('sidebar.departments')}</span>
          </NavLink>
        )}
        {hasAdmin && (
          <NavLink to="/admin" className="nav-item">
            <span className="icon">🛠️</span><span className="label">{t('sidebar.admin')}</span>
          </NavLink>
        )}
        <NavLink to="/settings" className="nav-item">
          <span className="icon">⚙️</span><span className="label">{t('sidebar.settings')}</span>
        </NavLink>
      </nav>

      <button className="user-avatar" onClick={logout}>
        <span className="icon">👤</span><span className="label">{t('sidebar.logout')}</span>
      </button>
    </aside>
  );
};

export default Sidebar;
