import React, { useEffect, useState } from 'react';
import { labelOf } from '#src/lib/names.js';
import EmptyState from '#src/components/ui/EmptyState.jsx';
import { errText, useI18n } from '#src/hooks/useI18n.js';
import { Alert, Button, Select } from '#src/components/ui/index.js';
import { getVersionsLimit, listVersions, restoreVersion } from '#src/lib/api/versions.js';
import { listOrphans } from '#src/lib/api/orphans.js';
import VersionList from '#src/components/versions/VersionList.jsx';
import { watchLatest } from '#src/lib/versionsWatch.js';

// Aviso de datos sin dispositivo ni juego, con enlace a Configuración > General (donde se revisan y se mueven a la papelera).
export function OrphansNotice({ count, onGoSettings }) {
  const { t } = useI18n();
  return (
    <Alert variant="info" compact className="orphans-notice">
      <span>{t('versions.orphans', { count })}</span>
      {onGoSettings && (
        <Button variant="ghost" onClick={onGoSettings}>
          {t('versions.orphansGo')}
        </Button>
      )}
    </Alert>
  );
}

export default function Versions({ config, onGoSettings }) {
  const { t } = useI18n();
  const games = Object.keys(config.games);
  const [game, setGame] = useState(games[0] || '');
  const [list, setList] = useState([]);
  const [msg, setMsg] = useState(null); // {error?, body}: `body` es un error o respuesta con {code, params} (se traduce al pintar)
  const [limit, setLimit] = useState(null);
  const [orphans, setOrphans] = useState(0); // elementos sin dispositivo ni juego en el hub (aviso con enlace a Configuración)

  const load = (g) =>
    g
      ? listVersions(g)
          .then(setList)
          .catch((e) => setMsg({ error: true, body: e }))
      : setList([]);
  const loadLimit = (g) =>
    g
      ? getVersionsLimit(g)
          .then(setLimit)
          .catch(() => setLimit(null))
      : setLimit(null);
  useEffect(() => {
    load(game);
    loadLimit(game);
  }, [game, config]);

  useEffect(() => {
    let alive = true;
    listOrphans()
      .then((r) => alive && setOrphans(r.items.length))
      .catch(() => {}); // el aviso es secundario: un fallo no molesta
    return () => {
      alive = false;
    };
  }, []);

  // La lista se refresca sola cuando aparece una versión nueva (p. ej. el checkpoint de cierre de un juego): se vigila la
  // más reciente cada ~15 s, solo con la pestaña visible y mientras esta página está montada.
  useEffect(() => {
    if (!game) return undefined;
    return watchLatest(
      () => getVersionsLimit(game),
      (l) => {
        setLimit(l);
        load(game);
      },
    );
  }, [game, config]);

  const restore = async (version, source, sourceName) => {
    if (!window.confirm(t('versions.confirm', { version, source: sourceName }))) return;
    try {
      const r = await restoreVersion(game, version, source);
      setMsg({ body: r });
      load(game);
      loadLimit(game);
    } catch (e) {
      setMsg({ error: true, body: e });
    }
  };

  return (
    <section className={list.length === 0 && !limit?.current ? 'fill' : undefined}>
      <div className="row between versions-head">
        <h2>{t('versions.title')}</h2>
        <Select
          aria-label={t('versions.gameAria')}
          value={game}
          onChange={(e) => {
            setGame(e.target.value);
            setMsg(null);
          }}
          options={games.map((g) => ({
            value: g,
            label: labelOf(config.games, g) + (config.games[g].enabled === false ? ` ${t('versions.disabledSuffix')}` : ''),
          }))}
        />
      </div>
      {limit && game && (
        <p className="muted versions-limit">
          {limit.max === 0
            ? t('versions.limit.unlimited', { count: limit.count })
            : t('versions.limit.max', { count: limit.count, max: limit.max })}
          {limit.override ? t('versions.limit.override') : t('versions.limit.global')}
        </p>
      )}
      {game && config.games[game]?.enabled === false && (
        <Alert variant="info" compact>
          {t('versions.disabledNote')}
        </Alert>
      )}
      {orphans > 0 && <OrphansNotice count={orphans} onGoSettings={onGoSettings} />}
      {msg && <Alert variant={msg.error ? 'error' : 'ok'}>{errText(msg.body)}</Alert>}
      {list.length === 0 &&
        !limit?.current &&
        (games.length === 0 ? (
          <EmptyState
            variant="page"
            icon="🎮"
            title={t('sync.noGames.title')}
            text={t('versions.noGames.text')}
            action={
              onGoSettings && (
                <Button variant="primary" onClick={onGoSettings}>
                  {t('common.goSettings')}
                </Button>
              )
            }
          />
        ) : (
          <EmptyState variant="page" icon="🗂️" title={t('versions.none.title')} text={t('versions.none.text')} />
        ))}
      <VersionList current={limit?.current} list={list} onRestore={restore} />
    </section>
  );
}
