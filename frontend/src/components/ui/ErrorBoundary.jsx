import React, { useState } from 'react';
import { useI18n } from '#src/hooks/useI18n.js';
import { copyText } from '#src/lib/clipboard.js';
import { crashReport } from '#src/lib/crash.js';
import { crashT } from '#src/lib/crashtext.js';
import Alert from './Alert.jsx';
import Button from './Button.jsx';

// Aviso con los detalles plegados (para iPad sin consola): solo lo que fija crashReport (error saneado, user agent y versión).
export function CrashPanel({ t, details }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    setCopied(await copyText(details));
  };
  return (
    <Alert variant="error" role="alert">
      <strong>{t('app.crash.title')}</strong>
      <p>{t('app.crash.text')}</p>
      <Button onClick={() => window.location.reload()}>{t('app.crash.reload')}</Button>
      <details className="crash-details">
        <summary>{t('app.crash.details')}</summary>
        <pre className="crash-details-text">{details}</pre>
        <Button onClick={copy}>{t(copied ? 'app.crash.detailsCopied' : 'app.crash.detailsCopy')}</Button>
      </details>
    </Alert>
  );
}

export function Fallback({ error, version }) {
  const { t } = useI18n();
  return <CrashPanel t={t} details={crashReport(error, { version })} />;
}

// Último recurso: sin useI18n ni tema (pudieron ser lo que falló); textos de respaldo según navigator.language.
export function StandaloneFallback({ error, version }) {
  return <CrashPanel t={crashT()} details={crashReport(error, { version })} />;
}

// Contiene un fallo de render: sin esto React desmonta TODA la aplicación y queda la pantalla en blanco.
// El aviso trae los detalles técnicos plegados y el fallo sigue yendo a la consola.
// `resetKey` (p. ej. la pestaña activa) lo rearma al cambiar. `version`: versión instalada, si se conoce.
// `standalone`: último recurso de la raíz (no usa el contexto de i18n). `silent`: sin aviso (no pinta nada al fallar).
export default class ErrorBoundary extends React.Component {
  state = { failed: false, error: null, resetKey: this.props.resetKey };

  static getDerivedStateFromError(error) {
    return { failed: true, error };
  }

  static getDerivedStateFromProps(props, state) {
    return props.resetKey !== state.resetKey ? { failed: false, error: null, resetKey: props.resetKey } : null;
  }

  componentDidCatch(error) {
    console.error('Checkpoint: fallo al pintar una zona', error);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    if (this.props.silent) return null;
    const Panel = this.props.standalone ? StandaloneFallback : Fallback;
    return <Panel error={this.state.error} version={this.props.version} />;
  }
}
