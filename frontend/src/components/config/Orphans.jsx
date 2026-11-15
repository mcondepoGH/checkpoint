import React, { useCallback, useEffect, useRef, useState } from 'react';
import { listOrphans, listTrash, relocateOrphan, restoreTrash, trashOrphans } from '#src/lib/api/orphans.js';
import {
  canRelocate,
  hasOnlyCopy,
  keepSelected,
  moveNotice,
  payload,
  relocateNotice,
  selectedItems,
  targetGame,
  totalSize,
} from '#src/lib/orphans.js';
import { fmtDateTime, fmtSize } from '#src/lib/format.js';
import { ui } from '#src/lib/errors.js';
import { errText, useI18n } from '#src/hooks/useI18n.js';
import { Alert, Button, Checkbox, Select } from '#src/components/ui/index.js';
import Field from '#src/components/ui/Field.jsx';
import Modal from '#src/components/ui/Modal.jsx';

function Meta({ it, locale }) {
  const { t } = useI18n();
  return (
    <dl className="pairing-meta">
      <div>
        <dt>{t('orphans.size')}</dt>
        <dd>{fmtSize(it.size, locale)}</dd>
      </div>
      <div>
        <dt>{t('orphans.versions')}</dt>
        <dd>{it.versions}</dd>
      </div>
      <div>
        <dt>{t('orphans.oldest')}</dt>
        <dd>{it.oldest}</dd>
      </div>
      <div>
        <dt>{t('orphans.newest')}</dt>
        <dd>{it.newest}</dd>
      </div>
    </dl>
  );
}

const nameOf = (t, it) =>
  it.kind === 'origin' ? t('orphans.origin', { game: it.game, source: it.source }) : t('orphans.game', { game: it.game });

