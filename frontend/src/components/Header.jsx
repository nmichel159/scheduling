import { useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import WorkplaceSwitcher from './WorkplaceSwitcher';
import { isWorkplaceScopedPath } from '../router/workplaceScope';
import './Header.css';

const Header = ({ onToggle }) => {
  const { t } = useTranslation();
  const { pathname } = useLocation();

  // Only the scheduler screens are scoped to one workplace; everywhere else
  // the switcher would suggest a choice that changes nothing on the page.
  const showWorkplace = isWorkplaceScopedPath(pathname);

  return (
    <header className={`header ${showWorkplace ? 'has-workplace' : ''}`}>
      <div className="header-left">
        <button className="menu-btn" onClick={onToggle}>☰</button>
        <span className="header-title">{t('app_title')}</span>
      </div>
      {/* Centred against the bar, not against the title: the empty third
          column is what keeps it there when the title changes length. */}
      {showWorkplace && <WorkplaceSwitcher />}
      {showWorkplace && <div className="header-right" aria-hidden="true" />}
    </header>
  );
};

export default Header;
