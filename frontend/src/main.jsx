import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import { router } from './router' // Importujeme tvoju mapu stránok
import './index.css'
import './i18n' // Toto aktivuje viacjazyčnosť v celom projekte

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
)