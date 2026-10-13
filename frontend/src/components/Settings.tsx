import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Plus, Copy, KeyRound, ArrowUpRight } from "lucide-react";
import { api } from "../api";
import type { Key } from "../types";
import { Field, ErrorMessage, Modal, Confirm } from "./Primitives";
export function Settings() {
  const { t, i18n } = useTranslation();
  const cache = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [scope, setScope] = useState("read");
  const [token, setToken] = useState("");
  const [copied, setCopied] = useState(false);
  const [revoking, setRevoking] = useState<string>();
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const keys = useQuery({
    queryKey: ["keys"],
    queryFn: () => api<Key[]>("/keys"),
  });
  const activity = useQuery({
    queryKey: ["audit"],
    queryFn: () =>
      api<
        {
          id: number;
          actor: string;
          action: string;
          detail: string;
          created: number;
        }[]
      >("/audit"),
    refetchInterval: 10000,
  });
  const create = useMutation({
    mutationFn: () => api<{ token: string }>("/keys", "POST", { name, scope }),
    onSuccess: (data) => {
      setAdding(false);
      setToken(data.token);
      setCopied(false);
      void cache.invalidateQueries({ queryKey: ["keys"] });
    },
  });
  const revoke = useMutation({
    mutationFn: (id: string) => api("/keys/" + id, "DELETE"),
    onSuccess: () => {
      setRevoking(undefined);
      void cache.invalidateQueries({ queryKey: ["keys"] });
    },
  });
  const change = useMutation({
    mutationFn: () => api("/auth/password", "POST", { current, password }),
    onSuccess: () => {
      cache.clear();
      location.reload();
    },
  });
  return (
    <section className="page-content">
      <div className="section-heading">
        <div>
          <span className="eyebrow">{t("access")}</span>
          <h1>{t("keys")}</h1>
          <p>{t("keyHint")}</p>
        </div>
        <button className="button primary" onClick={() => setAdding(true)}>
          <Plus size={16} />
          {t("createKey")}
        </button>
      </div>
      <ErrorMessage error={keys.error || revoke.error} />
      <div className="key-list">
        {keys.data
          ?.filter((k) => !k.revoked)
          .map((key) => (
            <article key={key.id}>
              <KeyRound size={22} />
              <div>
                <strong>{key.name}</strong>
                <code>{key.prefix}••••••••</code>
              </div>
              <span className="pill">{t(key.scope)}</span>
              <button
                className="text-button danger-text"
                onClick={() => setRevoking(key.id)}
              >
                {t("revoke")}
              </button>
            </article>
          ))}
      </div>
      <a
        className="text-button api-docs"
        href="/api/openapi.json"
        target="_blank"
        rel="noreferrer"
      >
        {t("apiDocs")}
        <ArrowUpRight size={15} />
      </a>
      <div className="settings-grid">
        <section className="surface">
          <h2>{t("changePassword")}</h2>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              change.mutate();
            }}
          >
            <Field label={t("currentPassword")}>
              <input
                autoComplete="current-password"
                type="password"
                required
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
              />
            </Field>
            <Field label={t("newPassword")}>
              <input
                autoComplete="new-password"
                type="password"
                required
                minLength={12}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>
            <ErrorMessage error={change.error} />
            <button className="button" disabled={change.isPending}>
              {t("changePassword")}
            </button>
          </form>
        </section>
        <section className="surface audit">
          <h2>{t("activity")}</h2>
          <ErrorMessage error={activity.error} />
          {activity.data?.map((a) => (
            <div key={a.id}>
              <span>
                <strong>
                  {t("auditActions." + a.action, { defaultValue: a.action })}
                </strong>
                <small className="mono">{a.actor}</small>
              </span>
              <time>
                {new Date(a.created * 1000).toLocaleString(i18n.language)}
              </time>
            </div>
          ))}
        </section>
      </div>
      {adding && (
        <Modal title={t("createKey")} onClose={() => setAdding(false)}>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate();
            }}
          >
            <Field label={t("keyName")}>
              <input
                required
                maxLength={80}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </Field>
            <Field label={t("scope")}>
              <div className="policy-options">
                {["read", "write", "admin"].map((s) => (
                  <button
                    type="button"
                    className={scope === s ? "active" : ""}
                    onClick={() => setScope(s)}
                    key={s}
                  >
                    {t(s)}
                  </button>
                ))}
              </div>
            </Field>
            <ErrorMessage error={create.error} />
            <footer>
              <button className="button primary" disabled={create.isPending}>
                {t("createKey")}
              </button>
            </footer>
          </form>
        </Modal>
      )}
      {token && (
        <Modal title={t("keyOnce")} onClose={() => setToken("")}>
          <p className="fingerprint mono">{token}</p>
          <button
            className="button"
            onClick={() => {
              void navigator.clipboard
                .writeText(token)
                .then(() => setCopied(true));
            }}
          >
            <Copy size={16} />
            {t(copied ? "copied" : "copy")}
          </button>
        </Modal>
      )}
      {revoking && (
        <Confirm
          title={t("revoke")}
          message={t("revoke")}
          onClose={() => setRevoking(undefined)}
          onConfirm={() => revoke.mutate(revoking)}
        />
      )}
    </section>
  );
}
