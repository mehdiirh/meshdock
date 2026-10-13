import { expect, it } from "vitest";
import {
  latestJob,
  jobStatus,
  failedDeployment,
  linkDeploymentStatus,
} from "./deployments";
import type { Job } from "./types";
const job = (revision: number, status: string, created = revision): Job => ({
  id: String(revision),
  revision,
  status,
  created,
  kind: "deploy",
  attempt: 1,
  error_code: null,
  link_ids: ["link"],
});
it("uses the latest revision instead of historical job selection", () => {
  expect(
    latestJob([job(1, "succeeded", 99), job(2, "failed", 1)])?.revision,
  ).toBe(2);
});
it("marks failed revisions and follows newer attempts", () => {
  expect(linkDeploymentStatus("link", 2, 1, [job(2, "failed")])).toBe("failed");
  expect(linkDeploymentStatus("link", 3, 1, [job(2, "failed")])).toBe("queued");
  expect(linkDeploymentStatus("other", 2, 1, [job(2, "failed")])).toBe(
    "succeeded",
  );
  expect(failedDeployment("retrying")).toBe(true);
  expect(failedDeployment("recovery_required")).toBe(true);
  expect(jobStatus({ ...job(2, "running"), cancel_requested: 1 })).toBe(
    "cancelling",
  );
});
