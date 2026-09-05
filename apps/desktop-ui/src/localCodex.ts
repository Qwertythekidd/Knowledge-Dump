import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import type {
  CodexCollectionSummary,
  CodexRestoreResult,
  CodexSourceInventory,
  CodexStorageDefaults,
  CodexSyncResult,
  CodexVerificationResult,
} from "@knowledge-dump/protocol";

export function localCodexAvailable(): boolean {
  return "__TAURI_INTERNALS__" in window;
}

function requireNative(): void {
  if (!localCodexAvailable()) throw new Error("native_desktop_required");
}

export async function codexStorageDefaults(): Promise<CodexStorageDefaults> {
  requireNative();
  return invoke<CodexStorageDefaults>("codex_storage_defaults");
}

export async function chooseLocalDirectory(defaultPath: string): Promise<string | null> {
  requireNative();
  const selected = await open({
    defaultPath,
    directory: true,
    multiple: false,
    title: "Choose a Knowledge Dump folder",
  });
  return typeof selected === "string" ? selected : null;
}

export async function saveCodexStoragePreferences(
  sourcePath: string,
  collectionPath: string,
  restorePath: string,
): Promise<CodexStorageDefaults> {
  requireNative();
  return invoke<CodexStorageDefaults>("save_codex_storage_preferences", {
    sourcePath,
    collectionPath,
    restorePath,
  });
}

export async function scanCodexSource(sourcePath: string): Promise<CodexSourceInventory> {
  requireNative();
  return invoke<CodexSourceInventory>("scan_codex_source", { sourcePath });
}

export async function syncCodexCollection(sourcePath: string, collectionPath: string): Promise<CodexSyncResult> {
  requireNative();
  return invoke<CodexSyncResult>("sync_codex_collection", { sourcePath, collectionPath });
}

export async function inspectCodexCollection(collectionPath: string): Promise<CodexCollectionSummary> {
  requireNative();
  return invoke<CodexCollectionSummary>("inspect_codex_collection", { collectionPath });
}

export async function verifyCodexCollection(collectionPath: string): Promise<CodexVerificationResult> {
  requireNative();
  return invoke<CodexVerificationResult>("verify_codex_collection", { collectionPath });
}

export async function restoreCodexCollection(
  collectionPath: string,
  destinationPath: string,
): Promise<CodexRestoreResult> {
  requireNative();
  return invoke<CodexRestoreResult>("restore_codex_collection", { collectionPath, destinationPath });
}
