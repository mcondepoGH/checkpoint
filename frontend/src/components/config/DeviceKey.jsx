import React, { useEffect, useId, useReducer, useRef, useState } from 'react';
import * as pairingApi from '#src/lib/api/pairing.js';
import { copyText } from '#src/lib/clipboard.js';
import { copyKey, initialState, reduce, run, wantsOpen } from '#src/lib/devicekey.js';
import { isInsecure } from '#src/lib/apikey.js';
import { errText, useI18n } from '#src/hooks/useI18n.js';
import { Alert, Button, CopyBox } from '#src/components/ui/index.js';

// Bloque «Clave» de la tarjeta de un dispositivo http: estado, Ver/Ocultar, Copiar, Regenerar y Revocar.
// La clave no se pinta hasta pulsar Ver (o al regenerar, que es cuando hay que ponerla en el dispositivo). `lock`: clave del catálogo con
// el motivo por el que las acciones están bloqueadas (dispositivo sin guardar o con cambios). `initial`, `api` e `insecure` son para pruebas.
export default function DeviceKey({ deviceId, lock = null, initial = null, api, insecure }) {
  const { t } = useI18n();
  const real = api ?? {
    get: () => pairingApi.getDeviceKey(deviceId),
    create: () => pairingApi.createDeviceKey(deviceId),
    revoke: () => pairingApi.revokeDeviceKey(deviceId),
  };
  const [s, dispatch] = useReducer(reduce, initial ? { ...initialState, ...initial } : initialState);
  // Cerrado por defecto; se abre solo al pasar a «sin clave» o «recién generada» y después manda el usuario.
  const [open, setOpen] = useState(() => wantsOpen(s));
  const auto = wantsOpen(s);
  useEffect(() => {
    if (auto) setOpen(true);
  }, [auto, s.fresh]);
  const confirmBtn = useRef(null);
  const hintId = useId();
  const warnInsecure = insecure ?? (typeof window !== 'undefined' && isInsecure(window.location));

  const act = async (what) => {
    dispatch({ type: 'start' });
    dispatch(await run(real, what));
  };
  useEffect(() => {
    if (!initial && deviceId) act('load');
  }, [deviceId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (s.confirm) confirmBtn.current?.focus();
  }, [s.confirm]);
  // Si la tarjeta se bloquea (cambios sin guardar), la clave visible se oculta y se cancela cualquier confirmación.
  useEffect(() => {
    if (lock) {
      dispatch({ type: 'hide' });
      dispatch({ type: 'cancel' });
    }
  }, [lock]);

  const off = !!lock || s.busy;
  const copy = async () => {
    dispatch({ type: 'start' });
    dispatch(await copyKey(real, s.key, copyText));
  };

  return (
    <details className="devkey" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary className="devkey-title">
        {t('devkey.title')}
        {s.loaded && !s.error && (
          <span className={`devkey-state ${s.exists ? 'has' : 'none'}`}>{s.exists ? t('devkey.has') : t('devkey.none')}</span>
        )}
      </summary>
      <div className="devkey-body">
        <small className="muted" id={hintId}>
          {t('devkey.hint')}
        </small>
        {lock && (
          <Alert variant="warn" compact role="note">
            {t(lock)}
          </Alert>
        )}
        {s.error && (
          <Alert variant="error" compact role="alert">
            {errText(s.error)}
          </Alert>
        )}
        {!s.loaded && !s.error && !lock && (
          <small className="muted" role="status">
            {t('common.loading')}
          </small>
        )}
        {s.key && (
          <>
            <CopyBox value={s.key} label={t('devkey.field')} what={t('devkey.copyWhat')} describedBy={hintId} />
            {warnInsecure && (
              <Alert variant="warn" compact>
                <span>{t('profile.apikey.insecure')}</span>
              </Alert>
            )}
          </>
        )}
        {s.confirm ? (
          <Alert variant="warn" role="alertdialog" aria-label={t(`devkey.confirm.${s.confirm}.title`)}>
            <p className="devkey-confirm">{t(`devkey.confirm.${s.confirm}.text`)}</p>
            <div className="devkey-actions">
              <Button ref={confirmBtn} variant="danger" disabled={off} onClick={() => act(s.confirm === 'revoke' ? 'revoke' : 'create')}>
                {t(`devkey.confirm.${s.confirm}.yes`)}
              </Button>
              <Button variant="ghost" onClick={() => dispatch({ type: 'cancel' })} disabled={s.busy}>
                {t('common.cancel')}
              </Button>
            </div>
          </Alert>
        ) : (
          s.loaded && (
            <div className="devkey-actions">
              {s.exists ? (
                <>
                  {s.key ? (
                    <Button disabled={off} onClick={() => dispatch({ type: 'hide' })}>
                      {t('devkey.hide')}
                    </Button>
                  ) : (
                    <Button disabled={off} onClick={() => act('show')}>
                      {t('devkey.show')}
                    </Button>
                  )}
                  <Button disabled={off} onClick={copy}>
                    {s.copied ? t('common.copied') : t('common.copy')}
                  </Button>
                  <Button disabled={off} onClick={() => dispatch({ type: 'ask', what: 'regenerate' })}>
                    {t('devkey.regenerate')}
                  </Button>
                  <Button variant="danger" disabled={off} onClick={() => dispatch({ type: 'ask', what: 'revoke' })}>
                    {t('devkey.revoke')}
                  </Button>
                </>
              ) : (
                <Button disabled={off} onClick={() => act('create')}>
                  {t('devkey.generate')}
                </Button>
              )}
            </div>
          )
        )}
      </div>
    </details>
  );
}
