import { useState, type FormEvent } from "react";
import { ArrowUpRight, Waypoints, Globe2 } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { api, setCsrf } from "../api";
import type { Session } from "../types";
import { Field, ErrorMessage, Spinner } from "./Primitives";
export function Login() {
  const { t, i18n } = useTranslation();
  const cache = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const login = useMutation({
    mutationFn: () =>
      api<Session>("/auth/login", "POST", { username, password }),
    onSuccess: (data) => {
      setCsrf(data.csrf);
      cache.setQueryData(["session"], data);
    },
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    login.mutate();
  }
  return (
    <div className="login-screen">
      <div className="login-art">
        <div className="brand">
          <Waypoints />
          <span>{t("appName")}</span>
        </div>
        <div className="orbit orbit-one" />
        <div className="orbit orbit-two" />
        <div className="orbit orbit-three" />
        <div className="orb orb-a" />
        <div className="orb orb-b" />
        <div className="orb orb-c" />
        <div className="login-statement">
          <span className="eyebrow">{t("selfHosted")}</span>
          <h1>{t("loginTitle")}</h1>
          <p>{t("loginSubtitle")}</p>
        </div>
        <span className="art-coordinate">01 / {t("controlPlane")}</span>
      </div>
      <div className="login-panel">
        <button
          className="language-button"
          onClick={() =>
            void i18n.changeLanguage(i18n.language === "fa" ? "en" : "fa")
          }
        >
          <Globe2 size={16} />
          {t("otherLanguage")}
        </button>
        <form onSubmit={submit}>
          <span className="eyebrow">{t("workspace")}</span>
          <h2>{t("signIn")}</h2>
          <Field label={t("username")}>
            <input
              autoComplete="username"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </Field>
          <Field label={t("password")}>
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          <ErrorMessage error={login.error} />
          <button className="button primary full" disabled={login.isPending}>
            {login.isPending ? <Spinner /> : <ArrowUpRight size={18} />}{" "}
            {t(login.isPending ? "signingIn" : "signIn")}
          </button>
        </form>
        <p className="login-foot">
          {t("appName")} <span>© {new Date().getFullYear()}</span>
        </p>
      </div>
    </div>
  );
}
