import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useRoles } from '../hooks/useRoles';
import { useMediaQuery, DESKTOP_QUERY } from '../hooks/useMediaQuery';
import ConfirmDialog from './ConfirmDialog';
import QuickJump from './QuickJump';
import SettingsDialog from './SettingsDialog';
import {
  AdminIcon,
  ChevronLeftIcon,
  HomeIcon,
  LimitsIcon,
  LogoutIcon,
  MoreIcon,
  MyScheduleIcon,
  RolesIcon,
  ScheduleOverviewIcon,
  SearchIcon,
  StatisticsIcon,
  SettingsIcon,
  TeamLimitsIcon,
  TeamScheduleIcon,
  WorkplaceIcon,
} from './NavIcons';
import client from '../api/client';
import logo from '../assets/logo.jpg';
import './Sidebar.css';

/** Šírka zbalenej lišty (railu) — musí sedieť s .sidebar v Sidebar.css. */
const RAIL_WIDTH = 56;

/**
 * Sekcie podľa rolí. `Icon` sekcie je ikona, ktorá ju zastupuje v raile;
 * `flag` je príznak z useRoles().
 */
const SECTIONS = [
  {
    id: 'employee',
    flag: 'hasEmployee',
    titleKey: 'sidebar.section_employee',
    Icon: MyScheduleIcon,
    items: [
      { to: '/schedule', labelKey: 'sidebar.schedule', Icon: MyScheduleIcon },
      { to: '/workload', labelKey: 'sidebar.workload', Icon: LimitsIcon },
    ],
  },
  {
    id: 'manager',
    flag: 'hasManager',
    titleKey: 'sidebar.section_manager',
    Icon: WorkplaceIcon,
    items: [
      { to: '/ambulances/schedule', labelKey: 'sidebar.ambulance_schedule', Icon: TeamScheduleIcon },
      { to: '/ambulances/workload', labelKey: 'sidebar.employee_workload', Icon: TeamLimitsIcon },
      { to: '/departments', labelKey: 'sidebar.departments', Icon: WorkplaceIcon },
    ],
  },
  {
    id: 'admin',
    flag: 'hasAdmin',
    titleKey: 'sidebar.section_admin',
    Icon: AdminIcon,
    items: [
      {
        to: '/schedules/overview',
        labelKey: 'sidebar.schedule_overview',
        Icon: ScheduleOverviewIcon,
      },
      { to: '/admin', labelKey: 'sidebar.admin', Icon: AdminIcon },
      { to: '/roles', labelKey: 'sidebar.roles', Icon: RolesIcon },
    ],
  },
  // Its own section rather than an item inside 'admin': level 4 is a separate
  // tier, and a section is the only granularity this list filters by.
  {
    id: 'analyst',
    flag: 'hasAnalyst',
    titleKey: 'sidebar.section_analyst',
    Icon: StatisticsIcon,
    items: [
      { to: '/statistics', labelKey: 'sidebar.statistics', Icon: StatisticsIcon },
    ],
  },
];

const readStoredUser = () => {
  try {
    return JSON.parse(localStorage.getItem('user')) || null;
  } catch {
    return null;
  }
};

/** "MUDr. Eva Kováčová" -> "EK"; tituly s bodkou sa preskakujú. */
const initialsOf = (user) => {
  const words = (user?.full_name || '').split(/\s+/).filter((w) => w && !w.endsWith('.'));
  if (words.length) {
    return words.slice(0, 2).map((w) => w[0]).join('').toUpperCase();
  }
  return (user?.email || '?').slice(0, 2).toUpperCase();
};

const isItemActive = (pathname, to) => pathname === to || pathname.startsWith(`${to}/`);

