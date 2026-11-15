import React, { useState } from 'react';
import Modal from '#src/components/ui/Modal.jsx';
import { errText, useI18n } from '#src/hooks/useI18n.js';
import { Alert, Button } from '#src/components/ui/index.js';
import { resolutionBody } from '#src/components/sync/httpConflict.js';
import { cancelResolution, putResolution } from '#src/lib/api/sync.js';

// Aviso de conflicto de datos de un juego solo http. Sin resolución: «Usar los datos del hub» / «Usar los de <dispositivo>»,
// cada uno con confirmación. Con resolución pendiente: «Resolución pendiente…» y Cancelar. El dispositivo la aplica él
// mismo (el hub no puede escribirle): al abrir o cerrar el juego, o con «Sincronizar» en su plugin.
export default function HttpConflicts({ game, gameName, items, devName, onChanged }) {
  const { t } = useI18n();
  const [ask, setAsk] = useState(null); // {conflict, winner}
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  if (!items.length) return null;

  const done = async (fn) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
      setAsk(null);
      onChanged?.();
    }
  };
  const confirm = () => done(() => putResolution(game, resolutionBody(ask.conflict, ask.winner)));
  const cancel = (device) => done(() => cancelResolution(game, device));
  const dev = ask && devName(ask.conflict.device);

  return (
    <>
      {error && <Alert variant="error">{errText(error)}</Alert>}
      {items.map(({ device, conflict, resolution }) =>
        resolution ? (
          <div className="conflict-flag" role="status" key={device}>
            <span>
              <b>{t('sync.httpConflict.pendingLead')}</b>{' '}
              {t(resolution.winner === 'hub' ? 'sync.httpConflict.pendingHub' : 'sync.httpConflict.pendingDevice', {
                device: devName(device),
              })}
            </span>
            <Button disabled={busy} onClick={() => cancel(device)}>
              {t('sync.httpConflict.cancel')}
            </Button>
          </div>
        ) : (
          conflict && (
            <div className="conflict-flag" role="alert" key={device}>
              <span>
                <b>{t('sync.flagLead')}</b> {t('sync.httpConflict.text', { device: devName(device) })}
              </span>
              <span className="row end">
                <Button disabled={busy} onClick={() => setAsk({ conflict, winner: 'hub' })}>
                  {t('sync.httpConflict.useHub')}
                </Button>
                <Button disabled={busy} onClick={() => setAsk({ conflict, winner: 'device' })}>
                  {t('sync.httpConflict.useDevice', { device: devName(device) })}
                </Button>
              </span>
            </div>
          )
        ),
      )}
      {ask && (
        <Modal title={t('sync.httpConflict.confirmTitle', { game: gameName })} onClose={() => !busy && setAsk(null)}>
          <p>{t(ask.winner === 'hub' ? 'sync.httpConflict.confirmHub' : 'sync.httpConflict.confirmDevice', { device: dev })}</p>
          <p className="muted">{t('sync.httpConflict.confirmWhen', { device: dev })}</p>
          <div className="row end">
            <Button onClick={() => setAsk(null)} disabled={busy}>
              {t('common.cancel')}
            </Button>
            <Button variant="primary" onClick={confirm} disabled={busy}>
              {t('sync.httpConflict.confirm')}
            </Button>
          </div>
        </Modal>
      )}
    </>
  );
}
