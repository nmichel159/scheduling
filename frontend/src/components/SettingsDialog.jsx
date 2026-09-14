import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useTheme } from '../hooks/useTheme';
import { setTheme } from '../theme';
import { MonitorIcon, MoonIcon, SunIcon } from './NavIcons';
import './SettingsDialog.css';

/** Názvy jazykov sa neprekladajú — "Slovenčina" hľadá aj ten, kto má appku v angličtine. */
const LANGUAGES = [
  { code: 'sk', badge: 'SK', label: 'Slovenčina' },
  { code: 'en', badge: 'EN', label: 'English' },
];

const THEME_OPTIONS = [
  { value: 'light', labelKey: 'settings.theme_light', Icon: SunIcon },
  { value: 'dark', labelKey: 'settings.theme_dark', Icon: MoonIcon },
  { value: 'system', labelKey: 'settings.theme_system', Icon: MonitorIcon },
];

/**
 * Nastavenia účtu — jazyk a vzhľad. Otvára sa z menu pod menom v bočnej lište.
 *
 * Voľby sa ukladajú okamžite (jazyk cez i18next do localStorage, vzhľad cez
 * src/theme.js), takže dialóg nemá tlačidlo "Uložiť" — len zatvorenie.
 */
const SettingsDialog = ({ open, onClose }) => {
  const { t, i18n } = useTranslation();
  const theme = useTheme();
  const closeRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();

    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="settings-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="settings-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-dialog-title"
      >
        <header className="settings-head">
          <h2 id="settings-dialog-title">{t('settings.title')}</h2>
          <button
            type="button"
            ref={closeRef}
            className="settings-close"
            onClick={onClose}
            aria-label={t('settings.close')}
            title={t('settings.close')}
          >
            ×
          </button>
        </header>

        <section className="settings-group">
          <p className="settings-group-title">{t('settings.language')}</p>
          <div className="settings-options">
            {LANGUAGES.map((lang) => {
              const selected = i18n.resolvedLanguage?.startsWith(lang.code);
              return (
                <button
                  key={lang.code}
                  type="button"
                  className={`settings-option ${selected ? 'is-selected' : ''}`}
                  aria-pressed={Boolean(selected)}
                  onClick={() => i18n.changeLanguage(lang.code)}
                >
                  <span className="settings-option-badge" aria-hidden="true">{lang.badge}</span>
                  <span className="settings-option-label">{lang.label}</span>
                </button>
              );
            })}
          </div>
        </section>

        <section className="settings-group">
          <p className="settings-group-title">{t('settings.appearance')}</p>
          <div className="settings-options">
            {THEME_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                className={`settings-option ${theme === option.value ? 'is-selected' : ''}`}
                aria-pressed={theme === option.value}
                onClick={() => setTheme(option.value)}
              >
                <option.Icon className="settings-option-icon" />
                <span className="settings-option-label">{t(option.labelKey)}</span>
              </button>
            ))}
          </div>
          <p className="settings-group-hint">{t('settings.theme_system_hint')}</p>
        </section>
      </div>
    </div>
  );
};

export default SettingsDialog;