// Parte visible: solo pinta (props). Sin datos huérfanos, sin papelera y sin aviso no pinta nada.
// Los nombres de juego y origen salen del disco: se pintan siempre como texto (React los escapa).
export function OrphanList({
  items,
  trash,
  games = [],
  ttlDays,
  selected,
  busy,
  notice,
  confirming,
  ack,
  relocating = null,
  target = '',
  onToggle,
  onRelocate = () => {},
  onTarget = () => {},
  onRelocateCancel = () => {},
  onRelocateConfirm = () => {},
  onAsk,
  onCancel,
  onAck,
  onConfirm,
  onRestore,
  onDismiss,
}) {
  const { t, locale } = useI18n();
  if (items.length === 0 && trash.length === 0 && !notice) return null;
  const chosen = selectedItems(items, selected);
  const onlyCopy = hasOnlyCopy(chosen);
  return (
    <section className="pairing orphans" aria-labelledby="orphans-title">
      {(items.length > 0 || trash.length > 0) && (
        <div className="orphans-head">
          <h4 id="orphans-title" className="pairing-title">
            {t('orphans.title')} <span className="pairing-count">{items.length}</span>
          </h4>
          <p className="muted pairing-intro">{t('orphans.intro', { days: ttlDays })}</p>
        </div>
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
      {items.length > 0 && (
        <>
          <ul className="pairing-list">
            {items.map((it) => (
              <li key={it.id} className="card pairing-row">
                <div className="pairing-head">
                  <Checkbox
                    label={<strong className="pairing-name">{nameOf(t, it)}</strong>}
                    checked={selected.includes(it.id)}
                    disabled={busy}
                    onChange={() => onToggle(it.id)}
                  />
                </div>
                <Meta it={it} locale={locale} />
                {it.only_copy && (
                  <Alert variant="warn" compact>
                    {t('orphans.onlyCopy', { days: ttlDays })}
                  </Alert>
                )}
                {canRelocate(it, games) && (
                  <div className="row pairing-actions">
                    <Button disabled={busy} onClick={() => onRelocate(it)}>
                      {t('orphans.relocateBtn')}
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
          <div className="row pairing-actions">
            <Button variant="primary" disabled={busy || chosen.length === 0} onClick={onAsk}>
              {t('orphans.trashBtn', { count: chosen.length })}
            </Button>
          </div>
        </>
      )}
      {confirming && (
        <Modal title={t('orphans.confirmTitle')} onClose={onCancel}>
          <div className="orphans-confirm">
            <p>{t('orphans.confirmIntro', { count: chosen.length, size: fmtSize(totalSize(chosen), locale) })}</p>
            <ul className="orphans-confirm-list">
              {chosen.map((it) => (
                <li key={it.id}>
                  {nameOf(t, it)} · {fmtSize(it.size, locale)}
                </li>
              ))}
            </ul>
            <p>{t('orphans.confirmKeep', { days: ttlDays })}</p>
            {onlyCopy && (
              <Alert variant="warn" compact>
                {t('orphans.confirmOnlyCopy')}
              </Alert>
            )}
            <Checkbox
              label={t(onlyCopy ? 'orphans.ackOnlyCopy' : 'orphans.ack', { days: ttlDays })}
              checked={ack}
              onChange={(e) => onAck(e.target.checked)}
            />
            <div className="row pairing-actions">
              <Button variant="primary" disabled={!ack || busy} onClick={onConfirm}>
                {busy ? t('orphans.moving') : t('orphans.confirm')}
              </Button>
              <Button disabled={busy} onClick={onCancel}>
                {t('common.cancel')}
              </Button>
            </div>
          </div>
        </Modal>
      )}
      {relocating && (
        <Modal title={t('orphans.relocateTitle')} onClose={onRelocateCancel}>
          <div className="orphans-confirm">
            <p>{t('orphans.relocateIntro', { game: relocating.game })}</p>
            <Field label={t('orphans.relocateTarget')}>
              {(props) => (
                <Select
                  {...props}
                  value={target}
                  disabled={busy}
                  onChange={(e) => onTarget(e.target.value)}
                  placeholder={t('orphans.relocatePick')}
                  options={games.map((g) => ({ value: g.id, label: g.name }))}
                />
              )}
            </Field>
            <dl className="pairing-meta">
              <div>
                <dt>{t('orphans.relocateFrom')}</dt>
                <dd>{relocating.game}</dd>
              </div>
              <div>
                <dt>{t('orphans.relocateTo')}</dt>
                <dd>{targetGame(games, target)?.name ?? '-'}</dd>
              </div>
              <div>
                <dt>{t('orphans.versions')}</dt>
                <dd>{relocating.versions}</dd>
              </div>
              <div>
                <dt>{t('orphans.size')}</dt>
                <dd>{fmtSize(relocating.size, locale)}</dd>
              </div>
            </dl>
            {targetGame(games, target) && (
              <Alert variant="warn" compact>
                {t('orphans.relocateKeep', { game: relocating.game, target: targetGame(games, target).name, days: ttlDays })}
              </Alert>
            )}
            <div className="row pairing-actions">
              <Button variant="primary" disabled={!targetGame(games, target) || busy} onClick={onRelocateConfirm}>
                {busy ? t('orphans.relocating') : t('orphans.relocateConfirm')}
              </Button>
              <Button disabled={busy} onClick={onRelocateCancel}>
                {t('common.cancel')}
              </Button>
            </div>
          </div>
        </Modal>
      )}
      {trash.length > 0 && (
        <details className="steam-dismissed orphans-trash">
          <summary className="steam-dismissed-title">
            {t('orphans.trashTitle')} <span className="pairing-count">{trash.reduce((n, e) => n + e.items.length, 0)}</span>
          </summary>
          <p className="muted steam-dismissed-intro">{t('orphans.trashIntro', { days: ttlDays })}</p>
          <ul className="pairing-list">
            {trash.map((e) =>
              e.items.map((it) => (
                <li key={`${e.entry}/${it.index}`} className="steam-dismissed-row">
                  <span className="steam-dismissed-text">
                    {nameOf(t, it)} · {fmtSize(it.size, locale)} · {t('orphans.expires', { date: fmtDateTime(e.expires, locale) })}
                  </span>
                  <Button disabled={busy} onClick={() => onRestore(e.entry, it.index)}>
                    {t('orphans.restore')}
                  </Button>
                </li>
              )),
            )}
          </ul>
        </details>
      )}
    </section>
  );
}

// Datos sin dispositivo ni juego: lista (con la papelera), mover/restaurar con doble confirmación y reubicar un juego
// huérfano en un juego existente (una confirmación). Solo se pinta si hay algo.
export default function Orphans() {
  const [items, setItems] = useState([]);
  const [trash, setTrash] = useState([]);
  const [games, setGames] = useState([]);
  const [relocating, setRelocating] = useState(null);
  const [target, setTarget] = useState('');
  const [ttl, setTtl] = useState(30);
  const [selected, setSelected] = useState([]);
  const [confirming, setConfirming] = useState(false);
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);
  const alive = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const [o, tr] = await Promise.all([listOrphans(), listTrash()]);
      if (!alive.current) return;
      setItems(o.items);
      setTtl(o.ttl_days);
      setGames(o.games ?? []);
      setTrash(tr);
      setSelected((s) => keepSelected(s, o.items));
    } catch (e) {
      if (alive.current) setNotice({ variant: 'error', body: e });
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    refresh();
    return () => {
      alive.current = false;
    };
  }, [refresh]);

  const toggle = (id) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  const cancel = () => {
    setConfirming(false);
    setAck(false);
  };
  const confirm = async () => {
    setBusy(true);
    try {
      const res = await trashOrphans(payload(selectedItems(items, selected)));
      setNotice(moveNotice(res));
    } catch (e) {
      setNotice({ variant: 'error', body: e });
    }
    setBusy(false);
    cancel();
    await refresh();
  };
  const askRelocate = (it) => {
    setRelocating(it);
    setTarget('');
  };
  const cancelRelocate = () => setRelocating(null);
  const confirmRelocate = async () => {
    const dest = targetGame(games, target);
    if (!relocating || !dest) return;
    setBusy(true);
    try {
      const res = await relocateOrphan(relocating.id, relocating.token, dest.id);
      setNotice(relocateNotice(res, dest));
    } catch (e) {
      setNotice({ variant: 'error', body: e });
    }
    setBusy(false);
    setRelocating(null);
    await refresh();
  };
  const restore = async (entry, item) => {
    setBusy(true);
    try {
      await restoreTrash(entry, item);
      setNotice({ variant: 'ok', body: ui('orphans.restored') });
    } catch (e) {
      setNotice({ variant: 'error', body: e });
    }
    setBusy(false);
    await refresh();
  };

  return (
    <OrphanList
      items={items}
      trash={trash}
      games={games}
      ttlDays={ttl}
      selected={selected}
      busy={busy}
      notice={notice}
      confirming={confirming}
      ack={ack}
      relocating={relocating}
      target={target}
      onRelocate={askRelocate}
      onTarget={setTarget}
      onRelocateCancel={cancelRelocate}
      onRelocateConfirm={confirmRelocate}
      onToggle={toggle}
      onAsk={() => setConfirming(true)}
      onCancel={cancel}
      onAck={setAck}
      onConfirm={confirm}
      onRestore={restore}
      onDismiss={() => setNotice(null)}
    />
  );
}
