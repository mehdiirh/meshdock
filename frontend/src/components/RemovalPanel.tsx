import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { RotateCcw, Undo2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api } from "../api";
import type { PendingRemoval, Server } from "../types";
import { Confirm, ErrorMessage } from "./Primitives";

export function RemovalPanel({
  removal,
  servers,
  revision,
  onClose,
  onForceDelete,
}: {
  removal: PendingRemoval;
  servers: Server[];
  revision: number;
  onClose: () => void;
  onForceDelete: (server: Server) => void;
}) {
  const { t } = useTranslation();
  const cache = useQueryClient();
  const [confirmation, setConfirmation] = useState<
    "retry-removal" | "restore" | null
  >(null);
  const action = useMutation({
    mutationFn: (operation: string) =>
      api(`/links/${removal.link.id}/${operation}`, "POST", { revision }),
    onSuccess: async () => {
      setConfirmation(null);
      await Promise.all([
        cache.invalidateQueries({ queryKey: ["topology"] }),
        cache.invalidateQueries({ queryKey: ["jobs"] }),
      ]);
    },
    onError: () => {
      setConfirmation(null);
      void cache.invalidateQueries({ queryKey: ["topology"] });
    },
  });
  const canAct =
    ["failed", "cancelled"].includes(removal.status) && !action.isPending;
  const serverName = (id: string) =>
    servers.find((server) => server.id === id)?.name || id;
  return (
    <aside className="inspector removal-panel" aria-label={t("removal.title")}>
      <header>
        <h2>{t("removal.title")}</h2>
        <button
          className="icon-button"
          onClick={onClose}
          aria-label={t("close")}
        >
          <X size={18} />
        </button>
      </header>
      <div className="removal-summary">
        <span className="pill">{removal.link.method.toUpperCase()}</span>
        <strong>
          {serverName(removal.link.entry_id)} →{" "}
          {serverName(removal.link.exit_id)}
        </strong>
        <p className="danger-text" role="status">
          {t("removal.status." + removal.status)}
        </p>
        <p>
          {t(
            removal.status === "recovery_required"
              ? "removal.uncertain"
              : "removal.explanation",
          )}
        </p>
      </div>
      <ErrorMessage error={action.error} />
      <div className="removal-actions">
        <button
          className="button danger"
          disabled={!canAct}
          onClick={() => setConfirmation("retry-removal")}
        >
          <RotateCcw size={16} />
          {t("removal.retry")}
        </button>
        <button
          className="button"
          disabled={!canAct}
          onClick={() => setConfirmation("restore")}
        >
          <Undo2 size={16} />
          {t("removal.restore")}
        </button>
      </div>
      {!canAct && (
        <p className="muted small">
          {t(
            removal.status === "recovery_required"
              ? "removal.recoverFirst"
              : "removal.wait",
          )}
        </p>
      )}
      <div className="force-removal-choices">
        <p className="muted small">{t("forceDelete.missingServer")}</p>
        {servers
          .filter((server) =>
            [removal.link.entry_id, removal.link.exit_id].includes(server.id),
          )
          .map((server) => (
            <button
              key={server.id}
              className="text-button danger-text"
              onClick={() => onForceDelete(server)}
            >
              {t("forceDelete.title", { name: server.name })}
            </button>
          ))}
      </div>
      {confirmation && (
        <Confirm
          title={t(
            confirmation === "restore" ? "removal.restore" : "removal.retry",
          )}
          message={t(
            confirmation === "restore"
              ? "removal.restoreHint"
              : "removal.retryHint",
          )}
          onClose={() => setConfirmation(null)}
          pending={action.isPending}
          onConfirm={() => action.mutate(confirmation)}
        />
      )}
    </aside>
  );
}
