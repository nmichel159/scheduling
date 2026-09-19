/**
 * Ikony bočnej lišty ako inline SVG.
 *
 * Emoji sa na každom systéme vykreslia inak, nedajú sa zafarbiť podľa stavu
 * a dve rôzne položky ("Obmedzenia" a "Obmedzenia zamestnancov") mali doteraz
 * rovnaký klipboard. SVG kreslí currentColor, takže ikona zdedí farbu položky
 * — vrátane aktívneho a hover stavu.
 */

const Icon = ({ className = 'nav-icon', children }) => (
  <svg
    className={className}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.6"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    {children}
  </svg>
);

export const HomeIcon = (props) => (
  <Icon {...props}>
    <path d="M4 10.6 12 4l8 6.6V19a1.4 1.4 0 0 1-1.4 1.4h-3.3v-5.2H8.7v5.2H5.4A1.4 1.4 0 0 1 4 19z" />
  </Icon>
);

/** Môj rozpis — kalendár s riadkami služieb. */
export const MyScheduleIcon = (props) => (
  <Icon {...props}>
    <rect x="3.6" y="5.2" width="16.8" height="15.2" rx="2.2" />
    <path d="M3.6 9.8h16.8M8 3.2v3.6M16 3.2v3.6M9 13.6h6M9 16.8h3.6" />
  </Icon>
);

/** Moje obmedzenia — posuvníky, teda "moje nastavenie dostupnosti". */
export const LimitsIcon = (props) => (
  <Icon {...props}>
    <path d="M4.4 7.6h15.2M4.4 12h15.2M4.4 16.4h15.2" />
    <circle cx="9" cy="7.6" r="2" fill="currentColor" stroke="none" />
    <circle cx="15" cy="12" r="2" fill="currentColor" stroke="none" />
    <circle cx="7.6" cy="16.4" r="2" fill="currentColor" stroke="none" />
  </Icon>
);

/** Rozpis pracoviska — kalendár s mriežkou zmien. */
export const TeamScheduleIcon = (props) => (
  <Icon {...props}>
    <rect x="3.6" y="5.2" width="16.8" height="15.2" rx="2.2" />
    <path d="M3.6 9.8h16.8M8 3.2v3.6M16 3.2v3.6M7.4 12.8h3.2v3.2H7.4zM13.4 12.8h3.2v3.2h-3.2z" />
  </Icon>
);

/** Obmedzenia zamestnancov — ľudia, nie posuvníky. */
export const TeamLimitsIcon = (props) => (
  <Icon {...props}>
    <circle cx="9.2" cy="8.4" r="3.3" />
    <path d="M3.4 19.8c.5-3.3 2.9-5.2 5.8-5.2s5.3 1.9 5.8 5.2" />
    <path d="M16.2 6.4a3.2 3.2 0 0 1 0 6M17.8 14.9c1.8.8 2.9 2.4 3.2 4.6" />
  </Icon>
);

export const WorkplaceIcon = (props) => (
  <Icon {...props}>
    <path d="M4.2 20.4V7.2A1.4 1.4 0 0 1 5.6 5.8H12v14.6M12 20.4V10.6h6.4a1.4 1.4 0 0 1 1.4 1.4v8.4M2.6 20.4h18.8M8.1 8.8v3.4M6.4 10.5h3.4" />
  </Icon>
);

/** Zamestnanci pracoviska — zoznam ľudí s kartičkou osoby. */
export const EmployeesIcon = (props) => (
  <Icon {...props}>
    <circle cx="8.6" cy="8.2" r="3.4" />
    <path d="M2.8 19.8c.4-3.4 2.8-5.4 5.8-5.4s5.4 2 5.8 5.4" />
    <path d="M17.4 6.4h3.8M17.4 10.2h3.8M17.4 14h3.8" />
  </Icon>
);

/** Správca kompetencií — odškrtávací zoznam schopností pracoviska. */
export const CompetenceIcon = (props) => (
  <Icon {...props}>
    <rect x="3.8" y="4.2" width="16.4" height="15.6" rx="2.2" />
    <path d="M7.2 9.2l1.6 1.6 2.6-2.8M7.2 15.2l1.6 1.6 2.6-2.8M14.4 9.6h3.2M14.4 15.6h3.2" />
  </Icon>
);

/* A calendar with one day marked: the screen is about the handful of dates
   in a year that are treated differently from the rest. */
export const SpecialDaysIcon = (props) => (
  <Icon {...props}>
    <rect x="3.6" y="5" width="16.8" height="15" rx="2.2" />
    <path d="M3.6 9.6h16.8M8 3.4v3.2M16 3.4v3.2" />
    <circle cx="15.6" cy="14.6" r="2" />
  </Icon>
);

export const AdminIcon = (props) => (
  <Icon {...props}>
    <path d="M6.8 3.6v5.2M6.8 14.4v6M17.2 3.6v8.4M17.2 17.6v2.8" />
    <circle cx="6.8" cy="11.6" r="2.6" />
    <circle cx="17.2" cy="14.8" r="2.6" />
  </Icon>
);

/** Prehlad rozvrhov — kalendar s odskrtnutym mesiacom. */
export const ScheduleOverviewIcon = (props) => (
  <Icon {...props}>
    <rect x="3.6" y="5.2" width="16.8" height="15.2" rx="2.2" />
    <path d="M3.6 9.8h16.8M8 3.2v3.6M16 3.2v3.6" />
    <path d="M8.4 15.2l2.4 2.4 4.8-4.8" />
  </Icon>
);

