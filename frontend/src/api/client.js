import axios from 'axios';

/**
 * Shared API client. The browser automatically sends the HttpOnly session
 * cookie; neither an identity nor a credential is taken from localStorage.
 */
const client = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  withCredentials: true,
});

export default client;
