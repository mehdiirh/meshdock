import type { Job } from "./types";

export function latestJob(jobs: Job[] = []) {
  return [...jobs].sort(
    (a, b) => b.revision - a.revision || b.created - a.created,
  )[0];
}

export function jobStatus(job: Job) {
  if (job.status === "succeeded" && job.error_code === "force_delete_orphans")
    return "cleanup_skipped";
  return job.cancel_requested && ["running", "recovering"].includes(job.status)
    ? "cancelling"
    : job.status;
}

export function linkDeploymentStatus(
  id: string,
  revision: number,
  applied: number,
  jobs: Job[] = [],
) {
  const job = latestJob(
    jobs.filter(
      (j) => j.revision === revision && (j.link_ids || []).includes(id),
    ),
  );
  if (job) return jobStatus(job);
  const current = latestJob(jobs.filter((j) => j.revision === revision));
  if (current?.link_ids && !current.link_ids.includes(id)) return "succeeded";
  return revision === applied ? "succeeded" : "queued";
}

export function failedDeployment(status: string) {
  return [
    "failed",
    "retrying",
    "recovery_required",
    "cancelled",
    "waiting_cleanup",
  ].includes(status);
}

export function failurePhase(detail?: string) {
  try {
    const value = JSON.parse(detail || "{}").phase;
    return ["preparing", "applying", "checking", "committing"].includes(value)
      ? value
      : null;
  } catch {
    return null;
  }
}
