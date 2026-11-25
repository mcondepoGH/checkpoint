import React, { useEffect, useId, useRef } from 'react';
import { createPortal } from 'react-dom';

// Diálogo accesible: role=dialog, foco dentro, Escape cierra y el foco vuelve a quien lo abrió.
export default function Modal({ title, onClose, children, wide }) {
  const titleId = useId();
  const ref = useRef(null);
  useEffect(() => {
    const prev = document.activeElement;
    ref.current?.focus();
    return () => {
      if (prev instanceof HTMLElement) prev.focus();
    };
  }, []);
  const onKey = (e) => {
    if (e.key === 'Escape') {
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key !== 'Tab') return;
    const f = ref.current.querySelectorAll('button:not(:disabled), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    if (!f.length) return;
    const first = f[0];
    const last = f[f.length - 1];
    if (e.shiftKey && (document.activeElement === first || document.activeElement === ref.current)) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };
  const view = (
    // El fondo es role=presentation (sin semántica): recibe el clic que cierra y el teclado (Escape/Tab) que burbujea desde el diálogo.
    <div
      className="modal"
      role="presentation"
      onKeyDown={onKey}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className={wide ? 'card dialog wide' : 'card dialog'}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        ref={ref}
      >
        <h3 id={titleId}>{title}</h3>
        {children}
      </div>
    </div>
  );
  // En un portal a <body>: un ancestro con transform (p. ej. .card:hover), filter o backdrop-filter convierte
  // position: fixed en relativo a él y el diálogo quedaba recortado dentro de la tarjeta. Sin DOM (render a cadena) va en línea.
  return typeof document === 'undefined' ? view : createPortal(view, document.body);
}
