import { useTranslation } from 'react-i18next';
import './Header.css';

const Header = ({ onToggle }) => {
  const { t } = useTranslation();
  return (
    <header className="header">
      <button className="menu-btn" onClick={onToggle}>☰</button>
      <span className="header-title">{t('app_title')}</span>
    </header>
  );
};

export default Header;