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
        <div className="nav-section">
          <NavLink to="/dashboard" className="nav-item">
            <span className="icon">🏠</span><span className="label">{t('sidebar.dashboard')}</span>
          </NavLink>
        </div>

        {hasEmployee && (
          <div className="nav-section">
            <div className="nav-section-title">
              <span className="label">{t('sidebar.section_employee')}</span>
            </div>
            <NavLink to="/schedule" className="nav-item">
              <span className="icon">🗓️</span><span className="label">{t('sidebar.schedule')}</span>
            </NavLink>
            <NavLink to="/workload" className="nav-item">
              <span className="icon">📋</span><span className="label">{t('sidebar.workload')}</span>
            </NavLink>
          </div>
        )}

        {hasManager && (
          <div className="nav-section">
            <div className="nav-section-title">
              <span className="label">{t('sidebar.section_manager')}</span>
            </div>
            <NavLink to="/ambulances/schedule" className="nav-item">
              <span className="icon">📅</span><span className="label">{t('sidebar.ambulance_schedule')}</span>
            </NavLink>
            <NavLink to="/ambulances/workload" className="nav-item">
              <span className="icon">📋</span><span className="label">{t('sidebar.employee_workload')}</span>
            </NavLink>
            <NavLink to="/departments" className="nav-item">
              <span className="icon">🏥</span><span className="label">{t('sidebar.departments')}</span>
            </NavLink>
          </div>
        )}

        {hasAdmin && (
          <div className="nav-section">
            <div className="nav-section-title">
              <span className="label">{t('sidebar.section_admin')}</span>
            </div>
            <NavLink to="/admin" className="nav-item">
              <span className="icon">🛠️</span><span className="label">{t('sidebar.admin')}</span>
            </NavLink>
            <NavLink to="/roles" className="nav-item">
              <span className="icon">👥</span><span className="label">{t('sidebar.roles')}</span>
            </NavLink>
          </div>
        )}
      </nav>

      <button className="user-avatar" onClick={logout}>
        <span className="icon">👤</span><span className="label">{t('sidebar.logout')}</span>
      </button>
    </aside>
  );
};

export default Sidebar;