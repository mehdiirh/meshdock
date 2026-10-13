import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  ArrowLeftRight,
  Check,
  KeyRound,
  ShieldCheck,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { api, useTopology } from "../api";
import { JumpHostSettings, jumpValid } from "./JumpHostSettings";
import { newId, type Server, type Credential, type Role } from "../types";
import { Modal, Field, Spinner, ErrorMessage } from "./Primitives";
export function ServerDialog({
  server,
  onSave,
  onClose,
  pending,
  error,
  onVault,
  onDelete,
}: {
  server?: Server;
  onSave: (server: Server) => void;
  onClose: () => void;
  pending: boolean;
  error: unknown;
  onVault: () => void;
  onDelete?: () => void;
}) {
  const { t } = useTranslation();
  const [step, setStep] = useState(0);
  const [trusted, setTrusted] = useState(!!server);
  const [value, setValue] = useState<Server>(
    server || {
      id: newId(),
      name: "",
      address: "",
      host: "",
      ssh_port: 22,
      role: "entry",
      credential_id: "",
      fingerprint: "",
      region: "",
      position: { x: 100, y: 100 },
    },
  );
  const inventory = useTopology();
  const credentials = useQuery({
    queryKey: ["credentials"],
    queryFn: () => api<Credential[]>("/credentials"),
  });
  const discover = useMutation({
    mutationFn: (request: {
      host: string;
      ssh_port: number;
      ssh_jump: Server["ssh_jump"];
    }) => api<{ fingerprint: string }>("/servers/discover", "POST", request),
    onSuccess: (data, request) => {
      setValue((v) =>
        v.host === request.host &&
        v.ssh_port === request.ssh_port &&
        JSON.stringify(v.ssh_jump || null) ===
          JSON.stringify(request.ssh_jump || null)
          ? { ...v, fingerprint: data.fingerprint }
          : v,
      );
      setTrusted(false);
    },
  });
  function update<K extends keyof Server>(key: K, v: Server[K]) {
    setValue((s) => ({
      ...s,
      [key]: v,
      ...(key === "host" || key === "ssh_port" || key === "ssh_jump"
        ? { fingerprint: "" }
        : {}),
    }));
    if (key === "host" || key === "ssh_port" || key === "ssh_jump")
      setTrusted(false);
  }
  const roleIcons = {
    entry: ArrowDownToLine,
    exit: ArrowUpFromLine,
    both: ArrowLeftRight,
  };
  return (
    <Modal title={t(server ? "editServer" : "addServer")} onClose={onClose}>
      <div className="wizard-steps">
        {[0, 1, 2].map((i) => (
          <span key={i} className={step >= i ? "active" : ""}>
            {step > i ? <Check size={13} /> : i + 1}
          </span>
        ))}
      </div>
      <h3>{t(["serverIdentity", "serverAccess", "serverTrust"][step])}</h3>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (step < 2) setStep(step + 1);
          else onSave(value);
        }}
      >
        {step === 0 && (
          <>
            <div className="role-cards">
              {(["entry", "exit", "both"] as Role[]).map((role) => {
                const Icon = roleIcons[role];
                return (
                  <button
                    type="button"
                    className={value.role === role ? "active" : ""}
                    key={role}
                    onClick={() => update("role", role)}
                  >
                    <Icon size={22} />
                    {t(role)}
                  </button>
                );
              })}
            </div>
            <Field label={t("name")}>
              <input
                required
                value={value.name}
                maxLength={80}
                onChange={(e) => update("name", e.target.value)}
              />
            </Field>
            <div className="form-grid">
              <Field label={t("address")}>
                <input
                  className="mono"
                  required
                  value={value.address}
                  pattern="(?:[0-9]{1,3}\.){3}[0-9]{1,3}"
                  placeholder="192.0.2.10"
                  onChange={(e) => {
                    update("address", e.target.value);
                    if (!server && value.host === value.address)
                      update("host", e.target.value);
                  }}
                />
              </Field>
              <Field label={t("region")}>
                <input
                  maxLength={80}
                  value={value.region}
                  onChange={(e) => update("region", e.target.value)}
                />
              </Field>
            </div>
          </>
        )}
        {step === 1 && (
          <>
            <p className="muted small">{t("serverAccessHint")}</p>
            <div className="form-grid host-grid">
              <Field label={t("host")}>
                <input
                  className="mono"
                  required
                  value={value.host}
                  onChange={(e) => update("host", e.target.value)}
                />
              </Field>
              <Field label={t("sshPort")}>
                <input
                  className="mono"
                  type="number"
                  min={1}
                  max={65535}
                  required
                  value={value.ssh_port}
                  onChange={(e) => update("ssh_port", Number(e.target.value))}
                />
              </Field>
            </div>
            <span className="field-label">{t("credential")}</span>
            <div className="credential-choices">
              {credentials.data?.map((c) => (
                <button
                  type="button"
                  key={c.id}
                  className={value.credential_id === c.id ? "active" : ""}
                  onClick={() => update("credential_id", c.id)}
                >
                  <KeyRound size={19} />
                  <span>
                    {c.name}
                    <small>
                      {t(c.kind === "key" ? "privateKey" : "password")}
                    </small>
                  </span>
                  {value.credential_id === c.id && <Check size={16} />}
                </button>
              ))}
            </div>
            {!credentials.data?.length && (
              <p className="muted">{t("noCredentials")}</p>
            )}
            <button type="button" className="text-button" onClick={onVault}>
              {t("addCredential")}
            </button>
            <JumpHostSettings
              value={value.ssh_jump || null}
              onChange={(jump) => update("ssh_jump", jump)}
              servers={(inventory.data?.servers || []).filter(
                (candidate) =>
                  candidate.id !== value.id &&
                  !candidate.ssh_jump &&
                  !(
                    candidate.host === value.host &&
                    candidate.ssh_port === value.ssh_port
                  ),
              )}
              credentials={credentials.data || []}
            />
            <ErrorMessage error={credentials.error || inventory.error} />
          </>
        )}
        {step === 2 && (
          <>
            <div className="trust-graphic">
              <ShieldCheck size={38} />
            </div>
            <p className="muted small">{t("trustHint")}</p>
            <button
              type="button"
              className="button full"
              onClick={() =>
                discover.mutate({
                  host: value.host,
                  ssh_port: value.ssh_port,
                  ssh_jump: value.ssh_jump || null,
                })
              }
              disabled={discover.isPending}
            >
              {discover.isPending ? <Spinner /> : <KeyRound size={16} />}{" "}
              {t(discover.isPending ? "discovering" : "discover")}
            </button>
            {value.fingerprint && (
              <>
                <div className="fingerprint mono">{value.fingerprint}</div>
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={trusted}
                    onChange={(e) => setTrusted(e.target.checked)}
                  />
                  {t("trust")}
                </label>
              </>
            )}
            <ErrorMessage error={discover.error} />
          </>
        )}
        <ErrorMessage error={error} />
        <footer>
          {onDelete && (
            <button
              type="button"
              className="text-button danger-text"
              onClick={onDelete}
            >
              {t("deleteServer")}
            </button>
          )}
          {step > 0 ? (
            <button
              className="button"
              type="button"
              onClick={() => setStep(step - 1)}
            >
              {t("back")}
            </button>
          ) : (
            <button className="button" type="button" onClick={onClose}>
              {t("cancel")}
            </button>
          )}
          <button
            className="button primary"
            disabled={
              pending ||
              (step === 1 &&
                (!value.credential_id || !jumpValid(value.ssh_jump))) ||
              (step === 2 &&
                (!trusted || !value.fingerprint || !jumpValid(value.ssh_jump)))
            }
          >
            {pending ? <Spinner /> : null}
            {t(step === 2 ? "save" : "continue")}
          </button>
        </footer>
      </form>
    </Modal>
  );
}
