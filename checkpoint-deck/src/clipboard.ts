// Copiar texto al portapapeles desde el frontend del plugin (CEF de Steam). Nunca lanza: devuelve si lo logró.
// Cadena: navigator.clipboard.writeText -> document.execCommand("copy") con un textarea temporal -> false.
// @decky/ui y @decky/api no traen API de portapapeles de texto (SteamClient.System solo tiene CopyFilesToClipboard, de ficheros).
// Comprobado en una Deck real (botón «Copiar dirección»); el comportamiento puede variar según la versión de Decky.
export async function copyText(text: string): Promise<boolean> {
  try {
    const nav = typeof navigator !== "undefined" ? navigator : undefined;
    if (nav?.clipboard?.writeText) {
      await nav.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* sigue con execCommand */
  }
  let ta: HTMLTextAreaElement | null = null;
  try {
    if (typeof document === "undefined") return false;
    ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    ta.style.pointerEvents = "none";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    return document.execCommand("copy") === true;
  } catch {
    return false;
  } finally {
    try {
      ta?.remove();
    } catch {
      /* nada */
    }
  }
}
