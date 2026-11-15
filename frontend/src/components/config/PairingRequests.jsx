import React, { useEffect, useState } from 'react';
import usePairing from '#src/hooks/usePairing.js';
import { canAccept, existingNoteKey, formatRemaining, remainingSeconds } from '#src/lib/pairing.js';
import { errText, useI18n } from '#src/hooks/useI18n.js';
import { Alert, Button } from '#src/components/ui/index.js';

// Un segundo de reloj local para la cuenta atrás entre consultas (no hace peticiones). `fixed` fija la hora en pruebas.
function useNow(active, fixed) {
  const [now, setNow] = useState(() => fixed ?? Date.now());
  useEffect(() => {
    if (fixed != null || !active) return undefined;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active, fixed]);
  return fixed ?? now;
}

// Parte visible: solo pinta (props). Si no hay solicitudes ni aviso, no pinta nada.
export function PairingList({ rows, busy, notice, dirty, now, onAccept, onReject, onDismiss }) {
  const { t } = useI18n();
  if (rows.length === 0 && !notice) return null;
  return (
    <section className="pairing" aria-labelledby="pairing-title">
      {rows.length > 0 && (
        <>
          <h4 id="pairing-title" className="pairing-title">
            {t('pairing.title')} <span className="pairing-count">{rows.length}</span>
          </h4>
          <p className="muted pairing-intro">{t('pairing.intro')}</p>
          {dirty && (
            <Alert variant="warn" compact role="note">
              {t('pairing.dirtyWarn')}
            </Alert>
          )}
        </>
      )}
      <div role="status" aria-live="polite">
        {notice && (
          <Alert variant={notice.variant} compact>
            <span>{errText(notice.body)}</span>
            <Button variant="ghost" onClick={onDismiss} aria-label={t('common.close')}>
              ×
            </Button>
          </Alert>
        )}
      </div>
      <ul className="pairing-list">
        {rows.map((r) => {
          const left = remainingSeconds(r, now);
          const note = existingNoteKey(r);
          const working = busy === r.id;
          return (
            <li key={r.id} className="card pairing-row">
              <div className="pairing-head">
                <strong className="pairing-name">{r.name}</strong>
                <span className="pairing-code" aria-label={t('pairing.codeAria', { code: r.code })}>
                  {r.code}
                </span>
              </div>
              <dl className="pairing-meta">
                <div>
                  <dt>{t('pairing.ip')}</dt>
                  <dd>{r.ip}</dd>
                </div>
                <div>
                  <dt>{t('pairing.expires')}</dt>
                  <dd>{left > 0 ? formatRemaining(left) : t('pairing.expired')}</dd>
                </div>
              </dl>
              {note && (
                <Alert variant={r.existing === 'other' ? 'error' : 'info'} compact>
                  {t(note)}
                </Alert>
              )}
              {canAccept(r, left) && <p className="pairing-check">{t('pairing.check', { code: r.code })}</p>}
              <div className="row pairing-actions">
                <Button variant="primary" disabled={!canAccept(r, left) || busy != null} onClick={() => onAccept(r)}>
                  {working ? t('pairing.working') : t('pairing.accept')}
                </Button>
                <Button disabled={busy != null} onClick={() => onReject(r)}>
                  {t('pairing.reject')}
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

// Solicitudes de vinculación pendientes: consulta cada 5 s mientras `active` y las acepta o rechaza.
export default function PairingRequests({ active, dirty, onReload }) {
  const p = usePairing({ enabled: active, dirty, onReload });
  const now = useNow(p.rows.length > 0);
  return (
    <PairingList
      rows={p.rows}
      busy={p.busy}
      notice={p.notice}
      dirty={dirty}
      now={now}
      onAccept={p.accept}
      onReject={p.reject}
      onDismiss={p.dismiss}
    />
  );
}
