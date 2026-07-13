import { NavLink, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import logo from '../assets/logo.jpg';
import './Sidebar.css';

const Sidebar = ({ open, onToggle }) => {
  const navigate = useNavigate();
  const { t } = useTranslation();

  const logout = () => {
    localStorage.removeItem('user');
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
        <NavLink to="/workload" className="nav-item">
          <span className="icon">📅</span><span className="label">{t('sidebar.workload')}</span>
        </NavLink>
        <NavLink to="/departments" className="nav-item">
          <span className="icon">🏥</span><span className="label">{t('sidebar.departments')}</span>
        </NavLink>
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
