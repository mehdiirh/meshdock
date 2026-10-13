import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  X,
  Plus,
  Trash2,
  ArrowRight,
  ShieldCheck,
  Radio,
  Save,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { api } from "../api";
import { mappingStatus } from "../ports";
import type { Link, Server, MethodInfo, Policy } from "../types";
import { Field, ErrorMessage, Spinner } from "./Primitives";
export function LinkPanel({
  link,
  servers,
  onSave,
  onClose,
  onDelete,
  pending,
  error,
  count = 1,
}: {
  link: Link;
  servers: Server[];
  onSave: (l: Link) => void;
  onClose: () => void;
  onDelete?: () => void;
  pending: boolean;
  error: unknown;
  count?: number;
}) {
  const { t } = useTranslation();
  const [value, setValue] = useState(link);
  const [exclusions, setExclusions] = useState(
    link.ports.map((p) => (p.exclude || []).join(", ")),
  );
  const methods = useQuery({
    queryKey: ["methods"],
    queryFn: () => api<MethodInfo[]>("/methods"),
  });
  const method = methods.data?.find((m) => m.id === value.method);
  const status = mappingStatus(
    value.ports,
    method,
    servers.find((s) => s.id === value.entry_id)?.ssh_port,
  );
  return (
    <aside className="inspector">
      <header>
        <div>
          <span className="eyebrow">{t("connection")}</span>
          <h2>
            {count > 1
              ? t("batch", { count })
              : t(onDelete ? "connection" : "newConnection")}
          </h2>
        </div>
        <button
          className="icon-button"
          aria-label={t("close")}
          onClick={onClose}
        >
          <X size={18} />
        </button>
      </header>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!status.error && method) onSave(value);
        }}
      >
        <div className="route-preview">
          <span>{servers.find((s) => s.id === link.entry_id)?.name}</span>
          <ArrowRight size={18} />
          <span>{servers.find((s) => s.id === link.exit_id)?.name}</span>
        </div>
        <Field label={t("transport")}>
          <div className="method-grid">
            {methods.data?.map((m) => (
              <button
                type="button"
                className={value.method === m.id ? "active" : ""}
                key={m.id}
                onClick={() =>
                  setValue((v) => ({
                    ...v,
                    method: m.id,
                    control_port: m.control_protocol ? v.control_port : null,
                  }))
                }
              >
                {m.encrypted ? <ShieldCheck size={16} /> : <Radio size={16} />}
                <span>{m.name}</span>
              </button>
            ))}
          </div>
        </Field>
        <div className={"method-note " + (method?.encrypted ? "secure" : "")}>
          {method?.encrypted ? <ShieldCheck size={14} /> : <Radio size={14} />}
          <span>{t(method?.encrypted ? "encrypted" : "unencrypted")}</span>
        </div>
        {method?.caveat && (
          <p className="small muted method-caveat">
            {t("caveats." + method.caveat)}
          </p>
        )}
        {method?.control_protocol && (
          <Field label={t("controlPort")}>
            <input
              aria-label={t("controlPort")}
              type="number"
              min={1}
              max={65535}
              className="mono"
              placeholder={t("automaticPort")}
              value={value.control_port ?? ""}
              onChange={(event) =>
                setValue((current) => ({
                  ...current,
                  control_port: event.target.value
                    ? Number(event.target.value)
                    : null,
                }))
              }
            />
            <small className="muted">
              {t("controlPortHint", {
                protocol: method.control_protocol.toUpperCase(),
              })}
            </small>
          </Field>
        )}
        <div className="field-heading">
          <h3>{t("portMappings")}</h3>
          <button
            className="text-button"
            type="button"
            disabled={value.ports.length >= 16}
            onClick={() =>
              setValue((v) => ({
                ...v,
                ports: [
                  ...v.ports,
                  { public: 8443, target: 8443, host: "127.0.0.1" },
                ],
              }))
            }
          >
            <Plus size={15} />
            {t("addPort")}
          </button>
        </div>
        {value.ports.map((port, i) => (
          <div className="port-card" key={i}>
            <div className="port-row">
              <Field label={t("publicPort")}>
                <input
                  className="mono"
                  aria-label={`${t("publicPort")} ${i + 1}`}
                  type="text"
                  dir="ltr"
                  placeholder="8000-8099"
                  required
                  value={port.public}
                  onChange={(e) =>
                    setValue((v) => ({
                      ...v,
                      ports: v.ports.map((p, n) =>
                        n === i ? { ...p, public: e.target.value } : p,
                      ),
                    }))
                  }
                />
              </Field>
              <ArrowRight size={17} />
              <Field label={t("targetPort")}>
                <input
                  className="mono"
                  aria-label={`${t("targetPort")} ${i + 1}`}
                  type="text"
                  dir="ltr"
                  placeholder="8000-8099"
                  required
                  value={port.target}
                  onChange={(e) =>
                    setValue((v) => ({
                      ...v,
                      ports: v.ports.map((p, n) =>
                        n === i ? { ...p, target: e.target.value } : p,
                      ),
                    }))
                  }
                />
              </Field>
              <button
                aria-label={t("delete")}
                type="button"
                className="icon-button"
                disabled={value.ports.length === 1}
                onClick={() => {
                  setExclusions((items) => items.filter((_, n) => n !== i));
                  setValue((v) => ({
                    ...v,
                    ports: v.ports.filter((_, n) => n !== i),
                  }));
                }}
              >
                <Trash2 size={14} />
              </button>
            </div>
            <Field label={t("excludedPorts")}>
              <input
                className="mono"
                dir="ltr"
                type="text"
                aria-label={`${t("excludedPorts")} ${i + 1}`}
                placeholder="8080, 9000-9010"
                value={exclusions[i] || ""}
                onChange={(event) => {
                  const text = event.target.value;
                  setExclusions((items) => {
                    const next = [...items];
                    next[i] = text;
                    return next;
                  });
                  setValue((v) => ({
                    ...v,
                    ports: v.ports.map((p, n) =>
                      n === i
                        ? {
                            ...p,
                            exclude: text
                              .split(",")
                              .map((part) => part.trim())
                              .filter(Boolean),
                          }
                        : p,
                    ),
                  }));
                }}
              />
            </Field>
            <small className="muted">{t("exclusionHint")}</small>
            <Field label={t("targetHost")}>
              <input
                className="mono"
                required
                value={port.host}
                onChange={(e) =>
                  setValue((v) => ({
                    ...v,
                    ports: v.ports.map((p, n) =>
                      n === i ? { ...p, host: e.target.value } : p,
                    ),
                  }))
                }
              />
            </Field>
          </div>
        ))}
        <div className="mapping-summary" aria-live="polite">
          <strong>{t("mappedPortCount", { count: status.count })}</strong>
          <span>
            {t(status.native ? "nativeRangeMode" : "expandedRangeMode", {
              max: method?.mapping.max_listener_ports,
            })}
          </span>
          {!status.native && <small>{t("socketCapacityHint")}</small>}
          {method?.mapping.forwards_per_session && (
            <small>
              {t("sshSessionCount", {
                count: Math.ceil(
                  status.count / method.mapping.forwards_per_session,
                ),
                size: method.mapping.forwards_per_session,
              })}
            </small>
          )}
          <small>{t("mappingPlatform")}</small>
        </div>
        {status.error && (
          <div role="alert" className="error">
            {t(status.error, { max: method?.mapping.max_ports })}
          </div>
        )}
        <p className="small muted">{t("actualPortConflicts")}</p>
        {!status.native && status.count > 4096 && (
          <p className="small muted">{t("outgoingPortHint")}</p>
        )}
        {status.native ? (
          <p className="small muted">{t("nativePoolHint")}</p>
        ) : (
          <>
            <Field label={t("policy")}>
              <div className="policy-options">
                {(["roundrobin", "leastconn", "failover"] as Policy[]).map(
                  (policy) => (
                    <button
                      key={policy}
                      type="button"
                      className={value.policy === policy ? "active" : ""}
                      onClick={() => setValue((v) => ({ ...v, policy }))}
                    >
                      {t(policy)}
                    </button>
                  ),
                )}
              </div>
            </Field>
            <p className="small muted">{t("poolHint")}</p>
          </>
        )}
        <div className="form-grid">
          {!status.native && (
            <Field label={t("weight")}>
              <input
                type="number"
                min={1}
                max={256}
                required
                value={value.weight}
                onChange={(e) =>
                  setValue((v) => ({ ...v, weight: Number(e.target.value) }))
                }
              />
            </Field>
          )}
          <label className="checkbox">
            <input
              type="checkbox"
              checked={value.enabled}
              onChange={(e) =>
                setValue((v) => ({ ...v, enabled: e.target.checked }))
              }
            />
            {t("enabled")}
          </label>
        </div>
        <p className="small muted">
          {t(
            status.native
              ? "nativeHealthHint"
              : value.ports.some(
                    (p) => String(p.public).includes("-") || p.exclude?.length,
                  )
                ? "rangeHealthHint"
                : "destinationRequired",
          )}
        </p>
        <ErrorMessage error={error || methods.error} />
        <div className="inspector-footer">
          <p>{t("deploymentHint")}</p>
          <button
            className="button primary full"
            disabled={pending || !!status.error || !method}
          >
            {pending ? <Spinner /> : <Save size={16} />} {t("save")}
          </button>
          {onDelete && (
            <button
              type="button"
              className="text-button danger-text full"
              onClick={onDelete}
            >
              <Trash2 size={14} />
              {t("removeConnection")}
            </button>
          )}
        </div>
      </form>
    </aside>
  );
}