/** Statistiky — stlpcovy graf. */
export const StatisticsIcon = (props) => (
  <Icon {...props}>
    <path d="M3.8 20.2h16.4" />
    <rect x="5.6" y="12.4" width="3.4" height="6" rx="1" />
    <rect x="10.9" y="8.2" width="3.4" height="10.2" rx="1" />
    <rect x="16.2" y="4.6" width="3.4" height="13.8" rx="1" />
  </Icon>
);

export const RolesIcon = (props) => (
  <Icon {...props}>
    <path d="M12 3.2 5.2 5.8v5.6c0 4.2 2.7 7.6 6.8 9.4 4.1-1.8 6.8-5.2 6.8-9.4V5.8z" />
    <circle cx="12" cy="10.2" r="2.1" />
    <path d="M8.7 16.2c.6-1.8 1.8-2.7 3.3-2.7s2.7.9 3.3 2.7" />
  </Icon>
);

export const SearchIcon = (props) => (
  <Icon {...props}>
    <circle cx="10.8" cy="10.8" r="6.2" />
    <path d="M15.4 15.4 20 20" />
  </Icon>
);

export const ChevronLeftIcon = (props) => (
  <Icon {...props}>
    <path d="M14.5 6.5 9 12l5.5 5.5" />
  </Icon>
);

export const ChevronDownIcon = (props) => (
  <Icon {...props}>
    <path d="M6.5 9.5 12 15l5.5-5.5" />
  </Icon>
);

export const LogoutIcon = (props) => (
  <Icon {...props}>
    <path d="M14.4 7.6V6.2a1.8 1.8 0 0 0-1.8-1.8H6.2A1.8 1.8 0 0 0 4.4 6.2v11.6a1.8 1.8 0 0 0 1.8 1.8h6.4a1.8 1.8 0 0 0 1.8-1.8v-1.4M10.2 12h9.4m0 0-2.8-2.8M19.6 12l-2.8 2.8" />
  </Icon>
);

export const LanguageIcon = (props) => (
  <Icon {...props}>
    <circle cx="12" cy="12" r="8.2" />
    <path d="M3.9 12h16.2M12 3.9c2.1 2.4 3.2 5.1 3.2 8.1s-1.1 5.7-3.2 8.1c-2.1-2.4-3.2-5.1-3.2-8.1S9.9 6.3 12 3.9z" />
  </Icon>
);

export const MoreIcon = (props) => (
  <Icon {...props}>
    <circle cx="6" cy="12" r="1.5" fill="currentColor" stroke="none" />
    <circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none" />
    <circle cx="18" cy="12" r="1.5" fill="currentColor" stroke="none" />
  </Icon>
);

/** Nastavenia — ozubené koleso. */
export const SettingsIcon = (props) => (
  <Icon {...props}>
    <circle cx="12" cy="12" r="2.9" />
    <path d="M19.1 14.4a1.5 1.5 0 0 0 .3 1.7l.1.1a1.8 1.8 0 1 1-2.6 2.6l-.1-.1a1.5 1.5 0 0 0-1.7-.3 1.5 1.5 0 0 0-.9 1.4v.3a1.8 1.8 0 1 1-3.6 0V20a1.5 1.5 0 0 0-1-1.4 1.5 1.5 0 0 0-1.7.3l-.1.1a1.8 1.8 0 1 1-2.6-2.6l.1-.1a1.5 1.5 0 0 0 .3-1.7 1.5 1.5 0 0 0-1.4-.9H4a1.8 1.8 0 1 1 0-3.6h.1a1.5 1.5 0 0 0 1.4-1 1.5 1.5 0 0 0-.3-1.7l-.1-.1a1.8 1.8 0 1 1 2.6-2.6l.1.1a1.5 1.5 0 0 0 1.7.3h.1a1.5 1.5 0 0 0 .9-1.4V4a1.8 1.8 0 1 1 3.6 0v.1a1.5 1.5 0 0 0 .9 1.4h.1a1.5 1.5 0 0 0 1.7-.3l.1-.1a1.8 1.8 0 1 1 2.6 2.6l-.1.1a1.5 1.5 0 0 0-.3 1.7v.1a1.5 1.5 0 0 0 1.4.9h.3a1.8 1.8 0 1 1 0 3.6H20a1.5 1.5 0 0 0-1.4.9z" />
  </Icon>
);

/** Svetlý motív — slnko. */
export const SunIcon = (props) => (
  <Icon {...props}>
    <circle cx="12" cy="12" r="4.2" />
    <path d="M12 2.6v2.2M12 19.2v2.2M4.4 4.4l1.6 1.6M18 18l1.6 1.6M2.6 12h2.2M19.2 12h2.2M4.4 19.6 6 18M18 6l1.6-1.6" />
  </Icon>
);

/** Tmavý motív — mesiac. */
export const MoonIcon = (props) => (
  <Icon {...props}>
    <path d="M20.4 13.6A8.4 8.4 0 0 1 10.4 3.6a8.4 8.4 0 1 0 10 10z" />
  </Icon>
);

/** Systémový motív — obrazovka, teda "ako to má nastavené počítač". */
export const MonitorIcon = (props) => (
  <Icon {...props}>
    <rect x="3" y="4.4" width="18" height="12" rx="2" />
    <path d="M8.6 20h6.8M12 16.4V20" />
  </Icon>
);

/** Obsadenosť — stĺpce záťaže, teda "koľko kto má". */
export const CoverageIcon = (props) => (
  <Icon {...props}>
    <path d="M3.6 20.4h16.8" />
    <rect x="5.6" y="12.4" width="3.4" height="6" rx="1" />
    <rect x="10.8" y="8.4" width="3.4" height="10" rx="1" />
    <rect x="16" y="4.4" width="3.4" height="14" rx="1" />
  </Icon>
);
