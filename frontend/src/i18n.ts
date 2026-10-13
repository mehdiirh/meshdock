import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en.json";
import fa from "./locales/fa.json";
void i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, fa: { translation: fa } },
  lng: localStorage.getItem("tm-language") || "en",
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});
function applyLanguage(language: string) {
  document.documentElement.lang = language;
  document.documentElement.dir = language === "fa" ? "rtl" : "ltr";
  localStorage.setItem("tm-language", language);
}
i18n.on("languageChanged", applyLanguage);
applyLanguage(i18n.language);
export default i18n;