const Sidebar = ({ open, onToggle, onClose }) => {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { t } = useTranslation();
  const { hasEmployee, hasManager, hasAdmin, hasAnalyst } = useRoles();
  const isDesktop = useMediaQuery(DESKTOP_QUERY);

  /** Rail = zbalená lišta na desktope. Rozbalená lišta aj mobil vypisujú všetky položky. */
  const railMode = isDesktop && !open;

  const [flyout, setFlyout] = useState(null);      // { id, top } — otvorená sekcia v raile
  const [userMenu, setUserMenu] = useState(null);  // { bottom } | true pri vypísanom menu
  const [quickJumpOpen, setQuickJumpOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [logoutAsked, setLogoutAsked] = useState(false);

  const closeTimer = useRef(null);
  const user = useMemo(readStoredUser, []);

  const sections = useMemo(() => {
    const allowed = { hasEmployee, hasManager, hasAdmin, hasAnalyst };
    return SECTIONS.filter((section) => allowed[section.flag]).map((section) => ({
      ...section,
      title: t(section.titleKey),
      items: section.items.map((item) => ({ ...item, label: t(item.labelKey) })),
    }));
  }, [hasEmployee, hasManager, hasAdmin, hasAnalyst, t]);

  /** Plochý zoznam pre rýchly skok — už prefiltrovaný podľa rolí. */
  const jumpItems = useMemo(
    () => [
      ...(hasEmployee
        ? [{ to: '/dashboard', label: t('sidebar.dashboard'), section: '', Icon: HomeIcon }]
        : []),
      ...sections.flatMap((section) =>
        section.items.map((item) => ({
          to: item.to,
          label: item.label,
          section: section.title,
          Icon: item.Icon,
        })),
      ),
    ],
    [sections, hasEmployee, t],
  );

  const closeMenus = useCallback(() => {
    clearTimeout(closeTimer.current);
    setFlyout(null);
    setUserMenu(null);
  }, []);

  // Po navigácii nemá čo ostať otvorené — ani fly-out, ani menu účtu.
  useEffect(() => {
    closeMenus();
  }, [pathname, closeMenus]);

  // Prepnutie rail <-> rozbalené mení spôsob vykreslenia, plávajúce panely by ostali visieť.
  useEffect(() => {
    closeMenus();
  }, [railMode, closeMenus]);

  useEffect(() => () => clearTimeout(closeTimer.current), []);

  // Ctrl/⌘ + K otvorí rýchly skok odkiaľkoľvek v aplikácii.
  useEffect(() => {
    const onKeyDown = (e) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault();
        setQuickJumpOpen((value) => !value);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const logout = async () => {
    setLogoutAsked(false);
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

  /** Na mobile je lišta overlay cez obsah — po kliku na položku musí zmiznúť. */
  const handleNavigate = () => {
    closeMenus();
    if (!isDesktop) onClose?.();
  };

  /**
   * Fly-out je position: fixed, takže ho nereže overflow railu ani scroll navigácie.
   * Pozíciu počítame z tlačidla a držíme ju v okne — panel s tromi položkami
   * otvorený pri spodnom okraji by inak vytiekol pod obrazovku.
   */
  const openFlyout = (section, element) => {
    const rect = element.getBoundingClientRect();
    const height = 34 + section.items.length * 40 + 12;
    const top = Math.max(8, Math.min(rect.top - 6, window.innerHeight - height - 12));
    clearTimeout(closeTimer.current);
    setUserMenu(null);
    setFlyout({ id: section.id, top });
  };

  const scheduleFlyoutClose = () => {
    clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(() => setFlyout(null), 160);
  };

  const toggleUserMenu = (element) => {
    if (userMenu) {
      setUserMenu(null);
      return;
    }
    setFlyout(null);
    if (railMode) {
      const rect = element.getBoundingClientRect();
      setUserMenu({ bottom: Math.max(8, window.innerHeight - rect.bottom - 4) });
    } else {
      setUserMenu({});
    }
  };

  const renderNavLink = (item, extraClass = '') => (
    <NavLink
      key={item.to}
      to={item.to}
      className={`nav-item ${extraClass}`.trim()}
      onClick={handleNavigate}
      title={railMode ? item.label : undefined}
    >
      <item.Icon />
      <span className="label">{item.label}</span>
    </NavLink>
  );

  const userMenuContent = (
    <>
      <p className="nav-menu-title">{t('sidebar.account')}</p>
      <button
        type="button"
        className="nav-menu-item"
        onClick={() => {
          setUserMenu(null);
          setSettingsOpen(true);
        }}
      >
        <SettingsIcon className="nav-icon" />
        {t('sidebar.settings')}
      </button>
      <hr className="nav-menu-divider" />
      <button
        type="button"
        className="nav-menu-item"
        onClick={() => {
          setUserMenu(null);
          setLogoutAsked(true);
        }}
      >
        <LogoutIcon className="nav-icon" />
        {t('sidebar.logout')}
      </button>
    </>
  );

  return (
    <>
      <aside className={`sidebar ${open ? 'is-open' : ''} ${railMode ? 'is-rail' : ''}`}>
        <div className="sidebar-head">
          <img src={logo} alt="UPJŠ" className="logo-img" />
          <span className="logo-title label">{t('app_title')}</span>
        </div>

        <nav className="sidebar-nav" aria-label={t('sidebar.nav_label')} onScroll={closeMenus}>
          <button
            type="button"
            className="nav-item nav-search"
            onClick={() => setQuickJumpOpen(true)}
            title={railMode ? t('sidebar.quick_jump') : undefined}
          >
            <SearchIcon />
            <span className="label">{t('sidebar.quick_jump')}</span>
            <kbd className="nav-kbd label">Ctrl K</kbd>
          </button>

          {/* Domov beží na "moje" endpointoch — je to zamestnanecká obrazovka. */}
          {hasEmployee && (
            <div className="nav-section">
              {renderNavLink({ to: '/dashboard', label: t('sidebar.dashboard'), Icon: HomeIcon })}
            </div>
          )}

          {sections.map((section) => {
            const sectionActive = section.items.some((item) => isItemActive(pathname, item.to));
            const isFlyoutOpen = flyout?.id === section.id;

            if (!railMode) {
              return (
                <div className="nav-section" key={section.id}>
                  <div className="nav-section-title">
                    <span className="label">{section.title}</span>
                  </div>
                  {section.items.map((item) => renderNavLink(item))}
                </div>
              );
            }

            return (
              <div
                className="nav-section rail-section"
                key={section.id}
                onMouseEnter={(e) => openFlyout(section, e.currentTarget.querySelector('.rail-trigger'))}
                onMouseLeave={scheduleFlyoutClose}
                onBlur={(e) => {
                  if (!e.currentTarget.contains(e.relatedTarget)) setFlyout(null);
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Escape') {
                    setFlyout(null);
                    e.currentTarget.querySelector('.rail-trigger')?.focus();
                  }
                  if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
                    e.preventDefault();
                    if (!isFlyoutOpen) {
                      openFlyout(section, e.currentTarget.querySelector('.rail-trigger'));
                    }
                    // Fly-out sa vykreslí až v ďalšom cykle, preto odložené zaostrenie.
                    const wrapper = e.currentTarget;
                    setTimeout(() => wrapper.querySelector('.nav-flyout .nav-item')?.focus(), 0);
                  }
                }}
              >
                <button
                  type="button"
                  className={`nav-item rail-trigger ${sectionActive ? 'is-current' : ''}`}
                  aria-expanded={isFlyoutOpen}
                  aria-haspopup="true"
                  title={section.title}
                  onClick={(e) => {
                    if (isFlyoutOpen) setFlyout(null);
                    else openFlyout(section, e.currentTarget);
                  }}
                >
                  <section.Icon />
                </button>

                {isFlyoutOpen && (
                  <div
                    className="nav-flyout"
                    style={{ top: flyout.top, left: RAIL_WIDTH + 6 }}
                    role="group"
                    aria-label={section.title}
                  >
                    <p className="nav-flyout-title">{section.title}</p>
                    {section.items.map((item) => (
                      <NavLink
                        key={item.to}
                        to={item.to}
                        className="nav-item"
                        onClick={handleNavigate}
                      >
                        <item.Icon />
                        <span className="flyout-label">{item.label}</span>
                      </NavLink>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </nav>

        <div className="sidebar-foot">
          <button
            type="button"
            className="nav-item nav-toggle"
            onClick={onToggle}
            aria-expanded={!railMode}
            title={railMode ? t('sidebar.open_menu') : t('sidebar.close_menu')}
          >
            <ChevronLeftIcon className={`nav-icon ${railMode ? 'is-flipped' : ''}`} />
            <span className="label">{t('sidebar.close_menu')}</span>
          </button>

          <div
            className="user-block"
            onBlur={(e) => {
              if (!e.currentTarget.contains(e.relatedTarget)) setUserMenu(null);
            }}
          >
            {userMenu && !railMode && (
              <div className="nav-menu user-menu-inline">{userMenuContent}</div>
            )}

            <button
              type="button"
              className="nav-item user-btn"
              aria-expanded={Boolean(userMenu)}
              aria-haspopup="true"
              title={user?.full_name || user?.email || t('sidebar.account')}
              onClick={(e) => toggleUserMenu(e.currentTarget)}
            >
              <span className="avatar" aria-hidden="true">{initialsOf(user)}</span>
              <span className="label user-meta">
                <b>{user?.full_name || t('sidebar.account')}</b>
                <em>{user?.email}</em>
              </span>
              <MoreIcon className="nav-icon user-more label" />
            </button>

            {userMenu && railMode && (
              <div
                className="nav-menu nav-flyout"
                style={{ bottom: userMenu.bottom, left: RAIL_WIDTH + 6 }}
              >
                {userMenuContent}
              </div>
            )}
          </div>
        </div>
      </aside>

      <QuickJump
        open={quickJumpOpen}
        items={jumpItems}
        onClose={() => setQuickJumpOpen(false)}
      />

      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />

      <ConfirmDialog
        open={logoutAsked}
        message={t('sidebar.logout_confirm')}
        confirmLabel={t('sidebar.logout')}
        cancelLabel={t('sidebar.cancel')}
        onConfirm={logout}
        onCancel={() => setLogoutAsked(false)}
      />
    </>
  );
};

export default Sidebar;
