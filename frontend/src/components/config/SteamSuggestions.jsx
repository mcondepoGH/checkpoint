import React from 'react';
import useSteam from '#src/hooks/useSteam.js';
import { showBlock } from '#src/lib/steam.js';
import { errText, useI18n } from '#src/hooks/useI18n.js';
import { Alert, Button } from '#src/components/ui/index.js';

// Parte visible: solo pinta (props). Si no hay sugerencias, descartes ni aviso, no pinta nada.
// Los nombres de Steam los manda la Deck: se pintan siempre como texto (React los escapa), nunca como HTML.
export function SteamList({ rows, dismissed, busy, notice, dirty, onAccept, onDiscard, onForget, onCloseNotice }) {
  const { t } = useI18n();
  if (!showBlock(rows, dismissed, notice)) return null;
  return (
    <section className="pairing steam" aria-labelledby="steam-title">
      {rows.length > 0 && (
        <>
          <h4 id="steam-title" className="pairing-title">
            {t('steam.title')} <span className="pairing-count">{rows.length}</span>
          </h4>
          <p className="muted pairing-intro">{t('steam.intro')}</p>
          {dirty && (
            <Alert variant="warn" compact role="note">
              {t('steam.dirtyWarn')}
            </Alert>
          )}
        </>
      )}
      <div role="status" aria-live="polite">
        {notice && (
          <Alert variant={notice.variant} compact>
            <span>{errText(notice.body)}</span>
            <Button variant="ghost" onClick={onCloseNotice} aria-label={t('common.close')}>
              ×
            </Button>
          </Alert>
        )}
      </div>
      {rows.length > 0 && (
        <ul className="pairing-list">
          {rows.map((r) => (
            <li key={r.id} className="card pairing-row">
              <div className="pairing-head">
                <strong className="pairing-name">{r.steamName}</strong>
                <span className="steam-appid">{t('steam.appid', { appid: r.appid })}</span>
              </div>
              <dl className="pairing-meta">
                <div>
                  <dt>{t('steam.game')}</dt>
                  <dd>{r.gameName}</dd>
                </div>
                <div>
                  <dt>{t('steam.from')}</dt>
                  <dd>{r.deviceName}</dd>
                </div>
              </dl>
              <p className="pairing-check">{t('steam.check', { steam: r.steamName, game: r.gameName })}</p>
              <div className="row pairing-actions">
                <Button variant="primary" disabled={busy != null} onClick={() => onAccept(r)}>
                  {busy === r.id ? t('steam.working') : t('steam.accept')}
                </Button>
                <Button disabled={busy != null} onClick={() => onDiscard(r)}>
                  {t('steam.discard')}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {dismissed.length > 0 && (
        <details className="steam-dismissed">
          <summary className="steam-dismissed-title">
            {t('steam.dismissedTitle')} <span className="pairing-count">{dismissed.length}</span>
          </summary>
          <p className="muted steam-dismissed-intro">{t('steam.dismissedIntro')}</p>
          <ul className="pairing-list">
            {dismissed.map((d) => (
              <li key={d.id} className="steam-dismissed-row">
                <span className="steam-dismissed-text">
                  {t('steam.dismissedRow', { steam: d.steamName, appid: d.appid, game: d.gameName })}
                </span>
                <Button disabled={busy != null} onClick={() => onForget(d)}>
                  {busy === d.id ? t('steam.working') : t('steam.forget')}
                </Button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

// Sugerencias de Steam: consulta cada 5 s mientras `active`; el usuario las acepta o descarta.
export default function SteamSuggestions({ active, dirty, onReload }) {
  const s = useSteam({ enabled: active, dirty, onReload });
  return (
    <SteamList
      rows={s.rows}
      dismissed={s.dismissed}
      busy={s.busy}
      notice={s.notice}
      dirty={dirty}
      onAccept={s.accept}
      onDiscard={s.discard}
      onForget={s.forget}
      onCloseNotice={s.closeNotice}
    />
  );
}
