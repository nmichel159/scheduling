import client from '../api/client';

export const loginWithPassword = (email, password) =>
  client.post('/auth/login', { email, password }).then((response) => response.data);

export const fetchMe = () => client.get('/auth/me').then((response) => response.data);

export const changePassword = (currentPassword, newPassword) =>
  client.post('/auth/password/change', {
    current_password: currentPassword,
    new_password: newPassword,
  });

export const requestPasswordReset = (email) =>
  client.post('/auth/password/forgot', { email });

export const resetPassword = (token, newPassword) =>
  client.post('/auth/password/reset', { token, new_password: newPassword });

/** Kód chyby z backendu (napr. "password_too_short") preložený cez password.errors. */
export const passwordErrorMessage = (t, error) => {
  const code = error?.response?.data?.detail;
  if (typeof code === 'string' && /^[a-z_]+$/.test(code)) {
    return t(`password.errors.${code}`, { defaultValue: t('password.generic_error') });
  }
  return t('password.generic_error');
};
