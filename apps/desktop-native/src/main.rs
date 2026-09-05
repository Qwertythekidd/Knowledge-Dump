#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod codex_storage;

#[tauri::command]
fn codex_storage_defaults() -> Result<codex_storage::CodexStorageDefaults, String> {
    codex_storage::defaults()
}

#[tauri::command]
fn save_codex_storage_preferences(
    source_path: String,
    collection_path: String,
    restore_path: String,
) -> Result<codex_storage::CodexStorageDefaults, String> {
    codex_storage::save_preferences(&source_path, &collection_path, &restore_path)
}

#[tauri::command]
async fn scan_codex_source(
    source_path: String,
) -> Result<codex_storage::CodexSourceInventory, String> {
    tauri::async_runtime::spawn_blocking(move || codex_storage::scan_source(&source_path))
        .await
        .map_err(|_| "codex_scan_worker_failed".to_string())?
}

#[tauri::command]
async fn sync_codex_collection(
    source_path: String,
    collection_path: String,
) -> Result<codex_storage::CodexSyncResult, String> {
    tauri::async_runtime::spawn_blocking(move || {
        codex_storage::sync_collection(&source_path, &collection_path)
    })
    .await
    .map_err(|_| "codex_sync_worker_failed".to_string())?
}

#[tauri::command]
async fn inspect_codex_collection(
    collection_path: String,
) -> Result<codex_storage::CodexCollectionSummary, String> {
    tauri::async_runtime::spawn_blocking(move || {
        codex_storage::inspect_collection(&collection_path)
    })
    .await
    .map_err(|_| "codex_inspect_worker_failed".to_string())?
}

#[tauri::command]
async fn verify_codex_collection(
    collection_path: String,
) -> Result<codex_storage::CodexVerificationResult, String> {
    tauri::async_runtime::spawn_blocking(move || codex_storage::verify_collection(&collection_path))
        .await
        .map_err(|_| "codex_verify_worker_failed".to_string())?
}

#[tauri::command]
async fn restore_codex_collection(
    collection_path: String,
    destination_path: String,
) -> Result<codex_storage::CodexRestoreResult, String> {
    tauri::async_runtime::spawn_blocking(move || {
        codex_storage::restore_collection(&collection_path, &destination_path)
    })
    .await
    .map_err(|_| "codex_restore_worker_failed".to_string())?
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            codex_storage_defaults,
            save_codex_storage_preferences,
            scan_codex_source,
            sync_codex_collection,
            inspect_codex_collection,
            verify_codex_collection,
            restore_codex_collection,
        ])
        .run(tauri::generate_context!())
        .expect("Knowledge Dump desktop runtime failed");
}
