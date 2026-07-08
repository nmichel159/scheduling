import './Header.css';

const Header = ({ onToggle }) => {
  return (
    <header className="header">
      <button className="menu-btn" onClick={onToggle}>☰</button>
      <span className="header-title">Scheduling</span>
    </header>
  );
};

export default Header;