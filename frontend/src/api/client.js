import axios from 'axios';

const client = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  withCredentials: true,
});


client.interceptors.response.use(
  (response) => response,
  (error) => {
    const isLoginRequest = error.config?.url === '/auth/google';
    if (error.response?.status === 401 && !isLoginRequest) {
      localStorage.removeItem('user');
      localStorage.removeItem('roles');
      localStorage.removeItem('sidebarOpen');
      if (window.location.pathname !== '/') {
        window.location.assign('/');
      }
    }
    return Promise.reject(error);
  }
);

export default client;