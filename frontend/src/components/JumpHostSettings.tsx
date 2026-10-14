import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ArrowRight, Check, KeyRound, Network } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api } from "../api";
import type { Credential, Server, SSHJump } from "../types";
import { ErrorMessage, Field, Spinner } from "./Primitives";

const blankJump = (): SSHJump => ({
  host: "",
  ssh_port: 22,
  username: "root",
  credential_id: "",
  fingerprint: "",
});
export function jumpValid(jump?: SSHJump | null) {
  return (
    !jump ||
    (!!jump.host &&
      !!jump.username &&
      !!jump.credential_id &&
      !!jump.fingerprint &&
      jump.ssh_port >= 1 &&
      jump.ssh_port <= 65535)
  );
}

export function JumpHostSettings({
  value,
  onChange,
  servers,
  credentials,
}: {
  value: SSHJump | null;
  onChange: (value: SSHJump | null) => void;
  servers: Server[];
  credentials: Credential[];
}) {
  const { t } = useTranslation();
  const [observedKey, setObservedKey] = useState("");
  const discover = useMutation({
    mutationFn: (jump: SSHJump) =>
      api<{ fingerprint: string }>("/servers/discover", "POST", {
        host: jump.host,
        ssh_port: jump.ssh_port,
      }),
    onSuccess: (result, jump) => {
      setObservedKey(result.fingerprint);
      onChange({ ...jump, fingerprint: "" });
    },
  });
  function update(patch: Partial<SSHJump>) {
    if (!value) return;
    if ("host" in patch || "ssh_port" in patch) {
      setObservedKey("");
      patch.fingerprint = "";
    }
    onChange({ ...value, ...patch });
  }
  return (
    <fieldset className="jump-settings" disabled={discover.isPending}>
      <legend>{t("sshJump.title")}</legend>
      <div className="segmented">
        <button
          type="button"
          className={!value ? "active" : ""}
          onClick={() => {
            onChange(null);
            setObservedKey("");
          }}
        >
          {t("sshJump.direct")}
        </button>
        <button
          type="button"
          className={value ? "active" : ""}
          onClick={() => {
            if (!value) onChange(blankJump());
          }}
        >
          <Network size={16} />
          {t("sshJump.via")}
        </button>
      </div>
      {value && (
        <>
          <p className="muted small">{t("sshJump.hint")}</p>
          <p className="muted small">{t("board.oneHop")}</p>
          <div className="jump-route">
            <span>{t("sshJump.controller")}</span>
            <ArrowRight size={16} />
            <strong>{value.host || t("sshJump.jump")}</strong>
            <ArrowRight size={16} />
            <span>{t("sshJump.target")}</span>
          </div>
          {!!servers.length && (
            <>
              <span className="field-label">{t("sshJump.reuse")}</span>
              <div className="jump-choices">
                {servers.map((server) => (
                  <button
                    type="button"
                    key={server.id}
                    className={
                      value.host === server.host &&
                      value.ssh_port === server.ssh_port
                        ? "active"
                        : ""
                    }
                    onClick={() => {
                      setObservedKey("");
                      onChange({
                        host: server.host,
                        ssh_port: server.ssh_port,
                        username: "root",
                        credential_id: server.credential_id,
                        fingerprint: server.fingerprint,
                      });
                    }}
                  >
                    <Network size={16} />
                    <span>
                      {server.name}
                      <small className="mono">{server.host}</small>
                    </span>
                    {value.host === server.host && <Check size={15} />}
                  </button>
                ))}
              </div>
            </>
          )}
          <div className="form-grid host-grid">
            <Field label={t("sshJump.host")}>
              <input
                required
                className="mono"
                value={value.host}
                onChange={(e) => update({ host: e.target.value })}
              />
            </Field>
            <Field label={t("sshJump.port")}>
              <input
                required
                type="number"
                min={1}
                max={65535}
                value={value.ssh_port}
                onChange={(e) => update({ ssh_port: Number(e.target.value) })}
              />
            </Field>
          </div>
          <div className="form-grid">
            <Field label={t("sshJump.username")}>
              <input
                required
                value={value.username}
                pattern={"[a-zA-Z_][a-zA-Z0-9_.\\-]{0,63}[$]?"}
                onChange={(e) => update({ username: e.target.value })}
              />
            </Field>
            <Field label={t("sshJump.credential")}>
              <select
                required
                value={value.credential_id}
                onChange={(e) => update({ credential_id: e.target.value })}
              >
                <option value="">{t("sshJump.chooseCredential")}</option>
                {credentials.map((credential) => (
                  <option key={credential.id} value={credential.id}>
                    {credential.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <button
            type="button"
            className="button full"
            disabled={
              !value.host ||
              value.ssh_port < 1 ||
              value.ssh_port > 65535 ||
              discover.isPending
            }
            onClick={() => discover.mutate(value)}
          >
            {discover.isPending ? <Spinner /> : <KeyRound size={16} />}
            {t("sshJump.discover")}
          </button>
          {(observedKey || value.fingerprint) && (
            <>
              <div className="fingerprint mono">
                {observedKey || value.fingerprint}
              </div>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={!!value.fingerprint}
                  onChange={(e) => {
                    if (!e.target.checked) setObservedKey(value.fingerprint);
                    onChange({
                      ...value,
                      fingerprint: e.target.checked ? observedKey : "",
                    });
                  }}
                />
                {t("sshJump.trust")}
              </label>
            </>
          )}
          <ErrorMessage error={discover.error} />
        </>
      )}
    </fieldset>
  );
}
