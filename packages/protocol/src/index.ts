export type FileKind = "folder" | "document" | "image" | "video" | "audio" | "archive" | "other";
export type FileStatus = "active" | "archived";

export interface Account {
  id: string;
  email: string;
  displayName: string;
  plan: string;
}

export interface SessionResponse {
  account: Account;
  accessToken: string;
  expiresAt: string;
}

export interface StorageHealth {
  gateway: "healthy" | "degraded" | "unavailable";
  authenticated: boolean;
  provider: "mock" | "digitalocean_spaces" | "s3_compatible";
  providerReachable: boolean;
  readAccess: boolean;
  writeAccess: boolean;
  latencyMs: number;
  checkedAt: string;
  usedBytes: number;
  quotaBytes: number;
}

export interface CloudFile {
  id: string;
  parentId: string | null;
  name: string;
  kind: FileKind;
  mimeType: string | null;
  sizeBytes: number;
  status: FileStatus;
  version: number;
  createdAt: string;
  updatedAt: string;
}

export interface ActivityEvent {
  id: string;
  action: string;
  targetName: string;
  createdAt: string;
}

export interface ApiError {
  error: string;
  detail?: string;
}
