import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  Waypoints,
  Network,
  KeyRound,
  SlidersHorizontal,
  Sun,
  Moon,
  Globe2,
  LogOut,
} from "lucide-react";
import { api, setCsrf, ApiError } from "./api";
import type { Session } from "./types";
import { Login } from "./components/Login";
import { Workspace } from "./components/Workspace";
import { Vault } from "./components/Vault";
import { Settings } from "./components/Settings";
import { ErrorMessage, Spinner } from "./components/Primitives";
export function App() {
  const { t, i18n } = useTranslation();
  const cache = useQueryClient();
  const [section, setSection] = useState("topology");
  const [theme, setTheme] = useState(
    localStorage.getItem("tm-theme") || "dark",
  );
  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => api<Session>("/auth/me"),
    retry: false,
  });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("tm-theme", theme);
  }, [theme]);
  useEffect(() => {
    if (session.data) setCsrf(session.data.csrf);
  }, [session.data]);
  if (session.isPending)
    return (
      <div className="loading-screen">
        <Spinner />
        {t("loading")}
      </div>
    );
  if (session.error instanceof ApiError && session.error.status === 401)
    return <Login />;
  if (!session.data)
    return (
      <div className="loading-screen">
        <h2>{t("unavailable")}</h2>
        <ErrorMessage error={session.error} />
        <button className="button" onClick={() => void session.refetch()}>
          {t("refresh")}
        </button>
      </div>
    );
  return (
    <div className="app-shell">
      <nav className="rail">
        <a
          className="logo"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setSection("topology");
          }}
          aria-label={t("appName")}
        >
          <Waypoints size={27} />
        </a>
        <div className="rail-navigation">
          {[
            { id: "topology", icon: Network },
            { id: "vault", icon: KeyRound },
            { id: "access", icon: SlidersHorizontal },
          ].map((item) => (
            <button
              key={item.id}
              className={section === item.id ? "active" : ""}
              title={t(item.id)}
              aria-label={t(item.id)}
              onClick={() => setSection(item.id)}
            >
              <item.icon size={21} />
            </button>
          ))}
        </div>
        <div className="rail-bottom">
          <button
            title={t("theme")}
            aria-label={t("theme")}
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          >
            {theme === "dark" ? <Sun size={20} /> : <Moon size={20} />}
          </button>
          <button
            title={t("language")}
            aria-label={t("language")}
            onClick={() =>
              void i18n.changeLanguage(i18n.language === "fa" ? "en" : "fa")
            }
          >
            <Globe2 size={20} />
            <small>{i18n.language.toUpperCase()}</small>
          </button>
          <button
            title={t("logout")}
            aria-label={t("logout")}
            onClick={() => {
              void api("/auth/logout", "POST").then(() => {
                setCsrf("");
                cache.clear();
                void cache.invalidateQueries();
              });
            }}
          >
            <LogOut size={19} />
          </button>
          <div className="avatar" title={session.data.username}>
            {session.data.username.slice(0, 2).toUpperCase()}
          </div>
        </div>
      </nav>
      <main className="main-shell">
        <header className="topbar">
          <div className="brand">
            <span>
              TUNNEL<span className="brand-light"> / MANAGER</span>
            </span>
            <span className="breadcrumb">/ {t(section)}</span>
          </div>
          <div className="workspace-indicator">
            <span className="status-dot succeeded" />
            {session.data.demo ? t("demo") : t("live")}
          </div>
        </header>
        {section === "topology" ? (
          <Workspace
            demo={session.data.demo}
            onVault={() => setSection("vault")}
          />
        ) : section === "vault" ? (
          <Vault />
        ) : (
          <Settings />
        )}
      </main>
    </div>
  );
}
