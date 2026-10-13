import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, LockKeyhole, Plus, Trash2, ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api } from "../api";
import type { Credential } from "../types";
import { Modal, Field, ErrorMessage, Spinner, Confirm } from "./Primitives";
export function Vault() {
  const { t } = useTranslation();
  const cache = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"password" | "key">("key");
  const [secret, setSecret] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const credentials = useQuery({
    queryKey: ["credentials"],
    queryFn: () => api<Credential[]>("/credentials"),
  });
  const add = useMutation({
    mutationFn: () =>
      api("/credentials", "POST", { name, kind, secret, passphrase }),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["credentials"] });
      setAdding(false);
      setName("");
      setSecret("");
      setPassphrase("");
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => api("/credentials/" + id, "DELETE"),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["credentials"] });
      setDeleting(null);
    },
  });
  return (
    <section className="page-content">
      <div className="section-heading">
        <div>
          <span className="eyebrow">{t("vault")}</span>
          <h1>{t("vaultTitle")}</h1>
          <p>{t("vaultSubtitle")}</p>
        </div>
        <button className="button primary" onClick={() => setAdding(true)}>
          <Plus size={17} />
          {t("addCredential")}
        </button>
      </div>
      <ErrorMessage error={credentials.error || remove.error} />
      <div className="credential-grid">
        {credentials.data?.map((c) => (
          <article className="credential-card" key={c.id}>
            <div className="credential-icon">
              {c.kind === "key" ? <KeyRound /> : <LockKeyhole />}
            </div>
            <h3>{c.name}</h3>
            <p>{t(c.kind === "key" ? "privateKey" : "password")}</p>
            <div className="credential-bottom">
              <span>
                <ShieldCheck size={14} />
                {t("encrypted")}
              </span>
              <button
                className="icon-button danger-text"
                aria-label={t("delete")}
                onClick={() => setDeleting(c.id)}
              >
                <Trash2 size={16} />
              </button>
            </div>
          </article>
        ))}
        {!credentials.data?.length && (
          <button
            className="credential-card add-card"
            onClick={() => setAdding(true)}
          >
            <Plus size={32} />
            {t("addCredential")}
          </button>
        )}
      </div>
      {adding && (
        <Modal
          title={t("addCredential")}
          onClose={() => {
            setAdding(false);
            setSecret("");
            setPassphrase("");
          }}
        >
          <form
            onSubmit={(e) => {
              e.preventDefault();
              add.mutate();
            }}
          >
            <div className="segmented">
              <button
                type="button"
                className={kind === "key" ? "active" : ""}
                onClick={() => setKind("key")}
              >
                <KeyRound size={16} />
                {t("privateKey")}
              </button>
              <button
                type="button"
                className={kind === "password" ? "active" : ""}
                onClick={() => setKind("password")}
              >
                <LockKeyhole size={16} />
                {t("password")}
              </button>
            </div>
            <Field label={t("credentialName")}>
              <input
                required
                maxLength={80}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </Field>
            <Field label={t(kind === "key" ? "privateKey" : "password")}>
              {kind === "key" ? (
                <textarea
                  className="mono"
                  rows={7}
                  required
                  value={secret}
                  onChange={(e) => setSecret(e.target.value)}
                  autoComplete="off"
                />
              ) : (
                <input
                  type="password"
                  required
                  value={secret}
                  onChange={(e) => setSecret(e.target.value)}
                  autoComplete="new-password"
                />
              )}
            </Field>
            {kind === "key" && (
              <Field label={t("passphrase")}>
                <input
                  type="password"
                  value={passphrase}
                  onChange={(e) => setPassphrase(e.target.value)}
                />
              </Field>
            )}
            <ErrorMessage error={add.error} />
            <footer>
              <button
                type="button"
                className="button"
                onClick={() => setAdding(false)}
              >
                {t("cancel")}
              </button>
              <button className="button primary" disabled={add.isPending}>
                {add.isPending ? <Spinner /> : <ShieldCheck size={16} />}{" "}
                {t("storeCredential")}
              </button>
            </footer>
          </form>
        </Modal>
      )}
      {deleting && (
        <Confirm
          title={t("delete")}
          message={t("deleteCredentialHint")}
          onClose={() => setDeleting(null)}
          onConfirm={() => remove.mutate(deleting)}
          pending={remove.isPending}
        />
      )}
    </section>
  );
}
