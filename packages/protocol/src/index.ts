export type FileKind = "folder" | "document" | "image" | "video" | "audio" | "archive" | "other";
export type FileStatus = "active" | "archived";

export interface Account {
  id: string;
  email: string;
  displayName: string;
  plan: string;
  status: string;
  createdAt: string;
}

export interface Device {
  id: string;
  label: string;
  platform: string;
  status: "active" | "revoked";
  createdAt: string;
  lastSeenAt: string;
  revokedAt: string | null;
}

export interface SessionResponse {
  account: Account;
  device: Device;
  accessToken: string;
  refreshToken: string;
  expiresAt: string;
  refreshExpiresAt: string;
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
  usedObjects: number;
  quotaObjects: number;
  database: "sqlite" | "postgresql";
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
  targetType: string;
  targetId: string | null;
  actorDeviceId: string | null;
  metadata: Record<string, unknown>;
  createdAt: string;
}

export interface FileVersion {
  id: string;
  fileId: string;
  version: number;
  sizeBytes: number;
  objectKey: string | null;
  metadata: Record<string, unknown>;
  createdAt: string;
}

export type UploadStatus = "initiated" | "uploading" | "completing" | "completed" | "aborted" | "expired";

export interface CompletedUploadPart {
  partNumber: number;
  sizeBytes: number;
  etag: string;
  uploadedAt: string;
}

export interface UploadSession {
  id: string;
  name: string;
  parentId: string | null;
  kind: FileKind;
  mimeType: string | null;
  sizeBytes: number;
  partSize: number;
  totalParts: number;
  status: UploadStatus;
  expiresAt: string;
  createdAt: string;
  updatedAt: string;
  completedAt: string | null;
  fileId: string | null;
  error: string | null;
  completedParts: CompletedUploadPart[];
}

export interface UploadPartGrant {
  partNumber: number;
  url: string;
  method: "PUT";
  headers: Record<string, string>;
  expiresAt: string;
}

export interface DownloadGrant {
  url: string;
  method: "GET";
  headers: Record<string, string>;
  expiresAt: string;
}

export interface ApiError {
  error: string;
  detail?: string;
}

export interface CodexStorageDefaults {
  sourceCodexHome: string;
  defaultCodexHome: string;
  collectionPath: string;
  restorePath: string;
}

export interface CodexSourceInventory {
  sourceCodexHome: string;
  activeSessionCount: number;
  archivedSessionCount: number;
  fileCount: number;
  totalBytes: number;
  workspaceRoots: string[];
  includedCategories: string[];
  excludedCategories: string[];
}

export interface CodexCollectionSummary {
  format: string;
  collectionId: string;
  collectionPath: string;
  sourceCodexHome: string;
  createdAt: string;
  updatedAt: string;
  activeSessionCount: number;
  archivedSessionCount: number;
  fileCount: number;
  totalBytes: number;
  workspaceRoots: string[];
}

export interface CodexSyncResult {
  collection: CodexCollectionSummary;
  addedFiles: number;
  updatedFiles: number;
  removedFiles: number;
  unchangedFiles: number;
}

export interface CodexVerificationResult {
  verified: boolean;
  collectionId: string;
  checkedAt: string;
  fileCount: number;
  totalBytes: number;
}

export interface CodexRestoreResult {
  restored: boolean;
  collectionId: string;
  destinationCodexHome: string;
  fileCount: number;
  totalBytes: number;
  loginCommand: string;
  resumeCommand: string;
}
