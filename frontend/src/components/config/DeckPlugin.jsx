import React, { useEffect, useState } from 'react';
import { getDeckPluginInfo } from '#src/lib/api/deck.js';
import { DOWNLOAD_URL, SHA_URL, ZIP_NAME, normalizeInfo } from '#src/lib/deck.js';
import { fmtSize } from '#src/lib/format.js';
import { useI18n } from '#src/hooks/useI18n.js';
import { Alert, Button } from '#src/components/ui/index.js';

// Parte visible: solo pinta (props). Sin zip en el hub (modo nativo sin empaquetar) el botón queda deshabilitado con el motivo.
export function DeckPluginView({ info, loaded, failed }) {
  const { t, locale } = useI18n();
  const ok = loaded && !failed && info?.available;
  return (
    <section className="pairing card deck-plugin" aria-labelledby="deck-plugin-title">
      <h4 id="deck-plugin-title" className="pairing-title">
        {t('deck.title')}
      </h4>
      <p className="muted pairing-intro">{t('deck.intro')}</p>
      <div className="row deck-plugin-actions">
        {ok ? (
          <a className="btn primary" href={DOWNLOAD_URL} download={ZIP_NAME}>
            {t('deck.download')}
          </a>
        ) : (
          <Button variant="primary" disabled>
            {t('deck.download')}
          </Button>
        )}
      </div>
      <div role="status" aria-live="polite">
        {failed && (
          <Alert variant="warn" compact>
            {t('deck.failed')}
          </Alert>
        )}
        {loaded && !failed && !info?.available && (
          <Alert variant="info" compact>
            {t('deck.missing')}
          </Alert>
        )}
      </div>
      {ok && (
        <>
          <dl className="pairing-meta">
            <div>
              <dt>{t('deck.version')}</dt>
              <dd>{info.version ?? t('deck.versionUnknown')}</dd>
            </div>
            {info.size != null && (
              <div>
                <dt>{t('deck.size')}</dt>
                <dd>{fmtSize(info.size, locale)}</dd>
              </div>
            )}
            <div>
              <dt>{t('deck.sha')}</dt>
              <dd>
                <code className="deck-plugin-sha">{info.sha256}</code>
              </dd>
            </div>
          </dl>
          <p className="muted pairing-check">
            {t('deck.verify')} <code>sha256sum {ZIP_NAME}</code> (<a href={SHA_URL}>{ZIP_NAME}.sha256</a>)
          </p>
        </>
      )}
    </section>
  );
}

export default function DeckPlugin() {
  const [state, setState] = useState({ info: null, loaded: false, failed: false });
  useEffect(() => {
    let alive = true;
    getDeckPluginInfo()
      .then((raw) => alive && setState({ info: normalizeInfo(raw), loaded: true, failed: false }))
      .catch(() => alive && setState({ info: null, loaded: true, failed: true }));
    return () => {
      alive = false;
    };
  }, []);
  return <DeckPluginView {...state} />;
}
