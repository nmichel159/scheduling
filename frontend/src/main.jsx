import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import { GoogleOAuthProvider } from '@react-oauth/google'
import '@fontsource-variable/inter'
import { router } from './router'
import './index.css'
import './styles/ui.css'
import './i18n'
import './theme'   // zapíše zvolený vzhľad do <html> ešte pred prvým vykreslením

const googleClientId = import.meta.env.VITE_GOOGLE_CLIENT_ID;

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <GoogleOAuthProvider clientId={googleClientId}>
      <RouterProvider router={router} />
    </GoogleOAuthProvider>
  </StrictMode>,
)
