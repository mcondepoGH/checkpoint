import React from 'react';
import Icon from '#src/components/ui/Icon.jsx';
import { showBadge, isPrerelease } from '#src/lib/updates.js';
import { useI18n } from '#src/hooks/useI18n.js';
import { Button } from '#src/components/ui/index.js';

// Botón de la cabecera: solo existe si hay una versión nueva. Una única píldora (icono + texto); el punto de la esquina avisa
// (ámbar si es preliminar, el texto ya lo dice en title/aria-label). Al estrecharse se queda en el icono.
export default function UpdateBadge({ info, onOpen }) {
  const { t } = useI18n();
  if (!showBadge(info)) return null;
  const pre = isPrerelease(info);
  const text = t(pre ? 'updates.badgePre' : 'updates.badge', { version: info.ultima });
  return (
    <Button variant="ghost" className={`tool update-badge${pre ? ' is-pre' : ''}`} onClick={onOpen} title={text} aria-label={text}>
      <Icon name="download" />
      <span className="lbl">{t('updates.badgeLabel')}</span>
    </Button>
  );
}
