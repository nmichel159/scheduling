import axios from 'axios';

/**
 * Shared Axios instance for all backend communication.
 * Reads the API base URL from Vite env (falls back to localhost)
 * and injects the X-User-Id header from the logged-in user.
 */
const client = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
});

client.interceptors.request.use((config) => {
  const userString = localStorage.getItem('user');
  if (userString) {
    try {
      const user = JSON.parse(userString);
      if (user?.id) {
        config.headers['X-User-Id'] = user.id;
      }
    } catch {
      // Corrupted storage — leave the request unauthenticated,
      // the backend will respond with 404/401 and the UI redirects to login.
    }
  }
  return config;
});

export default client;
