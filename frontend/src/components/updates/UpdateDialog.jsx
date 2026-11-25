import React from 'react';
import Modal from '#src/components/ui/Modal.jsx';
import { safeUrl, isPrerelease, canInstall, INSTALL_BUSY, PHASE_TEXT } from '#src/lib/updates.js';
import { errText, useI18n } from '#src/hooks/useI18n.js';
import useUpdateInstall from '#src/hooks/useUpdateInstall.js';
import { Alert, Button } from '#src/components/ui/index.js';

// Detalle de la versión nueva. Las notas se pintan como texto (React escapa todo): nunca como HTML.
// Con la actualización con un clic (`instalable`: instalador de Windows o instalación nativa de Linux) ofrece «Actualizar ahora»: confirmación y progreso en el propio diálogo.
export default function UpdateDialog({ info, onClose }) {
  const { t } = useI18n();
  const install = canInstall(info);
  const { phase, error, ask, cancel, start } = useUpdateInstall(info.ultima, info);
  const busy = INSTALL_BUSY.includes(phase) || phase === 'done';
  const url = safeUrl(info.url);
  const pre = isPrerelease(info);
  return (
    <Modal title={t('updates.badgeLabel')} onClose={busy ? () => {} : onClose} wide>
      <dl className="update-versions">
        <div>
          <dt>{t('updates.dialog.installed')}</dt>
          <dd>{info.actual}</dd>
        </div>
        <div>
          <dt>{t('updates.dialog.new')}</dt>
          <dd>
            {info.ultima}
            {pre && <span className="pre-tag">{t('updates.pre')}</span>}
          </dd>
        </div>
      </dl>
      {pre && (
        <Alert as="p" variant="warn">
          {t('updates.dialog.preWarn')}
        </Alert>
      )}
      {info.notas ? (
        <>
          <h4>{t('updates.dialog.notesTitle')}</h4>
          <div className="update-notes" role="region" aria-label={t('updates.dialog.notesTitle')} tabIndex={0}>
            {info.notas}
          </div>
        </>
      ) : (
        <p className="muted">{t('updates.dialog.noNotes')}</p>
      )}
      {url && (
        <p>
          <a href={url} target="_blank" rel="noopener noreferrer">
            {t('updates.dialog.link')}
          </a>
        </p>
      )}
      <p className="muted">{t(install ? 'updates.install.windowsNote' : 'updates.dialog.manual')}</p>
      <div role="status" aria-live="polite">
        {phase === 'confirm' && (
          <Alert as="p" variant="warn">
            {t('updates.install.confirm', { version: info.ultima })}
          </Alert>
        )}
        {PHASE_TEXT[phase] && <p>{t(PHASE_TEXT[phase], { version: info.ultima })}</p>}
        {phase === 'error' && error && <Alert variant="error">{errText(error)}</Alert>}
      </div>
      <div className="row end">
        <Button onClick={phase === 'confirm' ? cancel : onClose} disabled={busy}>
          {phase === 'confirm' ? t('common.cancel') : t('common.close')}
        </Button>
        {install && (phase === 'idle' || phase === 'error') && (
          <Button variant="primary" onClick={ask}>
            {t('updates.install.button')}
          </Button>
        )}
        {install && phase === 'confirm' && (
          <Button variant="primary" onClick={start}>
            {t('updates.install.confirmYes')}
          </Button>
        )}
      </div>
    </Modal>
  );
}
