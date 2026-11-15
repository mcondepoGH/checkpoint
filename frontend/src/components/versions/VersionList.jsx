import React from 'react';
import Icon from '#src/components/ui/Icon.jsx';
import { Button, Pill } from '#src/components/ui/index.js';
import { useI18n } from '#src/hooks/useI18n.js';

// Tarjetas de Versiones. «Actual» (`current`, estado del hub que da /limit) va siempre primero, con insignia de texto
// (icono + «Actual», no solo color) y sin Restaurar: ya es lo que hay en el hub. Después, las versiones guardadas.
// `current` null/ausente (hub vacío o hub antiguo): no hay tarjeta «Actual».
export default function VersionList({ current, list, onRestore }) {
  const { t } = useI18n();
  return (
    <div className="grid">
      {current && (
        <div className="card version-current" key="current">
          <h3>
            {t('versions.current.title')}{' '}
            <Pill tone="info" title={t('versions.current.help')}>
              <Icon name="history" />
              {t('versions.current.label')}
            </Pill>
          </h3>
          <div className="row between version-src">
            <span className="version-info">
              <b>{t('versions.current.hub')}</b> · {t('files', { count: current.files })} · {current.mtime}
            </span>
          </div>
        </div>
      )}
      {list.map((v) => (
        <div className="card" key={v.version}>
          <h3>{v.version}</h3>
          {v.sources.map((s) => (
            <div className="row between version-src" key={s.source}>
              <span className="version-info">
                <b>{s.name || s.source}</b> · {t('files', { count: s.files })} · {s.mtime}
              </span>
              <Button onClick={() => onRestore(v.version, s.source, s.name || s.source)}>{t('versions.restore')}</Button>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
