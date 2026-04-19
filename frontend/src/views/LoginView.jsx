import React from 'react';
import { useTranslation } from 'react-i18next';
import './LoginView.css';

const LoginView = () => {
  const { t, i18n } = useTranslation();

  return (
    <main className="login-wrapper">
      <div className="language-selector">
        <button onClick={() => i18n.changeLanguage('sk')} className={i18n.language === 'sk' ? 'active' : ''}>SK</button>
        <span className="separator">|</span>
        <button onClick={() => i18n.changeLanguage('en')} className={i18n.language === 'en' ? 'active' : ''}>EN</button>
      </div>

      <section className="login-content">
        <h1>{t('login_title')}</h1>
        <p className="subtitle">{t('login_subtitle')}</p>

        <div id="social" className="social-grid">
          <button className="social-button">
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