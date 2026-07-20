import React, { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useGoogleLogin } from '@react-oauth/google';
import { useNavigate } from 'react-router-dom';
import client from '../api/client';
import { fetchMyRoles } from '../services/roleService';
import './LoginView.css';

const LoginView = () => {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();

  useEffect(() => {
    if (localStorage.getItem('user')) {
      // Doplnenie rolí pre staršie sessions, ktoré ich ešte nemajú uložené.
      if (!localStorage.getItem('roles')) {
        fetchMyRoles()
          .then((roles) => localStorage.setItem('roles', JSON.stringify(roles)))
          .catch(() => localStorage.setItem('roles', '[]'))
          .finally(() => navigate('/dashboard'));
      } else {
        navigate('/dashboard');
      }
    }
  }, [navigate]);

  const login = useGoogleLogin({
    onSuccess: async (tokenResponse) => {
      try {
        const response = await client.post('/auth/google', {
          token: tokenResponse.access_token,
        });
        localStorage.setItem('user', JSON.stringify(response.data));

        // Role rozhodujú o tom, čo sa v UI zobrazí (pokyn: podľa GET /roles/me).
        try {
          const roles = await fetchMyRoles();
          localStorage.setItem('roles', JSON.stringify(roles));
        } catch {
          localStorage.setItem('roles', '[]'); // fallback: správa sa ako Rola 1
        }

        navigate('/dashboard');
      } catch (error) {
        console.error('Chyba pri prihlasovaní na backend:', error);
        alert('Backend je offline alebo nastala chyba pri overovaní.');
      }
    },
    onError: () => {
      console.log('Google Login Failed');
      alert('Prihlásenie cez Google zlyhalo.');
    },
  });

  return (
    <main className="login-wrapper">
      <div className="language-selector">
        <button
          onClick={() => i18n.changeLanguage('sk')}
          className={i18n.language === 'sk' ? 'active' : ''}
        >SK</button>
        <span className="separator">|</span>
        <button
          onClick={() => i18n.changeLanguage('en')}
          className={i18n.language === 'en' ? 'active' : ''}
        >EN</button>
      </div>

      <section className="login-content">
        <h1>{t('login_title')}</h1>
        <p className="subtitle">{t('login_subtitle')}</p>

        <div id="social" className="social-grid">
          <button className="social-button" onClick={() => login()}>
            <span className="button-icon">G</span>
            {t('login_google')}
          </button>
          <button className="social-button">
            <span className="button-icon">f</span>
            {t('login_facebook')}
          </button>
          <button className="social-button">
            <span className="button-icon">O</span>
            {t('login_outlook')}
          </button>
        </div>

        <p className="footer-note">
          {t('need_help')} <code>support@scheduling.app</code>
        </p>
      </section>
    </main>
  );
};

export default LoginView;
