import React from 'react';
import { useTranslation } from 'react-i18next';
import { useGoogleLogin } from '@react-oauth/google'; // Hook pre prihlásenie
import { useNavigate } from 'react-router-dom';     // Na presmerovanie po úspechu
import './LoginView.css';

const LoginView = () => {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();

  // Definujeme akciu po kliknutí na Google tlačidlo
  const login = useGoogleLogin({
    onSuccess: (tokenResponse) => {
      console.log('Google Token:', tokenResponse);
      
      // TODO: Tu neskôr pošleme token na náš backend (Python), 
      // aby sme užívateľa uložili do Postgres databázy.
      
      // Zatiaľ ťa len presmerujeme, aby si videl, že to funguje
      navigate('/dashboard');
    },
    onError: () => {
      console.log('Login Failed');
      alert('Prihlásenie zlyhalo, skúste to znova.');
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
          {/* Pridaný onClick event pre Google */}
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