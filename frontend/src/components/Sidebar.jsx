import { NavLink, useNavigate } from 'react-router-dom';
import logo from '../assets/logo.jpg';
import './Sidebar.css';

const Sidebar = ({ open, onToggle }) => {
  const navigate = useNavigate();

  const logout = () => {
    localStorage.removeItem('user');
    navigate('/');
  };

  return (
    <aside className={`sidebar ${open ? 'is-open' : ''}`}>
      <button className="logo-btn" onClick={onToggle}
              title={open ? 'Zatvoriť menu' : 'Otvoriť menu'}>
        <img src={logo} alt="UPJŠ" className="logo-img" />
        <span className="toggle-icon">{open ? '◀' : '▶'}</span>
      </button>

      <nav className="sidebar-nav">
        <NavLink to="/dashboard" className="nav-item">
          <span className="icon">📅</span><span className="label">Dashboard</span>
        </NavLink>
        <NavLink to="/settings" className="nav-item">
          <span className="icon">⚙️</span><span className="label">Nastavenia</span>
        </NavLink>
      </nav>

      <button className="user-avatar" onClick={logout}>
        <span className="icon">👤</span><span className="label">Odhlásiť</span>
      </button>
    </aside>
  );
};

export default Sidebar;