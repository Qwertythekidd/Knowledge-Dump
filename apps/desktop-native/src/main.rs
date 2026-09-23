#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod codex_storage;

use std::{env, process};

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

#[tauri::command]
async fn restore_default_codex_collection(
    collection_path: String,
) -> Result<codex_storage::CodexRestoreResult, String> {
    tauri::async_runtime::spawn_blocking(move || {
        codex_storage::restore_default_collection(&collection_path)
    })
    .await
    .map_err(|_| "codex_restore_worker_failed".to_string())?
}

fn main() {
    if let Some(exit_code) = run_codex_storage_cli() {
        process::exit(exit_code);
    }
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
            restore_default_codex_collection,
        ])
        .run(tauri::generate_context!())
        .expect("Knowledge Dump desktop runtime failed");
}

fn run_codex_storage_cli() -> Option<i32> {
    let mut arguments = env::args().skip(1);
    if arguments.next().as_deref() != Some("codex-storage") {
        return None;
    }
    let command = arguments.next().unwrap_or_else(|| "help".to_string());
    let remaining: Vec<String> = arguments.collect();
    let result = match command.as_str() {
        "discover" => cli_discover(&remaining),
        "collect" => cli_collect(&remaining),
        "verify" => cli_verify(&remaining),
        "restore-test" => cli_restore_test(&remaining),
        "restore-default" => cli_restore_default(&remaining),
        "help" | "--help" | "-h" => {
            print_codex_storage_help();
            Ok(())
        }
        _ => Err(format!("unknown_codex_storage_command:{command}")),
    };
    match result {
        Ok(()) => Some(0),
        Err(error) => {
            eprintln!("Knowledge Dump Codex storage failed: {error}");
            Some(1)
        }
    }
}

fn cli_discover(arguments: &[String]) -> Result<(), String> {
    require_no_extra_arguments(arguments)?;
    let defaults = codex_storage::defaults()?;
    let inventory = codex_storage::scan_source(&defaults.source_codex_home)?;
    println!("Codex home: {}", inventory.source_codex_home);
    println!("Knowledge Dump collection: {}", defaults.collection_path);
    println!(
        "Sessions: {} active, {} archived",
        inventory.active_session_count, inventory.archived_session_count
    );
    println!(
        "Portable data: {} files, {} bytes",
        inventory.file_count, inventory.total_bytes
    );
    print_workspace_roots(&inventory.workspace_roots);
    Ok(())
}

fn cli_collect(arguments: &[String]) -> Result<(), String> {
    if arguments.len() > 1 {
        return Err("codex_storage_collect_accepts_one_destination".to_string());
    }
    let defaults = codex_storage::defaults()?;
    let collection_path = arguments.first().unwrap_or(&defaults.collection_path);
    let inventory = codex_storage::scan_source(&defaults.source_codex_home)?;
    println!("Collecting from: {}", inventory.source_codex_home);
    println!("Collection path: {collection_path}");
    println!(
        "Portable data: {} files, {} bytes",
        inventory.file_count, inventory.total_bytes
    );
    let result = codex_storage::sync_collection(&inventory.source_codex_home, collection_path)?;
    let verification = codex_storage::verify_collection(collection_path)?;
    codex_storage::save_preferences(
        &inventory.source_codex_home,
        collection_path,
        &defaults.restore_path,
    )?;
    println!(
        "Updated: {} added, {} changed, {} removed, {} unchanged",
        result.added_files, result.updated_files, result.removed_files, result.unchanged_files
    );
    println!(
        "Verified collection {}: {} files, {} bytes",
        verification.collection_id, verification.file_count, verification.total_bytes
    );
    print_workspace_roots(&result.collection.workspace_roots);
    Ok(())
}

fn cli_verify(arguments: &[String]) -> Result<(), String> {
    if arguments.len() > 1 {
        return Err("codex_storage_verify_accepts_one_collection".to_string());
    }
    let defaults = codex_storage::defaults()?;
    let collection_path = arguments.first().unwrap_or(&defaults.collection_path);
    let verification = codex_storage::verify_collection(collection_path)?;
    println!(
        "Verified collection {}: {} files, {} bytes",
        verification.collection_id, verification.file_count, verification.total_bytes
    );
    Ok(())
}

fn cli_restore_test(arguments: &[String]) -> Result<(), String> {
    if arguments.len() > 1 {
        return Err("codex_storage_restore_accepts_one_destination".to_string());
    }
    let defaults = codex_storage::defaults()?;
    let destination_path = arguments.first().unwrap_or(&defaults.restore_path);
    let restored = codex_storage::restore_collection(&defaults.collection_path, destination_path)?;
    codex_storage::save_preferences(
        &defaults.source_codex_home,
        &defaults.collection_path,
        destination_path,
    )?;
    println!(
        "Prepared isolated restore: {} files, {} bytes",
        restored.file_count, restored.total_bytes
    );
    println!("{}", restored.login_command);
    println!("{}", restored.resume_command);
    Ok(())
}

fn cli_restore_default(arguments: &[String]) -> Result<(), String> {
    if arguments.len() > 1 {
        return Err("codex_storage_restore_default_accepts_one_collection".to_string());
    }
    let defaults = codex_storage::defaults()?;
    let collection_path = arguments.first().unwrap_or(&defaults.collection_path);
    let restored = codex_storage::restore_default_collection(collection_path)?;
    println!(
        "Installed verified Codex context: {} files, {} bytes",
        restored.file_count, restored.total_bytes
    );
    println!("Destination: {}", restored.destination_codex_home);
    println!("Authentication state was not restored. Sign in before resuming tasks.");
    println!("{}", restored.login_command);
    println!("{}", restored.resume_command);
    Ok(())
}

fn require_no_extra_arguments(arguments: &[String]) -> Result<(), String> {
    if arguments.is_empty() {
        Ok(())
    } else {
        Err("codex_storage_command_accepts_no_arguments".to_string())
    }
}

fn print_workspace_roots(workspace_roots: &[String]) {
    println!("Referenced workspaces: {}", workspace_roots.len());
    for workspace_root in workspace_roots {
        println!("  {workspace_root}");
    }
}

fn print_codex_storage_help() {
    println!("Knowledge Dump Codex structured storage");
    println!();
    println!("Usage:");
    println!("  knowledge-dump codex-storage discover");
    println!("  knowledge-dump codex-storage collect [COLLECTION_PATH]");
    println!("  knowledge-dump codex-storage verify [COLLECTION_PATH]");
    println!("  knowledge-dump codex-storage restore-test [DESTINATION_CODEX_HOME]");
    println!("  knowledge-dump codex-storage restore-default [COLLECTION_PATH]");
    println!();
    println!(
        "Collect uses the current CODEX_HOME or ~/.codex and remembers the selected collection."
    );
    println!(
        "Restore-default is for a fresh workstation and refuses to replace an existing Codex home."
    );
    println!("Workspace paths are recorded, but Git repositories are not copied implicitly.");
}
