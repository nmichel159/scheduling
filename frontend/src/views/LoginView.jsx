import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useGoogleLogin } from '@react-oauth/google';
import { useNavigate } from 'react-router-dom';
import client from '../api/client';
import { fetchMyRoles } from '../services/roleService';
import { getStoredRoles, landingPathFor, storeRoles } from '../hooks/useRoles';
import logo from '../assets/logo.jpg';
import './LoginView.css';

const SUPPORT_EMAIL = 'support@scheduling.app';

const LANGUAGES = [
  { code: 'sk', label: 'SK' },
  { code: 'en', label: 'EN' },
];

/** Official multi-colour Google "G" (brand guidelines ask for it unaltered). */
const GoogleLogo = () => (
  <svg className="login-google-logo" viewBox="0 0 48 48" aria-hidden="true" focusable="false">
    <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
    <path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
    <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.5 39.6 16.2 44 24 44z" />
    <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
  </svg>
);

const LoginView = () => {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [error, setError] = useState('');
  const [signingIn, setSigningIn] = useState(false);

  useEffect(() => {
    if (localStorage.getItem('user')) {
      // Doplnenie rolí pre staršie sessions, ktoré ich ešte nemajú uložené.
      if (!localStorage.getItem('roles')) {
        fetchMyRoles()
          .then((roles) => {
            storeRoles(roles);
            navigate(landingPathFor(roles));
          })
          .catch(() => {
            storeRoles([]);
            navigate(landingPathFor([]));
          });
      } else {
        navigate(landingPathFor(getStoredRoles()));
      }
    }
  }, [navigate]);

  const login = useGoogleLogin({
    onSuccess: async (tokenResponse) => {
      setSigningIn(true);
      setError('');
      try {
        const response = await client.post('/auth/google', {
          token: tokenResponse.access_token,
        });
        localStorage.setItem('user', JSON.stringify(response.data));

        // Role rozhodujú o tom, čo sa v UI zobrazí (pokyn: podľa GET /roles/me).
        let roles = [];
        try {
          roles = await fetchMyRoles();
        } catch {
          roles = [];
        }
        storeRoles(roles);

        navigate(landingPathFor(roles));
      } catch (err) {
        console.error('Chyba pri prihlasovaní na backend:', err);
        setError(t('login_error_backend'));
        setSigningIn(false);
      }
    },
    onError: () => {
      setError(t('login_error_google'));
      setSigningIn(false);
    },
    // Zatvorené okno Google nie je chyba — len vrátime tlačidlo do pôvodného stavu.
    onNonOAuthError: () => setSigningIn(false),
  });

  const currentLanguage = i18n.resolvedLanguage || 'sk';

  return (
    <main className="login-wrapper">
      <div className="login-language" role="group" aria-label="Language">
        {LANGUAGES.map((lang) => (
          <button
            key={lang.code}
            type="button"
            onClick={() => i18n.changeLanguage(lang.code)}
            className={currentLanguage === lang.code ? 'is-active' : ''}
            aria-pressed={currentLanguage === lang.code}
          >
            {lang.label}
          </button>
        ))}
      </div>

      <section className="login-card" aria-labelledby="login-title">
        <div className="login-brand">
          <img src={logo} alt="" className="login-logo" />
          <span className="login-brand-name">{t('app_title')}</span>
        </div>

        <h1 id="login-title" className="login-title">{t('login_heading')}</h1>
        <p className="login-subtitle">{t('login_subtitle')}</p>

        {error && (
          <div className="alert alert-danger login-error" role="alert">
            {error}
          </div>
        )}

        <button
          type="button"
          className="btn btn-lg btn-block login-google"
          onClick={() => {
            setError('');
            setSigningIn(true);
            login();
          }}
          disabled={signingIn}
        >
          {signingIn ? <span className="spinner" aria-hidden="true" /> : <GoogleLogo />}
          {signingIn ? t('login_signing_in') : t('login_google')}
        </button>
        <p className="login-hint">{t('login_hint')}</p>
      </section>

      <p className="login-footer">
        {t('need_help')} <a href={`mailto:${SUPPORT_EMAIL}`}>{SUPPORT_EMAIL}</a>
      </p>
    </main>
  );
};

export default LoginView;
