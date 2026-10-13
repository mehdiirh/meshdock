import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, RotateCcw, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api, useJobs, useTopology } from "../api";
import type { Job, Server } from "../types";
import { Confirm, ErrorMessage, Modal, Spinner } from "./Primitives";

export function ForceCleanupReport({
  job,
  revision,
}: {
  job: Job;
  revision: number;
}) {
  const { t } = useTranslation();
  const cache = useQueryClient();
  const [skip, setSkip] = useState(false);
  const result = job.force_delete!;
  const action = useMutation({
    mutationFn: (operation: string) =>
      api(`/jobs/${job.id}/${operation}`, "POST", { revision }),
    onSuccess: async () => {
      setSkip(false);
      await Promise.all([
        cache.invalidateQueries({ queryKey: ["jobs"] }),
        cache.invalidateQueries({ queryKey: ["topology"] }),
      ]);
    },
  });
  return (
    <section
      className="force-cleanup-report"
      aria-label={t("forceDelete.report")}
    >
      <strong>
        {t(
          job.status === "succeeded"
            ? "forceDelete.removed"
            : "forceDelete.removing",
          { name: result.server_name },
        )}
      </strong>
      <p className="muted small">{t("forceDelete.progressHint")}</p>
      {!result.hosts.length && (
        <p>
          <Spinner /> {t("forceDelete.queued")}
        </p>
      )}
      <div className="force-hosts">
        {result.hosts.map((host) => (
          <article
            key={host.server_id + host.host}
            className={"force-host " + host.status}
          >
            {host.status === "cleaned" ? (
              <CheckCircle2 size={18} />
            ) : (
              <AlertTriangle size={18} />
            )}
            <div>
              <strong>{host.name}</strong>
              <small className="mono">{host.host}</small>
              <span>{t("forceDelete.hostStatus." + host.status)}</span>
              {host.error_message && host.status !== "cleaned" && (
                <small>{host.error_message}</small>
              )}
            </div>
          </article>
        ))}
      </div>
      {job.status === "waiting_cleanup" && (
        <div className="force-actions">
          <button
            className="button"
            disabled={action.isPending}
            onClick={() => action.mutate("retry-cleanup")}
          >
            <RotateCcw size={16} />
            {t("forceDelete.retry")}
          </button>
          {result.can_skip && (
            <button
              className="button danger"
              disabled={action.isPending}
              onClick={() => setSkip(true)}
            >
              <Trash2 size={16} />
              {t("forceDelete.skip")}
            </button>
          )}
        </div>
      )}
      {job.error_code === "force_delete_orphans" && (
        <p className="force-warning">{t("forceDelete.orphans")}</p>
      )}
      <ErrorMessage error={action.error} />
      {skip && (
        <Confirm
          title={t("forceDelete.skip")}
          message={t("forceDelete.skipHint")}
          pending={action.isPending}
          onClose={() => setSkip(false)}
          onConfirm={() => action.mutate("skip-cleanup")}
        />
      )}
    </section>
  );
}

export function ForceDeleteDialog({
  server,
  onClose,
}: {
  server: Server;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const cache = useQueryClient();
  const topology = useTopology();
  const jobs = useJobs();
  const [acknowledged, setAcknowledged] = useState(false);
  const [jobId, setJobId] = useState<string>();
  const current = jobs.data?.find((job) => job.id === jobId);
  const start = useMutation({
    mutationFn: () =>
      api<{ job_id: string }>(`/servers/${server.id}/force-delete`, "POST", {
        revision: topology.data!.revision,
      }),
    onSuccess: async (result) => {
      setJobId(result.job_id);
      await Promise.all([
        cache.invalidateQueries({ queryKey: ["jobs"] }),
        cache.invalidateQueries({ queryKey: ["topology"] }),
      ]);
    },
  });
  return (
    <Modal
      title={t("forceDelete.title", { name: server.name })}
      onClose={onClose}
    >
      {jobId ? (
        current?.force_delete ? (
          <ForceCleanupReport
            job={current}
            revision={topology.data?.revision || 0}
          />
        ) : (
          <Spinner />
        )
      ) : (
        <>
          <p>{t("forceDelete.hint")}</p>
          <p className="muted small">{t("forceDelete.preserve")}</p>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(event) => setAcknowledged(event.target.checked)}
            />
            {t("forceDelete.acknowledge")}
          </label>
          <ErrorMessage error={start.error || topology.error} />
          <footer>
            <button className="button" onClick={onClose}>
              {t("cancel")}
            </button>
            <button
              className="button danger"
              disabled={!acknowledged || !topology.data || start.isPending}
              onClick={() => start.mutate()}
            >
              {start.isPending ? <Spinner /> : <Trash2 size={16} />}
              {t("forceDelete.action")}
            </button>
          </footer>
        </>
      )}
    </Modal>
  );
}
