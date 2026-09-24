import { LANGUAGES, language, setLanguage, t } from "../i18n";

// Remembered in this browser; the page reloads in the new language
export default function LanguagePicker({ compact }) {
  return (
    <div className={compact ? "language-picker compact" : "field language-picker"}>
      <label htmlFor="language">{t("Language")}</label>
      <select id="language" className="select" value={language()} onChange={(e) => setLanguage(e.target.value)}>
        {LANGUAGES.map((l) => <option key={l.code} value={l.code} lang={l.code}>{l.name}</option>)}
      </select>
    </div>
  );
}
