// Translations. The English text is the key: t("Delete group") shows the translation for the
// chosen language, or the English text when there's none yet. Placeholders: t("{n} containers", { n }).
//
// The language is read before anything renders (so labels defined at module level translate
// too); changing it reloads the page. To add a language: copy fr.json, translate the values,
// and add it to LANGUAGES below. `npm test` checks every text in the code has a translation.
import fr from "./fr.json";

export const LANGUAGES = [
  { code: "en", name: "English" },
  { code: "fr", name: "Français" },
];
const CATALOGS = { fr };
const STORAGE_KEY = "habeny.lang";

function detect() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved && LANGUAGES.some((l) => l.code === saved)) return saved;
  } catch { /* no storage: fall back to the browser's language */ }
  const browser = (typeof navigator !== "undefined" && navigator.language || "en").slice(0, 2).toLowerCase();
  return LANGUAGES.some((l) => l.code === browser) ? browser : "en";
}

let current = detect();
if (typeof document !== "undefined") document.documentElement.lang = current;

export function language() {
  return current;
}

export function setLanguage(code, { reload = true } = {}) {
  try { localStorage.setItem(STORAGE_KEY, code); } catch { /* this page only */ }
  current = code;
  if (typeof document !== "undefined") document.documentElement.lang = code;
  if (reload && typeof window !== "undefined") window.location.reload();
}

export function t(text, vars) {
  const translated = (CATALOGS[current] && CATALOGS[current][text]) || text;
  if (!vars) return translated;
  return translated.replace(/\{(\w+)\}/g, (match, name) => (name in vars ? String(vars[name]) : match));
}

// Dates and numbers in the chosen language's format
export function formatDateTime(value) {
  return value ? new Date(value).toLocaleString(current) : "";
}
