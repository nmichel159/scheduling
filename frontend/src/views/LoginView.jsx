import React from 'react';
import { useTranslation } from 'react-i18next';
import { useGoogleLogin } from '@react-oauth/google';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import './LoginView.css';

const LoginView = () => {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();

  // Načítanie URL z .env cez Vite
  const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  const login = useGoogleLogin({
    onSuccess: async (tokenResponse) => {
      console.log('Google Success:', tokenResponse);
      
      try {
        // Používame premennú API_URL namiesto statického textu
        const response = await axios.post(`${API_URL}/auth/google`, {
          token: tokenResponse.access_token,
        });

        console.log('Backend Response:', response.data);
        localStorage.setItem('user', JSON.stringify(response.data));
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
          {/* Ostatné tlačidlá zostávajú... */}
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