import type { Artifact, CompareResult, DocumentResponse, Run, Source } from "./types";

export type ExportFormat = "json" | "xlsx";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      detail = payload.detail ?? detail;
    } catch {
      // Keep the HTTP status when the server did not return JSON.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export const api = {
  sources: () => request<Source[]>("/api/sources"),
  createSource: (body: { url: string; name?: string }) =>
    request<Source>("/api/sources", { method: "POST", body: JSON.stringify(body) }),
  updateSource: (id: string, body: Partial<Pick<Source, "name" | "enabled" | "url">>) =>
    request<Source>(`/api/sources/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  createRun: (sourceId: string) =>
    request<Run>(`/api/sources/${sourceId}/runs`, { method: "POST" }),
  runs: (sourceId?: string, status?: string) => {
    const params = new URLSearchParams({ limit: "100" });
    if (sourceId) params.set("source_id", sourceId);
    if (status) params.set("status", status);
    return request<Run[]>(`/api/runs?${params.toString()}`);
  },
  run: (id: string) => request<Run>(`/api/runs/${id}`),
  document: (id: string, view: "recognized" | "revised" = "recognized") =>
    request<DocumentResponse>(`/api/runs/${id}/document?view=${view}`),
  compare: (id: string) => request<CompareResult>(`/api/runs/${id}/compare`),
  selectImage: (runId: string, candidateId: string) =>
    request<Run>(`/api/runs/${runId}/image-selection`, {
      method: "POST",
      body: JSON.stringify({ candidate_id: candidateId }),
    }),
  saveRevision: (runId: string, body: { base_document_sha256: string; document: object }) =>
    request<{ id: string }>(`/api/runs/${runId}/revision`, { method: "PUT", body: JSON.stringify(body) }),
  exportRun: (runId: string, revisionId: string | undefined, format: ExportFormat) =>
    request<{ artifacts: Artifact[] }>(`/api/runs/${runId}/exports`, {
      method: "POST",
      body: JSON.stringify({ revision_id: revisionId, formats: [format] }),
    }),
};
