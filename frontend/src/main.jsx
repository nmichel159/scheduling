import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import { GoogleOAuthProvider } from '@react-oauth/google'
import '@fontsource-variable/inter'
// Shared styles first: every view's CSS loads with the router below, and a
// view has to be able to adjust a shared class (.btn, .dialog, ...) with a
// single-class rule of its own.
import './index.css'
import './styles/ui.css'
import { router } from './router'
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
