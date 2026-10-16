import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import { passwordErrorMessage, resetPassword } from '../services/authService';
import logo from '../assets/logo.jpg';
import './LoginView.css';

/** Nastavenie nového hesla z odkazu v e-maile (?token=…). */
const ResetPasswordView = () => {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const token = params.get('token') || '';
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);
  const [saving, setSaving] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (next !== confirm) {
      setError(t('password.mismatch'));
      return;
    }
    setSaving(true);
    setError('');
    try {
      await resetPassword(token, next);
      setDone(true);
    } catch (err) {
      setError(passwordErrorMessage(t, err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <main className="login-wrapper">
      <section className="login-card" aria-labelledby="reset-title">
        <div className="login-brand">
          <img src={logo} alt="" className="login-logo" />
          <span className="login-brand-name">{t('app_title')}</span>
        </div>

        <h1 id="reset-title" className="login-title">{t('password.reset_title')}</h1>

        {error && (
          <div className="alert alert-danger login-error" role="alert">
            {error}
          </div>
        )}

        {!token ? (
          <div className="alert alert-danger login-error" role="alert">
            {t('password.errors.invalid_reset_link')}
          </div>
        ) : done ? (
          <div className="alert alert-success login-error" role="status">
            {t('password.reset_done')}
          </div>
        ) : (
          <form className="login-form" onSubmit={submit}>
            <div className="field">
              <label className="field-label" htmlFor="reset-new">{t('password.new')}</label>
              <input
                id="reset-new"
                className="input"
                type="password"
                autoComplete="new-password"
                value={next}
                onChange={(e) => setNext(e.target.value)}
                disabled={saving}
                required
              />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="reset-confirm">{t('password.confirm')}</label>
              <input
                id="reset-confirm"
                className="input"
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                disabled={saving}
                required
              />
            </div>
            <button
              type="submit"
              className="btn btn-primary btn-lg btn-block"
              disabled={saving || !next || !confirm}
            >
              {t('password.save')}
            </button>
          </form>
        )}

        <Link to="/" className="login-link" style={{ display: 'inline-block', marginTop: 16 }}>
          {t('password.back_to_login')}
        </Link>
      </section>
    </main>
  );
};

export default ResetPasswordView;
