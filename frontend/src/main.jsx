import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/newsreader'
import '@fontsource-variable/newsreader/wght-italic.css'
import '@fontsource-variable/instrument-sans'
import './index.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
