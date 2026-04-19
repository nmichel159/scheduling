import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import { GoogleOAuthProvider } from '@react-oauth/google' // 1. Pridaný import
import { router } from './router'
import './index.css'
import './i18n'

// 2. Načítanie Google Client ID z .env súboru
const googleClientId = import.meta.env.VITE_GOOGLE_CLIENT_ID;

createRoot(document.getElementById('root')).render(
  <StrictMode>
    {/* 3. Obalenie aplikácie Google Providerom */}
    <GoogleOAuthProvider clientId={googleClientId}>
      <RouterProvider router={router} />
    </GoogleOAuthProvider>
  </StrictMode>,
)