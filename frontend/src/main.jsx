import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import '#src/styles/main.scss';
import { registerServiceWorker } from '#src/lib/pwa.js';
import { ErrorBoundary } from '#src/components/ui/index.js';
import CrashToasts from '#src/components/ui/CrashToasts.jsx';

registerServiceWorker();

// Último recurso: cubre la cabecera y todo lo que no esté dentro de una zona envuelta. El manejador global de
// fallos va en su propio límite silencioso: si fallara, no tira la aplicación.
createRoot(document.getElementById('root')).render(
  <ErrorBoundary standalone>
    <App />
    <ErrorBoundary silent>
      <CrashToasts />
    </ErrorBoundary>
  </ErrorBoundary>,
);
