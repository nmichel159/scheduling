/**
 * Ikony bočnej lišty ako inline SVG.
 *
 * Emoji sa na každom systéme vykreslia inak a nedajú sa zafarbiť podľa
 * stavu. SVG kreslí currentColor, takže ikona zdedí farbu položky
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

/** Môj rozpis — kalendár s postavou: podstatné je to „môj“. */
export const MyScheduleIcon = (props) => (
  <Icon {...props}>
    <rect x="3.6" y="5.2" width="16.8" height="15.2" rx="2.2" />
    <path d="M3.6 9.8h16.8M8 3.2v3.6M16 3.2v3.6" />
    <circle cx="12" cy="13.6" r="2" />
    <path d="M8.6 19.2c.5-1.9 1.8-2.9 3.4-2.9s2.9 1 3.4 2.9" />
  </Icon>
);

/** Obmedzenia — kalendár so zákazom, teda „kedy nemôžem“. */
export const LimitsIcon = (props) => (
  <Icon {...props}>
    <path d="M20.4 11.2V7.2a2.2 2.2 0 0 0-2.2-2.2H5.8a2.2 2.2 0 0 0-2.2 2.2v11a2.2 2.2 0 0 0 2.2 2.2h5.4" />
    <path d="M3.6 9.6h16.8M8 3.4v3.2M16 3.4v3.2" />
    <circle cx="17" cy="17" r="3.8" />
    <path d="m14.3 19.7 5.4-5.4" />
  </Icon>
);

/** Rozpis pracoviska — mriežka, riadok na človeka. */
export const TeamScheduleIcon = (props) => (
  <Icon {...props}>
    <rect x="3.6" y="4.6" width="16.8" height="14.8" rx="2.2" />
    <path d="M3.6 9h16.8M9 9v10.4M14.6 9v10.4M3.6 14.2h16.8" />
  </Icon>
);

/** Výzva mailom — obálka s odoslanou šípkou. */
export const MailIcon = (props) => (
  <Icon {...props}>
    <path d="M20.4 12.2V7.2a1.8 1.8 0 0 0-1.8-1.8H5.4a1.8 1.8 0 0 0-1.8 1.8v9.6a1.8 1.8 0 0 0 1.8 1.8h7" />
    <path d="m3.9 7.6 8.1 5.8 8.1-5.8" />
    <path d="M15.4 19.4h5.6m0 0-2.2-2.2m2.2 2.2-2.2 2.2" />
  </Icon>
);

export const WorkplaceIcon = (props) => (
  <Icon {...props}>
    <path d="M4.2 20.4V7.2A1.4 1.4 0 0 1 5.6 5.8H12v14.6M12 20.4V10.6h6.4a1.4 1.4 0 0 1 1.4 1.4v8.4M2.6 20.4h18.8M8.1 8.8v3.4M6.4 10.5h3.4" />
  </Icon>
);

/** Zamestnanci pracoviska — dvaja ľudia. */
export const EmployeesIcon = (props) => (
  <Icon {...props}>
    <circle cx="9.4" cy="8.4" r="3.4" />
    <path d="M3.4 19.6c.4-3.3 2.9-5.2 6-5.2s5.6 1.9 6 5.2" />
    <path d="M16.4 5.6a3.2 3.2 0 0 1 0 6.2M17.6 14.6c2 .5 3.2 2.3 3.4 5" />
  </Icon>
);

/** Kompetencie — odznak s fajkou, teda potvrdená spôsobilosť. */
export const CompetenceIcon = (props) => (
  <Icon {...props}>
    <circle cx="12" cy="9.2" r="5.6" />
    <path d="m9.6 9.2 1.7 1.7 3.1-3.4" />
    <path d="M8.2 13.8 6.8 21l5.2-2.6 5.2 2.6-1.4-7.2" />
  </Icon>
);

/* A calendar with a star on one day: the screen is about the handful of dates
   in a year that are treated differently from the rest. */
export const SpecialDaysIcon = (props) => (
  <Icon {...props}>
    <rect x="3.6" y="5" width="16.8" height="15" rx="2.2" />
    <path d="M3.6 9.6h16.8M8 3.4v3.2M16 3.4v3.2" />
    <path d="m12 11.6 1.4 2.8 3.1.5-2.3 2.2.6 3.1-2.8-1.5-2.8 1.5.6-3.1-2.3-2.2 3.1-.5z" />
  </Icon>
);

/** Správa pracovísk — budova s ozubeným kolesom. */
export const AdminIcon = (props) => (
  <Icon {...props}>
    <path d="M3.4 20.4V6a1.6 1.6 0 0 1 1.6-1.6h7a1.6 1.6 0 0 1 1.6 1.6v5.4M2 20.4h11" />
    <path d="M6.4 8.4h1.6M6.4 12h1.6M6.4 15.6h1.6" />
    <circle cx="16.8" cy="16.4" r="2.2" />
    <path d="M16.8 11.6v1.4M16.8 19.8v1.4M12.6 14v0M20.4 12.6l-1 1M21.6 16.4h-1.4M13.4 16.4H12M20.4 20.2l-1-1M13.2 13.2l1 1M13.2 19.6l1-1" />
  </Icon>
);

/** Prehľad rozvrhov — stoh hárkov, teda viac rozvrhov naraz. */
export const ScheduleOverviewIcon = (props) => (
  <Icon {...props}>
    <path d="M7.4 5.4V4.2a1.6 1.6 0 0 1 1.6-1.6h9.2a1.6 1.6 0 0 1 1.6 1.6v9.2a1.6 1.6 0 0 1-1.6 1.6h-1.2" />
    <rect x="3.4" y="6.6" width="12.8" height="14.8" rx="2" />
    <path d="M3.4 10.8h12.8" />
    <path d="M7 16.2l2 2 3.6-4" />
  </Icon>
);

/** Štatistiky — trendová čiara (stĺpce drží Obsadenosť). */
export const StatisticsIcon = (props) => (
  <Icon {...props}>
    <path d="M4 3.8v16.4h16.2" />
    <path d="m7 15.6 3.4-4 3 2.4 4.4-6" />
    <circle cx="17.8" cy="8" r="1.4" fill="currentColor" stroke="none" />
  </Icon>
);

/** Roly — kľúč, teda kto k čomu má prístup. */
export const RolesIcon = (props) => (
  <Icon {...props}>
    <circle cx="8.2" cy="8.4" r="4.2" />
    <path d="m11.4 11.2 8.4 8.4M16.8 16.6l-1.8 1.8M19 14.4l-1.8 1.8" />
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

/** Tlac rozvrhu — tlaciaren s vysunutym listom. */
export const PrintIcon = (props) => (
  <Icon {...props}>
    <path d="M7.2 8.4V3.6h9.6v4.8" />
    <path d="M7.2 17.2H5.4A1.8 1.8 0 0 1 3.6 15.4v-4.2a2.8 2.8 0 0 1 2.8-2.8h11.2a2.8 2.8 0 0 1 2.8 2.8v4.2a1.8 1.8 0 0 1-1.8 1.8h-1.8" />
    <rect x="7.2" y="13.6" width="9.6" height="6.8" rx="1.2" />
  </Icon>
);
