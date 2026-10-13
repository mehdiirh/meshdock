import {
  QueryClient,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import i18n from "./i18n";
import type { Topology } from "./types";
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 3000, refetchOnWindowFocus: true },
    mutations: { retry: false },
  },
});
let csrf = "";
export function setCsrf(token: string) {
  csrf = token;
}
export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch("/api/v1" + path, {
    method,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "Accept-Language": i18n.language,
      "X-CSRF-Token": csrf,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok)
    throw new ApiError(
      data.code,
      data.message || i18n.t("requestFailed"),
      response.status,
    );
  return data;
}
export function useTopology() {
  return useQuery({
    queryKey: ["topology"],
    queryFn: () => api<Topology>("/topology"),
    refetchInterval: 5000,
  });
}
export function useSaveTopology() {
  const cache = useQueryClient();
  return useMutation({
    mutationFn: (topology: Topology) =>
      api<{ revision: number; job_id: string }>("/topology", "PUT", {
        revision: topology.revision,
        servers: topology.servers,
        links: topology.links,
      }),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["topology"] });
      void cache.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: () => {
      void cache.invalidateQueries({ queryKey: ["topology"] });
    },
  });
}
