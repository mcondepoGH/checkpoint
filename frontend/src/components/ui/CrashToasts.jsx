import React, { useEffect, useRef, useState } from 'react';
import { useI18n } from '#src/hooks/useI18n.js';
import { copyText } from '#src/lib/clipboard.js';
import { startCrashWatch } from '#src/lib/crashwatch.js';
import Button from './Button.jsx';

function Toast({ item, onDismiss, t }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    setCopied(await copyText(item.details));
  };
  return (
    <div className={`crash-toast ${item.severity}`} role={item.severity === 'alert' ? 'alert' : 'status'}>
      <div className="crash-toast-head">
        <strong>{t('app.crash.toastTitle')}</strong>
        <button type="button" className="crash-toast-close" aria-label={t('app.crash.dismiss')} onClick={() => onDismiss(item.id)}>
          ×
        </button>
      </div>
      <p className="crash-toast-text">{item.title}</p>
      <details className="crash-details">
        <summary>{t('app.crash.details')}</summary>
        <pre className="crash-details-text">{item.details}</pre>
        <Button onClick={copy}>{t(copied ? 'app.crash.detailsCopied' : 'app.crash.detailsCopy')}</Button>
      </details>
    </div>
  );
}

// Lista de avisos discretos (no bloquean la pantalla). `t`: función de traducción.
export function CrashToastList({ items, onDismiss, t }) {
  if (!items.length) return null;
  return (
    <div className="crash-toasts">
      {items.map((it) => (
        <Toast key={it.id} item={it} onDismiss={onDismiss} t={t} />
      ))}
    </div>
  );
}

// Escucha los fallos globales (una sola vez) y los muestra como avisos discretos con «Ver detalles» y «Copiar detalles».
export default function CrashToasts({ version = '' }) {
  const { t } = useI18n();
  const [items, setItems] = useState([]);
  const watch = useRef(null);
  useEffect(() => {
    watch.current = startCrashWatch(window, { onChange: setItems, version });
    return () => watch.current.stop();
  }, [version]);
  return <CrashToastList items={items} onDismiss={(id) => watch.current?.dismiss(id)} t={t} />;
}
