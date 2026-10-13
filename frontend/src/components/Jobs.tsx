import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronUp,
  Clock3,
  RotateCcw,
  Activity,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { api } from "../api";
import type { Job, Log, Server } from "../types";
import { ErrorMessage } from "./Primitives";
export function Jobs({ servers }: { servers: Server[] }) {
  const { t, i18n } = useTranslation();
  const cache = useQueryClient();
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<string>();
  const jobs = useQuery({
    queryKey: ["jobs"],
    queryFn: () => api<Job[]>("/jobs"),
    refetchInterval: 2500,
  });
  const active = selected
    ? jobs.data?.find((j) => j.id === selected)
    : jobs.data?.[0];
  const logs = useQuery({
    queryKey: ["logs", active?.id, i18n.language],
    queryFn: async () => {
      const persisted: Log[] = [];
      let after = 0;
      while (true) {
        const page = await api<Log[]>(
          `/jobs/${active!.id}/logs?after=${after}`,
        );
        persisted.push(...page);
        if (page.length < 500) break;
        after = page[page.length - 1].id;
      }
      // A stream may have delivered newer events while the history request ran.
      const streamed =
        cache.getQueryData<Log[]>(["logs", active!.id, i18n.language]) || [];
      const combined = new Map(
        [...persisted, ...streamed].map((entry) => [entry.id, entry]),
      );
      return [...combined.values()].sort((left, right) => left.id - right.id);
    },
    enabled: open && !!active,
    refetchInterval: open ? 5000 : false,
  });
  useEffect(() => {
    if (!open || !active) return;
    const source = new EventSource(
      "/api/v1/jobs/" +
        active.id +
        "/events?lang=" +
        encodeURIComponent(i18n.language) +
        "&after=" +
        (logs.data?.at(-1)?.id || 0),
    );
    source.onmessage = (event) => {
      const incoming: Log = JSON.parse(event.data);
      cache.setQueryData<Log[]>(
        ["logs", active.id, i18n.language],
        (previous) =>
          previous?.some((l) => l.id === incoming.id)
            ? previous
            : [...(previous || []), incoming],
      );
    };
    source.addEventListener("done", () => {
      source.close();
      void cache.invalidateQueries({ queryKey: ["jobs"] });
      void cache.invalidateQueries({ queryKey: ["topology"] });
    });
    return () => source.close();
  }, [open, active?.id, i18n.language, cache]);
  const recover = useMutation({
    mutationFn: (id: string) => api("/jobs/" + id + "/recover", "POST"),
    onSuccess: () => void cache.invalidateQueries({ queryKey: ["jobs"] }),
  });
  return (
    <section className={"jobs-drawer " + (open ? "expanded" : "")}>
      <button className="jobs-bar" onClick={() => setOpen(!open)}>
        <span>
          <Activity size={17} />
          <strong>{t("jobs")}</strong>
          <span className="count-badge">{jobs.data?.length || 0}</span>
        </span>
        <span>
          {active ? (
            <>
              <span className={"status-dot " + active.status} />
              <span>{t("status." + active.status)}</span>
              <span className="muted">r{active.revision}</span>
            </>
          ) : (
            <span className="muted">{t("noJobs")}</span>
          )}
          {open ? <ChevronDown size={18} /> : <ChevronUp size={18} />}
        </span>
      </button>
      {open && (
        <div className="jobs-body">
          <div className="job-list">
            {jobs.data?.map((job) => (
              <button
                key={job.id}
                className={active?.id === job.id ? "active" : ""}
                onClick={() => setSelected(job.id)}
              >
                <span className={"status-dot " + job.status} />
                <span>
                  <strong>
                    {t("revision")} {job.revision}
                  </strong>
                  <small>{t("status." + job.status)}</small>
                </span>
                <time>
                  {new Date(job.created * 1000).toLocaleTimeString(
                    i18n.language,
                    { hour: "2-digit", minute: "2-digit" },
                  )}
                </time>
              </button>
            ))}
          </div>
          <div className="log-pane">
            <header>
              <span>
                <Clock3 size={14} />
                {t("liveLogs")}
              </span>
              {active && (
                <span className="muted">
                  {t("attempt")} {active.attempt}
                </span>
              )}
              {active?.status === "recovery_required" && (
                <button
                  className="text-button"
                  disabled={recover.isPending}
                  onClick={() => recover.mutate(active.id)}
                >
                  <RotateCcw size={14} />
                  {t("recover")}
                </button>
              )}
            </header>
            <ErrorMessage error={jobs.error || logs.error || recover.error} />
            <div className="log-lines" aria-live="polite">
              {logs.data?.map((log) => (
                <div className={"log-line " + log.level} key={log.id}>
                  <time className="mono">
                    {new Date(log.created * 1000).toLocaleTimeString(
                      i18n.language,
                    )}
                  </time>
                  <span className="log-server">
                    {servers.find((s) => s.id === log.server_id)?.name || "—"}
                  </span>
                  <span>
                    {log.message}
                    {log.detail && (
                      <small className="mono"> {log.detail}</small>
                    )}
                  </span>
                </div>
              ))}
              {!logs.data?.length && <p className="muted">{t("noLogs")}</p>}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
