// Textos del aviso de fallo SIN depender del contexto de i18n (que puede ser lo que ha fallado): se leen directamente de
// los catálogos y el idioma sale de navigator.language. Solo datos y funciones puras: nada que pueda lanzar al pintar.
import es from '#src/locales/es.json';
import en from '#src/locales/en.json';

const CATALOGS = { es: es.app.crash, en: en.app.crash };

export function crashLang(nav = globalThis.navigator) {
  try {
    const l = String((nav?.languages && nav.languages[0]) || nav?.language || '').toLowerCase();
    return l.startsWith('en') ? 'en' : 'es';
  } catch {
    return 'es';
  }
}

/** Función t(clave) para las claves `app.crash.*`; clave desconocida devuelve la propia clave. */
export function crashT(nav) {
  const c = CATALOGS[crashLang(nav)];
  return (key) => c[key.replace(/^app\.crash\./, '')] ?? key;
}
