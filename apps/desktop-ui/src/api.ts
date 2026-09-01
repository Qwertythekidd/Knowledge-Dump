import type {
  Account,
  ActivityEvent,
  CloudFile,
  Device,
  DownloadGrant,
  FileVersion,
  SessionResponse,
  StorageHealth,
  UploadPartGrant,
  UploadSession,
} from "@knowledge-dump/protocol";

const TOKEN_KEY = "knowledge-dump.session-token";
const REFRESH_KEY = "knowledge-dump.refresh-token";
const DEVICE_KEY = "knowledge-dump.device-id";
const GATEWAY_KEY = "knowledge-dump.gateway-url";
let refreshInFlight: Promise<SessionResponse> | null = null;

function gatewayBase(): string {
  return (window.localStorage.getItem(GATEWAY_KEY) || import.meta.env.VITE_KNOWLEDGE_DUMP_GATEWAY_URL || "/api").replace(/\/$/, "");
}

function token(): string {
  return window.sessionStorage.getItem(TOKEN_KEY) || "";
}

function refreshToken(): string {
  return window.sessionStorage.getItem(REFRESH_KEY) || "";
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<{ response: Response; body: T & { error?: string } }> {
  const response = await fetch(`${gatewayBase()}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(token() ? { Authorization: `Bearer ${token()}` } : {}),
      ...(init?.headers || {}),
    },
  });
  const body = await response.json().catch(() => ({})) as T & { error?: string };
  return { response, body };
}

async function request<T>(path: string, init?: RequestInit, retryRefresh = true): Promise<T> {
  let result = await fetchJson<T>(path, init);
  if (result.response.status === 401 && retryRefresh && refreshToken() && path !== "/v1/auth/refresh") {
    await refreshSession();
    result = await fetchJson<T>(path, init);
  }
  if (!result.response.ok) throw new Error(result.body.error || `Request failed (${result.response.status})`);
  return result.body;
}

function persistSession(result: SessionResponse): void {
  window.sessionStorage.setItem(TOKEN_KEY, result.accessToken);
  window.sessionStorage.setItem(REFRESH_KEY, result.refreshToken);
  window.localStorage.setItem(DEVICE_KEY, result.device.id);
}

function clearSession(): void {
  window.sessionStorage.removeItem(TOKEN_KEY);
  window.sessionStorage.removeItem(REFRESH_KEY);
}

async function refreshSession(): Promise<SessionResponse> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      const currentRefreshToken = refreshToken();
      const { response, body } = await fetchJson<SessionResponse>("/v1/auth/refresh", {
        method: "POST",
        body: JSON.stringify({ refreshToken: currentRefreshToken }),
      });
      if (!response.ok) {
        clearSession();
        throw new Error(body.error || "refresh_token_invalid");
      }
      persistSession(body);
      return body;
    })().finally(() => { refreshInFlight = null; });
  }
  return refreshInFlight;
}

export function savedToken(): string {
  return token() || refreshToken();
}

export function saveGatewayUrl(value: string): void {
  const normalized = value.trim().replace(/\/$/, "");
  if (normalized) window.localStorage.setItem(GATEWAY_KEY, normalized);
  else window.localStorage.removeItem(GATEWAY_KEY);
}

export function currentGatewayUrl(): string {
  return gatewayBase();
}

export async function login(email: string, password: string): Promise<SessionResponse> {
  try {
    const result = await request<SessionResponse>("/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({
        email,
        password,
        deviceId: window.localStorage.getItem(DEVICE_KEY) || null,
        deviceLabel: `Knowledge Dump on ${navigator.platform || "this workstation"}`,
        platform: navigator.platform || "unknown",
      }),
    }, false);
    persistSession(result);
    return result;
  } catch (reason) {
    if (reason instanceof Error && reason.message === "device_revoked") {
      window.localStorage.removeItem(DEVICE_KEY);
    }
    throw reason;
  }
}

export async function session(): Promise<Account> {
  const result = await request<{ account: Account; device: Device }>("/v1/auth/session");
  return result.account;
}

export async function logout(): Promise<void> {
  try {
    if (token()) await request("/v1/auth/logout", { method: "POST", body: JSON.stringify({}) }, false);
  } finally {
    clearSession();
  }
}

export async function storageHealth(): Promise<StorageHealth> {
  return request<StorageHealth>("/v1/storage/health");
}

export async function devices(): Promise<{ devices: Device[]; currentDeviceId: string }> {
  return request<{ devices: Device[]; currentDeviceId: string }>("/v1/devices");
}

export async function revokeDevice(deviceId: string): Promise<void> {
  await request(`/v1/devices/${encodeURIComponent(deviceId)}`, { method: "DELETE" });
}

export async function files(parentId: string | null, status = "active", search = ""): Promise<CloudFile[]> {
  const params = new URLSearchParams({ status });
  if (parentId) params.set("parentId", parentId);
  if (search.trim()) params.set("search", search.trim());
  const result = await request<{ files: CloudFile[] }>(`/v1/files?${params}`);
  return result.files;
}

export async function fileVersions(fileId: string): Promise<FileVersion[]> {
  const result = await request<{ versions: FileVersion[] }>(`/v1/files/${encodeURIComponent(fileId)}/versions`);
  return result.versions;
}

export async function createFolder(name: string, parentId: string | null): Promise<CloudFile> {
  const result = await request<{ file: CloudFile }>("/v1/folders", {
    method: "POST",
    body: JSON.stringify({ name, parentId }),
  });
  return result.file;
}

async function initiateUpload(file: File, parentId: string | null): Promise<UploadSession> {
  const result = await request<{ upload: UploadSession }>("/v1/uploads", {
    method: "POST",
    body: JSON.stringify({
      name: file.name,
      parentId,
      kind: kindForFile(file),
      mimeType: file.type || null,
      sizeBytes: file.size,
    }),
  });
  return result.upload;
}

export async function uploadStatus(uploadId: string): Promise<UploadSession> {
  const result = await request<{ upload: UploadSession }>(`/v1/uploads/${encodeURIComponent(uploadId)}`);
  return result.upload;
}

export async function abortUpload(uploadId: string): Promise<void> {
  await request(`/v1/uploads/${encodeURIComponent(uploadId)}`, { method: "DELETE" });
}

export async function uploadFile(
  file: File,
  parentId: string | null,
  onProgress: (progress: number) => void,
  onSession: (session: UploadSession) => void,
  signal?: AbortSignal,
  existingUploadId?: string,
): Promise<CloudFile> {
  let upload = existingUploadId ? await uploadStatus(existingUploadId) : await initiateUpload(file, parentId);
  if (upload.name !== file.name || upload.sizeBytes !== file.size) throw new Error("upload_source_mismatch");
  if (upload.status === "completed" || upload.status === "completing") {
    const reconciled = await request<{ file: CloudFile; upload: UploadSession }>(
      `/v1/uploads/${encodeURIComponent(upload.id)}/complete`,
      { method: "POST", body: JSON.stringify({}), signal },
    );
    onSession(reconciled.upload);
    onProgress(100);
    return reconciled.file;
  }
  if (!(["initiated", "uploading"] as string[]).includes(upload.status)) throw new Error("upload_not_active");
  onSession(upload);

  const completed = new Set(upload.completedParts.map((part) => part.partNumber));
  let completedBytes = upload.completedParts.reduce((total, part) => total + part.sizeBytes, 0);
  const missing = Array.from({ length: upload.totalParts }, (_, index) => index + 1).filter((partNumber) => !completed.has(partNumber));
  const grants: UploadPartGrant[] = [];
  for (let offset = 0; offset < missing.length; offset += 25) {
    const result = await request<{ parts: UploadPartGrant[] }>(`/v1/uploads/${encodeURIComponent(upload.id)}/parts`, {
      method: "POST",
      body: JSON.stringify({ partNumbers: missing.slice(offset, offset + 25) }),
      signal,
    });
    grants.push(...result.parts);
  }

  let cursor = 0;
  async function worker(): Promise<void> {
    while (cursor < grants.length) {
      const grant = grants[cursor];
      cursor += 1;
      const start = (grant.partNumber - 1) * upload.partSize;
      const end = Math.min(file.size, start + upload.partSize);
      const body = file.slice(start, end);
      const response = await fetch(resolveTransferUrl(grant.url), {
        method: grant.method,
        headers: grant.headers,
        body,
        signal,
      });
      if (!response.ok) throw new Error(`upload_part_failed_${response.status}`);
      const etag = response.headers.get("ETag");
      if (!etag) throw new Error("upload_part_etag_missing");
      const reported = await request<{ upload: UploadSession }>(
        `/v1/uploads/${encodeURIComponent(upload.id)}/parts/${grant.partNumber}/complete`,
        { method: "POST", body: JSON.stringify({ etag, sizeBytes: body.size }), signal },
      );
      upload = reported.upload;
      completedBytes += body.size;
      onSession(upload);
      onProgress(file.size ? Math.min(94, Math.round(completedBytes / file.size * 94)) : 94);
    }
  }
  const workers = await Promise.allSettled(
    Array.from({ length: Math.min(3, Math.max(1, grants.length)) }, () => worker()),
  );
  const failedWorker = workers.find((result): result is PromiseRejectedResult => result.status === "rejected");
  if (failedWorker) throw failedWorker.reason;
  onProgress(96);
  const completedUpload = await request<{ file: CloudFile; upload: UploadSession }>(
    `/v1/uploads/${encodeURIComponent(upload.id)}/complete`,
    { method: "POST", body: JSON.stringify({}), signal },
  );
  onSession(completedUpload.upload);
  onProgress(100);
  return completedUpload.file;
}

export async function renameFile(fileId: string, name: string): Promise<CloudFile> {
  const result = await request<{ file: CloudFile }>(`/v1/files/${encodeURIComponent(fileId)}`, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });
  return result.file;
}

export async function setArchived(fileId: string, archived: boolean): Promise<CloudFile> {
  const result = await request<{ file: CloudFile }>(`/v1/files/${encodeURIComponent(fileId)}/${archived ? "archive" : "restore"}`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  return result.file;
}

export async function purgeFile(fileId: string): Promise<void> {
  await request(`/v1/files/${encodeURIComponent(fileId)}`, { method: "DELETE" });
}

export async function activity(): Promise<ActivityEvent[]> {
  const result = await request<{ activity: ActivityEvent[] }>("/v1/activity");
  return result.activity;
}

export async function downloadFile(file: CloudFile): Promise<void> {
  const grant = await request<DownloadGrant>(`/v1/files/${encodeURIComponent(file.id)}/download`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  const response = await fetch(resolveTransferUrl(grant.url), { method: grant.method, headers: grant.headers });
  if (!response.ok) throw new Error("download_failed");
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = file.name;
  anchor.click();
  URL.revokeObjectURL(url);
}

function resolveTransferUrl(value: string): string {
  if (/^https?:\/\//i.test(value)) return value;
  return `${gatewayBase()}${value.startsWith("/") ? value : `/${value}`}`;
}

function kindForFile(file: File): CloudFile["kind"] {
  if (file.type.startsWith("image/")) return "image";
  if (file.type.startsWith("video/")) return "video";
  if (file.type.startsWith("audio/")) return "audio";
  if (/\.(zip|tar|gz|7z)$/i.test(file.name)) return "archive";
  if (file.type.startsWith("text/") || /\.(pdf|md|json|jsonl|docx?|xlsx?)$/i.test(file.name)) return "document";
  return "other";
}
