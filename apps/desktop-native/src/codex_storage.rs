use chrono::{SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeSet, HashMap, HashSet};
use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::{BufReader, BufWriter, Read, Seek, SeekFrom, Write};
use std::path::{Component, Path, PathBuf};
use std::time::UNIX_EPOCH;
use uuid::Uuid;
use walkdir::WalkDir;

const SNAPSHOT_FORMAT: &str = "knowledge-dump.codex-workspace-snapshot.v1";
const PREFERENCES_FORMAT: &str = "knowledge-dump.codex-storage-preferences.v1";
const MANIFEST_NAME: &str = "manifest.json";
const PREFERENCES_NAME: &str = "codex-storage.json";
const CODEX_HOME_DIRECTORY: &str = "codex-home";
const COPY_BUFFER_BYTES: usize = 1024 * 1024;
const COPY_STABILITY_ATTEMPTS: usize = 3;
const SESSION_METADATA_READ_LIMIT: u64 = 1024 * 1024;
const INCLUDED_DIRECTORIES: &[&str] = &[
    "sessions",
    "archived_sessions",
    "attachments",
    "generated_images",
    "visualizations",
    "memories",
    "rules",
    "skills",
];
const INCLUDED_FILES: &[&str] = &[
    "session_index.jsonl",
    "AGENTS.md",
    "AGENTS.override.md",
    "version.json",
];

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CodexStorageDefaults {
    pub source_codex_home: String,
    pub default_codex_home: String,
    pub collection_path: String,
    pub restore_path: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CodexSourceInventory {
    pub source_codex_home: String,
    pub active_session_count: u64,
    pub archived_session_count: u64,
    pub file_count: u64,
    pub total_bytes: u64,
    pub workspace_roots: Vec<String>,
    pub included_categories: Vec<String>,
    pub excluded_categories: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CodexCollectionSummary {
    pub format: String,
    pub collection_id: String,
    pub collection_path: String,
    pub source_codex_home: String,
    pub created_at: String,
    pub updated_at: String,
    pub active_session_count: u64,
    pub archived_session_count: u64,
    pub file_count: u64,
    pub total_bytes: u64,
    pub workspace_roots: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CodexSyncResult {
    pub collection: CodexCollectionSummary,
    pub added_files: u64,
    pub updated_files: u64,
    pub removed_files: u64,
    pub unchanged_files: u64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CodexVerificationResult {
    pub verified: bool,
    pub collection_id: String,
    pub checked_at: String,
    pub file_count: u64,
    pub total_bytes: u64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CodexRestoreResult {
    pub restored: bool,
    pub collection_id: String,
    pub destination_codex_home: String,
    pub file_count: u64,
    pub total_bytes: u64,
    pub login_command: String,
    pub resume_command: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SnapshotManifest {
    format: String,
    collection_id: String,
    created_at: String,
    updated_at: String,
    source_codex_home: String,
    source_version: Option<String>,
    active_session_count: u64,
    archived_session_count: u64,
    file_count: u64,
    total_bytes: u64,
    #[serde(default)]
    workspace_roots: Vec<String>,
    included_categories: Vec<String>,
    excluded_categories: Vec<String>,
    files: Vec<SnapshotFile>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SnapshotFile {
    path: String,
    size_bytes: u64,
    sha256: String,
    source_modified_ns: u64,
    snapshot_modified_ns: u64,
}

#[derive(Debug, Clone)]
struct SourceFile {
    source: PathBuf,
    relative: PathBuf,
    size_bytes: u64,
    modified_ns: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct CodexStoragePreferences {
    format: String,
    source_codex_home: String,
    collection_path: String,
    restore_path: String,
}

pub fn defaults() -> Result<CodexStorageDefaults, String> {
    let home = home_directory()?;
    let source = active_codex_home()?;
    let default_codex_home = display_path(&source);
    let data_home = env::var_os("XDG_DATA_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| home.join(".local/share"));
    let defaults = CodexStorageDefaults {
        source_codex_home: display_path(&source),
        default_codex_home: default_codex_home.clone(),
        collection_path: display_path(
            &data_home.join("knowledge-dump/local-collections/codex-workspace"),
        ),
        restore_path: display_path(&home.join(".codex-knowledge-dump-restore")),
    };
    let Some(preferences) = read_preferences()? else {
        return Ok(defaults);
    };
    Ok(CodexStorageDefaults {
        source_codex_home: preferences.source_codex_home,
        default_codex_home,
        collection_path: preferences.collection_path,
        restore_path: preferences.restore_path,
    })
}

pub fn save_preferences(
    source_path: &str,
    collection_path: &str,
    restore_path: &str,
) -> Result<CodexStorageDefaults, String> {
    let preferences = CodexStoragePreferences {
        format: PREFERENCES_FORMAT.to_string(),
        source_codex_home: display_path(&resolve_user_path(source_path)?),
        collection_path: display_path(&resolve_user_path(collection_path)?),
        restore_path: display_path(&resolve_user_path(restore_path)?),
    };
    let path = preferences_path()?;
    let parent = path
        .parent()
        .ok_or_else(|| "codex_storage_preferences_path_invalid".to_string())?;
    fs::create_dir_all(parent).map_err(|_| "codex_storage_preferences_write_failed".to_string())?;
    set_private_directory(parent)?;
    write_json_atomically(&path, &preferences, "codex_storage_preferences")?;
    Ok(CodexStorageDefaults {
        source_codex_home: preferences.source_codex_home,
        default_codex_home: display_path(&active_codex_home()?),
        collection_path: preferences.collection_path,
        restore_path: preferences.restore_path,
    })
}

pub fn scan_source(source_path: &str) -> Result<CodexSourceInventory, String> {
    let source_root = require_source_root(source_path)?;
    let files = collect_source_files(&source_root)?;
    let (active_session_count, archived_session_count) = session_counts(&files);
    let workspace_roots = discover_workspace_roots(&files);
    Ok(CodexSourceInventory {
        source_codex_home: display_path(&source_root),
        active_session_count,
        archived_session_count,
        file_count: files.len() as u64,
        total_bytes: files.iter().map(|item| item.size_bytes).sum(),
        workspace_roots,
        included_categories: included_categories(),
        excluded_categories: excluded_categories(),
    })
}

pub fn sync_collection(
    source_path: &str,
    collection_path: &str,
) -> Result<CodexSyncResult, String> {
    let source_root = require_source_root(source_path)?;
    let collection_root = prepare_collection_root(collection_path, &source_root)?;
    let codex_home = collection_root.join(CODEX_HOME_DIRECTORY);
    fs::create_dir_all(&codex_home).map_err(|_| "codex_collection_create_failed".to_string())?;
    set_private_directory(&collection_root)?;
    set_private_directory(&codex_home)?;

    let existing = read_manifest_optional(&collection_root)?;
    let existing_files: HashMap<String, SnapshotFile> = existing
        .as_ref()
        .map(|manifest| {
            manifest
                .files
                .iter()
                .cloned()
                .map(|item| (item.path.clone(), item))
                .collect()
        })
        .unwrap_or_default();
    let sources = collect_source_files(&source_root)?;
    let (active_session_count, archived_session_count) = session_counts(&sources);
    let workspace_roots = discover_workspace_roots(&sources);
    let mut records = Vec::with_capacity(sources.len());
    let mut added_files = 0_u64;
    let mut updated_files = 0_u64;
    let mut unchanged_files = 0_u64;

    for source in sources {
        let source = source_file(&source_root, &source.source)?;
        let relative = normalized_relative(&source.relative)?;
        let destination = safe_join(&codex_home, &relative)?;
        let previous = existing_files.get(&relative);
        if let Some(record) = previous {
            if source.size_bytes == record.size_bytes
                && source.modified_ns == record.source_modified_ns
                && target_matches_record(&destination, record)
            {
                records.push(record.clone());
                unchanged_files += 1;
                continue;
            }
        }

        let record = copy_source_file(&source, &destination, &relative)?;
        if previous.is_some() {
            updated_files += 1;
        } else {
            added_files += 1;
        }
        records.push(record);
    }

    records.sort_by(|left, right| left.path.cmp(&right.path));
    let current_paths: HashSet<&str> = records.iter().map(|record| record.path.as_str()).collect();
    let mut removed_files = 0_u64;
    for previous in existing_files.values() {
        if current_paths.contains(previous.path.as_str()) {
            continue;
        }
        let obsolete = safe_join(&codex_home, &previous.path)?;
        match fs::symlink_metadata(&obsolete) {
            Ok(metadata) if metadata.file_type().is_file() || metadata.file_type().is_symlink() => {
                fs::remove_file(&obsolete)
                    .map_err(|_| "codex_collection_obsolete_file_remove_failed".to_string())?;
            }
            Ok(_) => return Err("codex_collection_obsolete_path_invalid".to_string()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(_) => return Err("codex_collection_obsolete_file_remove_failed".to_string()),
        }
        removed_files += 1;
    }
    let now = utc_now();
    let manifest = SnapshotManifest {
        format: SNAPSHOT_FORMAT.to_string(),
        collection_id: existing
            .as_ref()
            .map(|item| item.collection_id.clone())
            .unwrap_or_else(|| Uuid::new_v4().to_string()),
        created_at: existing
            .as_ref()
            .map(|item| item.created_at.clone())
            .unwrap_or_else(|| now.clone()),
        updated_at: now,
        source_codex_home: display_path(&source_root),
        source_version: read_codex_version(&source_root),
        active_session_count,
        archived_session_count,
        file_count: records.len() as u64,
        total_bytes: records.iter().map(|item| item.size_bytes).sum(),
        workspace_roots,
        included_categories: included_categories(),
        excluded_categories: excluded_categories(),
        files: records,
    };

    if existing.is_some() {
        preserve_previous_manifest(&collection_root)?;
    }
    write_manifest(&collection_root, &manifest)?;
    Ok(CodexSyncResult {
        collection: collection_summary(&collection_root, &manifest),
        added_files,
        updated_files,
        removed_files,
        unchanged_files,
    })
}

pub fn inspect_collection(collection_path: &str) -> Result<CodexCollectionSummary, String> {
    let root = require_collection_root(collection_path)?;
    let manifest = read_manifest(&root)?;
    Ok(collection_summary(&root, &manifest))
}

pub fn verify_collection(collection_path: &str) -> Result<CodexVerificationResult, String> {
    let root = require_collection_root(collection_path)?;
    let manifest = read_manifest(&root)?;
    let codex_home = root.join(CODEX_HOME_DIRECTORY);
    let mut total_bytes = 0_u64;
    for record in &manifest.files {
        let path = safe_join(&codex_home, &record.path)?;
        let metadata = fs::symlink_metadata(&path)
            .map_err(|_| format!("codex_collection_file_missing:{}", record.path))?;
        if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
            return Err(format!("codex_collection_file_invalid:{}", record.path));
        }
        if metadata.len() != record.size_bytes || hash_file(&path)? != record.sha256 {
            return Err(format!(
                "codex_collection_checksum_mismatch:{}",
                record.path
            ));
        }
        total_bytes += metadata.len();
    }
    if total_bytes != manifest.total_bytes || manifest.file_count != manifest.files.len() as u64 {
        return Err("codex_collection_manifest_totals_invalid".to_string());
    }
    Ok(CodexVerificationResult {
        verified: true,
        collection_id: manifest.collection_id,
        checked_at: utc_now(),
        file_count: manifest.file_count,
        total_bytes,
    })
}

pub fn restore_collection(
    collection_path: &str,
    destination_path: &str,
) -> Result<CodexRestoreResult, String> {
    restore_collection_with_policy(collection_path, destination_path, true)
}

pub fn restore_default_collection(collection_path: &str) -> Result<CodexRestoreResult, String> {
    let destination = active_codex_home()?;
    if fs::symlink_metadata(&destination).is_ok() {
        return Err("codex_default_home_exists".to_string());
    }
    restore_collection_with_policy(collection_path, &display_path(&destination), false)
}

fn restore_collection_with_policy(
    collection_path: &str,
    destination_path: &str,
    protect_active_home: bool,
) -> Result<CodexRestoreResult, String> {
    let collection_root = require_collection_root(collection_path)?;
    let manifest = read_manifest(&collection_root)?;
    let source_codex_home = collection_root.join(CODEX_HOME_DIRECTORY);
    let requested_destination = resolve_user_path(destination_path)?;
    if fs::symlink_metadata(&requested_destination).is_ok() {
        return Err("codex_restore_destination_exists".to_string());
    }
    let destination_name = requested_destination
        .file_name()
        .ok_or_else(|| "codex_restore_destination_invalid".to_string())?;
    let requested_parent = requested_destination
        .parent()
        .ok_or_else(|| "codex_restore_destination_invalid".to_string())?;
    fs::create_dir_all(requested_parent)
        .map_err(|_| "codex_restore_parent_create_failed".to_string())?;
    let parent = requested_parent
        .canonicalize()
        .map_err(|_| "codex_restore_parent_create_failed".to_string())?;
    let destination = parent.join(destination_name);
    if protect_active_home {
        let active_codex_home = active_codex_home()?;
        if destination == active_codex_home
            || destination.starts_with(&active_codex_home)
            || active_codex_home.starts_with(&destination)
        {
            return Err("codex_restore_active_home_forbidden".to_string());
        }
    }
    if destination.starts_with(&collection_root) || collection_root.starts_with(&destination) {
        return Err("codex_restore_destination_overlaps_collection".to_string());
    }

    let temporary = parent.join(format!(
        ".{}.knowledge-dump-partial-{}",
        destination
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or("codex-restore"),
        Uuid::new_v4()
    ));
    fs::create_dir(&temporary).map_err(|_| "codex_restore_create_failed".to_string())?;
    set_private_directory(&temporary)?;

    let restored = (|| -> Result<(u64, u64), String> {
        let mut count = 0_u64;
        let mut bytes = 0_u64;
        for record in &manifest.files {
            let source = safe_join(&source_codex_home, &record.path)?;
            let target = safe_join(&temporary, &record.path)?;
            let copied = copy_snapshot_file(&source, &target, record)?;
            count += 1;
            bytes += copied;
        }
        Ok((count, bytes))
    })();

    let (file_count, total_bytes) = match restored {
        Ok(value) => value,
        Err(error) => {
            let _ = fs::remove_dir_all(&temporary);
            return Err(error);
        }
    };
    fs::rename(&temporary, &destination).map_err(|_| {
        let _ = fs::remove_dir_all(&temporary);
        "codex_restore_finalize_failed".to_string()
    })?;

    let quoted_destination = shell_quote(&display_path(&destination));
    Ok(CodexRestoreResult {
        restored: true,
        collection_id: manifest.collection_id,
        destination_codex_home: display_path(&destination),
        file_count,
        total_bytes,
        login_command: format!("CODEX_HOME={} codex login", quoted_destination),
        resume_command: format!("CODEX_HOME={} codex resume", quoted_destination),
    })
}

fn collect_source_files(source_root: &Path) -> Result<Vec<SourceFile>, String> {
    let mut files = Vec::new();
    for directory in INCLUDED_DIRECTORIES {
        let root = source_root.join(directory);
        if !root.is_dir() {
            continue;
        }
        for entry in WalkDir::new(&root).follow_links(false) {
            let entry = entry.map_err(|_| format!("codex_source_walk_failed:{directory}"))?;
            if !entry.file_type().is_file() || entry.file_type().is_symlink() {
                continue;
            }
            files.push(source_file(source_root, entry.path())?);
        }
    }
    for name in INCLUDED_FILES {
        let path = source_root.join(name);
        if path.is_file() && !path.is_symlink() {
            files.push(source_file(source_root, &path)?);
        }
    }
    files.sort_by(|left, right| left.relative.cmp(&right.relative));
    Ok(files)
}

fn source_file(source_root: &Path, path: &Path) -> Result<SourceFile, String> {
    let metadata =
        fs::symlink_metadata(path).map_err(|_| "codex_source_metadata_failed".to_string())?;
    if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
        return Err("codex_source_file_invalid".to_string());
    }
    let relative = path
        .strip_prefix(source_root)
        .map_err(|_| "codex_source_path_invalid".to_string())?
        .to_path_buf();
    Ok(SourceFile {
        source: path.to_path_buf(),
        relative,
        size_bytes: metadata.len(),
        modified_ns: modified_ns(&metadata)?,
    })
}

fn copy_source_file(
    source: &SourceFile,
    destination: &Path,
    relative: &str,
) -> Result<SnapshotFile, String> {
    let parent = destination
        .parent()
        .ok_or_else(|| "codex_collection_destination_invalid".to_string())?;
    fs::create_dir_all(parent)
        .map_err(|_| "codex_collection_directory_create_failed".to_string())?;
    set_private_directory(parent)?;
    for _ in 0..COPY_STABILITY_ATTEMPTS {
        let before = fs::symlink_metadata(&source.source)
            .map_err(|_| "codex_source_changed_during_sync".to_string())?;
        if !before.file_type().is_file() || before.file_type().is_symlink() {
            return Err(format!("codex_source_changed_during_sync:{relative}"));
        }
        let temporary = parent.join(format!(".knowledge-dump-copy-{}", Uuid::new_v4()));
        let copied = copy_and_hash(&source.source, &temporary)?;
        let after = fs::symlink_metadata(&source.source)
            .map_err(|_| "codex_source_changed_during_sync".to_string())?;
        let before_modified_ns = modified_ns(&before)?;
        let stable_copy = after.len() == before.len() && modified_ns(&after)? == before_modified_ns;
        let stable_append_prefix = is_session_jsonl(relative)
            && after.len() >= copied.0
            && file_ends_with_newline(&temporary)?
            && hash_file_prefix(&source.source, copied.0)? == copied.1;
        if !stable_copy && !stable_append_prefix {
            let _ = fs::remove_file(&temporary);
            continue;
        }
        fs::set_permissions(&temporary, private_file_permissions())
            .map_err(|_| "codex_collection_permissions_failed".to_string())?;
        fs::rename(&temporary, destination).map_err(|_| {
            let _ = fs::remove_file(&temporary);
            "codex_collection_file_finalize_failed".to_string()
        })?;
        let snapshot_modified_ns = modified_ns(
            &fs::symlink_metadata(destination)
                .map_err(|_| "codex_collection_metadata_failed".to_string())?,
        )?;
        return Ok(SnapshotFile {
            path: relative.to_string(),
            size_bytes: copied.0,
            sha256: copied.1,
            source_modified_ns: before_modified_ns,
            snapshot_modified_ns,
        });
    }
    Err(format!("codex_source_changed_during_sync:{relative}"))
}

fn copy_snapshot_file(
    source: &Path,
    destination: &Path,
    record: &SnapshotFile,
) -> Result<u64, String> {
    let parent = destination
        .parent()
        .ok_or_else(|| "codex_restore_destination_invalid".to_string())?;
    fs::create_dir_all(parent).map_err(|_| "codex_restore_directory_create_failed".to_string())?;
    set_private_directory(parent)?;
    let (size, digest) = copy_and_hash(source, destination)?;
    if size != record.size_bytes || digest != record.sha256 {
        let _ = fs::remove_file(destination);
        return Err(format!(
            "codex_collection_checksum_mismatch:{}",
            record.path
        ));
    }
    fs::set_permissions(destination, private_file_permissions())
        .map_err(|_| "codex_restore_permissions_failed".to_string())?;
    Ok(size)
}

fn copy_and_hash(source: &Path, destination: &Path) -> Result<(u64, String), String> {
    let input = File::open(source).map_err(|_| "codex_file_read_failed".to_string())?;
    let output = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(destination)
        .map_err(|_| "codex_file_write_failed".to_string())?;
    let mut reader = BufReader::with_capacity(COPY_BUFFER_BYTES, input);
    let mut writer = BufWriter::with_capacity(COPY_BUFFER_BYTES, output);
    let mut digest = Sha256::new();
    let mut size = 0_u64;
    let mut buffer = vec![0_u8; COPY_BUFFER_BYTES];
    loop {
        let read = reader
            .read(&mut buffer)
            .map_err(|_| "codex_file_read_failed".to_string())?;
        if read == 0 {
            break;
        }
        writer
            .write_all(&buffer[..read])
            .map_err(|_| "codex_file_write_failed".to_string())?;
        digest.update(&buffer[..read]);
        size += read as u64;
    }
    writer
        .flush()
        .map_err(|_| "codex_file_write_failed".to_string())?;
    writer
        .get_ref()
        .sync_all()
        .map_err(|_| "codex_file_sync_failed".to_string())?;
    Ok((size, format!("{:x}", digest.finalize())))
}

fn hash_file(path: &Path) -> Result<String, String> {
    let mut source = BufReader::with_capacity(
        COPY_BUFFER_BYTES,
        File::open(path).map_err(|_| "codex_collection_file_read_failed".to_string())?,
    );
    let mut digest = Sha256::new();
    let mut buffer = vec![0_u8; COPY_BUFFER_BYTES];
    loop {
        let read = source
            .read(&mut buffer)
            .map_err(|_| "codex_collection_file_read_failed".to_string())?;
        if read == 0 {
            break;
        }
        digest.update(&buffer[..read]);
    }
    Ok(format!("{:x}", digest.finalize()))
}

fn hash_file_prefix(path: &Path, size: u64) -> Result<String, String> {
    let source = File::open(path).map_err(|_| "codex_file_read_failed".to_string())?;
    let mut reader = BufReader::with_capacity(COPY_BUFFER_BYTES, source).take(size);
    let mut digest = Sha256::new();
    let mut copied = 0_u64;
    let mut buffer = vec![0_u8; COPY_BUFFER_BYTES];
    loop {
        let read = reader
            .read(&mut buffer)
            .map_err(|_| "codex_file_read_failed".to_string())?;
        if read == 0 {
            break;
        }
        digest.update(&buffer[..read]);
        copied += read as u64;
    }
    if copied != size {
        return Err("codex_source_changed_during_sync".to_string());
    }
    Ok(format!("{:x}", digest.finalize()))
}

fn file_ends_with_newline(path: &Path) -> Result<bool, String> {
    let mut file = File::open(path).map_err(|_| "codex_file_read_failed".to_string())?;
    if file
        .metadata()
        .map_err(|_| "codex_file_read_failed".to_string())?
        .len()
        == 0
    {
        return Ok(true);
    }
    file.seek(SeekFrom::End(-1))
        .map_err(|_| "codex_file_read_failed".to_string())?;
    let mut last = [0_u8; 1];
    file.read_exact(&mut last)
        .map_err(|_| "codex_file_read_failed".to_string())?;
    Ok(last[0] == b'\n')
}

fn is_session_jsonl(relative: &str) -> bool {
    (relative.starts_with("sessions/") || relative.starts_with("archived_sessions/"))
        && relative.ends_with(".jsonl")
}

fn target_matches_record(path: &Path, record: &SnapshotFile) -> bool {
    let Ok(metadata) = fs::symlink_metadata(path) else {
        return false;
    };
    metadata.file_type().is_file()
        && !metadata.file_type().is_symlink()
        && metadata.len() == record.size_bytes
        && modified_ns(&metadata).ok() == Some(record.snapshot_modified_ns)
}

fn read_manifest_optional(root: &Path) -> Result<Option<SnapshotManifest>, String> {
    let path = root.join(MANIFEST_NAME);
    if !path.exists() {
        return Ok(None);
    }
    read_manifest(root).map(Some)
}

fn read_preferences() -> Result<Option<CodexStoragePreferences>, String> {
    let path = preferences_path()?;
    if !path.exists() {
        return Ok(None);
    }
    let source =
        File::open(path).map_err(|_| "codex_storage_preferences_read_failed".to_string())?;
    let preferences: CodexStoragePreferences = serde_json::from_reader(BufReader::new(source))
        .map_err(|_| "codex_storage_preferences_invalid".to_string())?;
    if preferences.format != PREFERENCES_FORMAT {
        return Err("codex_storage_preferences_invalid".to_string());
    }
    resolve_user_path(&preferences.source_codex_home)?;
    resolve_user_path(&preferences.collection_path)?;
    resolve_user_path(&preferences.restore_path)?;
    Ok(Some(preferences))
}

fn read_manifest(root: &Path) -> Result<SnapshotManifest, String> {
    let path = root.join(MANIFEST_NAME);
    let source = File::open(&path).map_err(|_| "codex_collection_manifest_missing".to_string())?;
    let manifest: SnapshotManifest = serde_json::from_reader(BufReader::new(source))
        .map_err(|_| "codex_collection_manifest_invalid".to_string())?;
    if manifest.format != SNAPSHOT_FORMAT || Uuid::parse_str(&manifest.collection_id).is_err() {
        return Err("codex_collection_manifest_invalid".to_string());
    }
    for record in &manifest.files {
        validate_relative(&record.path)?;
        if record.sha256.len() != 64
            || !record.sha256.bytes().all(|value| value.is_ascii_hexdigit())
        {
            return Err("codex_collection_manifest_invalid".to_string());
        }
    }
    Ok(manifest)
}

fn write_manifest(root: &Path, manifest: &SnapshotManifest) -> Result<(), String> {
    let destination = root.join(MANIFEST_NAME);
    write_json_atomically(&destination, manifest, "codex_collection_manifest")
}

fn write_json_atomically<T: Serialize>(
    destination: &Path,
    value: &T,
    error_prefix: &str,
) -> Result<(), String> {
    let parent = destination
        .parent()
        .ok_or_else(|| format!("{error_prefix}_path_invalid"))?;
    let name = destination
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| format!("{error_prefix}_path_invalid"))?;
    let temporary = parent.join(format!(".{name}.{}", Uuid::new_v4()));
    let output = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temporary)
        .map_err(|_| format!("{error_prefix}_write_failed"))?;
    let mut writer = BufWriter::new(output);
    serde_json::to_writer_pretty(&mut writer, value)
        .map_err(|_| format!("{error_prefix}_write_failed"))?;
    writer
        .write_all(b"\n")
        .map_err(|_| format!("{error_prefix}_write_failed"))?;
    writer
        .flush()
        .map_err(|_| format!("{error_prefix}_write_failed"))?;
    writer
        .get_ref()
        .sync_all()
        .map_err(|_| format!("{error_prefix}_write_failed"))?;
    fs::set_permissions(&temporary, private_file_permissions())
        .map_err(|_| format!("{error_prefix}_permissions_failed"))?;
    fs::rename(&temporary, destination).map_err(|_| {
        let _ = fs::remove_file(&temporary);
        format!("{error_prefix}_finalize_failed")
    })
}

fn preserve_previous_manifest(root: &Path) -> Result<(), String> {
    let source = root.join(MANIFEST_NAME);
    if !source.is_file() {
        return Ok(());
    }
    let history = root.join("history");
    fs::create_dir_all(&history)
        .map_err(|_| "codex_collection_history_create_failed".to_string())?;
    set_private_directory(&history)?;
    let name = format!(
        "manifest-{}-{}.json",
        Utc::now().format("%Y%m%dT%H%M%SZ"),
        &Uuid::new_v4().to_string()[..8]
    );
    fs::copy(source, history.join(name))
        .map_err(|_| "codex_collection_history_write_failed".to_string())?;
    Ok(())
}

fn prepare_collection_root(value: &str, source_root: &Path) -> Result<PathBuf, String> {
    let candidate = resolve_user_path(value)?;
    fs::create_dir_all(&candidate).map_err(|_| "codex_collection_create_failed".to_string())?;
    let root = candidate
        .canonicalize()
        .map_err(|_| "codex_collection_path_invalid".to_string())?;
    if root == source_root || root.starts_with(source_root) || source_root.starts_with(&root) {
        return Err("codex_collection_overlaps_source".to_string());
    }
    if fs::symlink_metadata(&root)
        .map_err(|_| "codex_collection_path_invalid".to_string())?
        .file_type()
        .is_symlink()
    {
        return Err("codex_collection_symlink_forbidden".to_string());
    }
    Ok(root)
}

fn require_collection_root(value: &str) -> Result<PathBuf, String> {
    let root = resolve_user_path(value)?;
    if fs::symlink_metadata(&root)
        .map_err(|_| "codex_collection_not_found".to_string())?
        .file_type()
        .is_symlink()
    {
        return Err("codex_collection_symlink_forbidden".to_string());
    }
    let canonical = root
        .canonicalize()
        .map_err(|_| "codex_collection_not_found".to_string())?;
    if !canonical.is_dir() {
        return Err("codex_collection_not_found".to_string());
    }
    Ok(canonical)
}

fn require_source_root(value: &str) -> Result<PathBuf, String> {
    let root = resolve_user_path(value)?;
    if fs::symlink_metadata(&root)
        .map_err(|_| "codex_source_not_found".to_string())?
        .file_type()
        .is_symlink()
    {
        return Err("codex_source_symlink_forbidden".to_string());
    }
    let canonical = root
        .canonicalize()
        .map_err(|_| "codex_source_not_found".to_string())?;
    if !canonical.is_dir() {
        return Err("codex_source_not_found".to_string());
    }
    Ok(canonical)
}

fn resolve_user_path(value: &str) -> Result<PathBuf, String> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return Err("codex_path_required".to_string());
    }
    let path = if trimmed == "~" {
        home_directory()?
    } else if let Some(rest) = trimmed.strip_prefix("~/") {
        home_directory()?.join(rest)
    } else {
        PathBuf::from(trimmed)
    };
    if !path.is_absolute() {
        return Err("codex_path_must_be_absolute".to_string());
    }
    Ok(path)
}

fn safe_join(root: &Path, relative: &str) -> Result<PathBuf, String> {
    validate_relative(relative)?;
    Ok(root.join(relative))
}

fn validate_relative(value: &str) -> Result<(), String> {
    let path = Path::new(value);
    if value.is_empty()
        || path.is_absolute()
        || path
            .components()
            .any(|component| !matches!(component, Component::Normal(_)))
    {
        return Err("codex_collection_relative_path_invalid".to_string());
    }
    Ok(())
}

fn normalized_relative(path: &Path) -> Result<String, String> {
    if path.is_absolute()
        || path
            .components()
            .any(|part| !matches!(part, Component::Normal(_)))
    {
        return Err("codex_source_relative_path_invalid".to_string());
    }
    Ok(path.to_string_lossy().replace('\\', "/"))
}

fn session_counts(files: &[SourceFile]) -> (u64, u64) {
    let active = files
        .iter()
        .filter(|item| {
            item.relative.starts_with("sessions")
                && item.relative.extension().and_then(|value| value.to_str()) == Some("jsonl")
        })
        .count() as u64;
    let archived = files
        .iter()
        .filter(|item| {
            item.relative.starts_with("archived_sessions")
                && item.relative.extension().and_then(|value| value.to_str()) == Some("jsonl")
        })
        .count() as u64;
    (active, archived)
}

fn discover_workspace_roots(files: &[SourceFile]) -> Vec<String> {
    let mut roots = BTreeSet::new();
    for item in files.iter().filter(|item| {
        (item.relative.starts_with("sessions") || item.relative.starts_with("archived_sessions"))
            && item.relative.extension().and_then(|value| value.to_str()) == Some("jsonl")
    }) {
        let Ok(file) = File::open(&item.source) else {
            continue;
        };
        let mut sample = String::new();
        if BufReader::new(file)
            .take(SESSION_METADATA_READ_LIMIT)
            .read_to_string(&mut sample)
            .is_err()
        {
            continue;
        }
        for line in sample.lines().take(12) {
            let Ok(value) = serde_json::from_str::<serde_json::Value>(line) else {
                continue;
            };
            let cwd = value
                .pointer("/payload/cwd")
                .or_else(|| value.get("cwd"))
                .and_then(|value| value.as_str());
            if let Some(cwd) = cwd.filter(|cwd| Path::new(cwd).is_absolute()) {
                roots.insert(cwd.to_string());
                break;
            }
        }
    }
    roots.into_iter().collect()
}

fn read_codex_version(root: &Path) -> Option<String> {
    let value: serde_json::Value =
        serde_json::from_reader(File::open(root.join("version.json")).ok()?).ok()?;
    value
        .get("latest_version")
        .and_then(|item| item.as_str())
        .map(ToString::to_string)
}

fn collection_summary(root: &Path, manifest: &SnapshotManifest) -> CodexCollectionSummary {
    CodexCollectionSummary {
        format: manifest.format.clone(),
        collection_id: manifest.collection_id.clone(),
        collection_path: display_path(root),
        source_codex_home: manifest.source_codex_home.clone(),
        created_at: manifest.created_at.clone(),
        updated_at: manifest.updated_at.clone(),
        active_session_count: manifest.active_session_count,
        archived_session_count: manifest.archived_session_count,
        file_count: manifest.file_count,
        total_bytes: manifest.total_bytes,
        workspace_roots: manifest.workspace_roots.clone(),
    }
}

fn included_categories() -> Vec<String> {
    [
        "active sessions",
        "archived sessions",
        "session titles",
        "attachments",
        "generated images",
        "visualizations",
        "Codex memories",
        "rules",
        "skills",
        "global AGENTS instructions",
    ]
    .iter()
    .map(|value| value.to_string())
    .collect()
}

fn excluded_categories() -> Vec<String> {
    [
        "authentication tokens",
        "desktop cookies and browser state",
        "logs and caches",
        "installation identifiers",
        "volatile SQLite state",
        "plugins and temporary worktrees",
    ]
    .iter()
    .map(|value| value.to_string())
    .collect()
}

fn modified_ns(metadata: &fs::Metadata) -> Result<u64, String> {
    let duration = metadata
        .modified()
        .map_err(|_| "codex_file_timestamp_invalid".to_string())?
        .duration_since(UNIX_EPOCH)
        .map_err(|_| "codex_file_timestamp_invalid".to_string())?;
    u64::try_from(duration.as_nanos()).map_err(|_| "codex_file_timestamp_invalid".to_string())
}

fn home_directory() -> Result<PathBuf, String> {
    env::var_os("HOME")
        .map(PathBuf::from)
        .filter(|path| path.is_absolute())
        .ok_or_else(|| "home_directory_unavailable".to_string())
}

fn active_codex_home() -> Result<PathBuf, String> {
    Ok(env::var_os("CODEX_HOME")
        .map(PathBuf::from)
        .unwrap_or(home_directory()?.join(".codex")))
}

fn preferences_path() -> Result<PathBuf, String> {
    let config_home = env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .unwrap_or(home_directory()?.join(".config"));
    Ok(config_home.join("knowledge-dump").join(PREFERENCES_NAME))
}

fn display_path(path: &Path) -> String {
    path.to_string_lossy().to_string()
}

fn utc_now() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Secs, true)
}

fn shell_quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\\''"))
}

#[cfg(unix)]
fn private_file_permissions() -> fs::Permissions {
    use std::os::unix::fs::PermissionsExt;
    fs::Permissions::from_mode(0o600)
}

#[cfg(not(unix))]
fn private_file_permissions() -> fs::Permissions {
    fs::metadata(".")
        .expect("current directory metadata")
        .permissions()
}

#[cfg(unix)]
fn set_private_directory(path: &Path) -> Result<(), String> {
    use std::os::unix::fs::PermissionsExt;
    fs::set_permissions(path, fs::Permissions::from_mode(0o700))
        .map_err(|_| "codex_collection_permissions_failed".to_string())
}

#[cfg(not(unix))]
fn set_private_directory(_path: &Path) -> Result<(), String> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn fixture(root: &Path) -> PathBuf {
        let codex = root.join("source-codex");
        let session = codex.join("sessions/2026/09/04/rollout-active.jsonl");
        let archived = codex.join("archived_sessions/rollout-archived.jsonl");
        let attachment = codex.join("attachments/fixture/notes.txt");
        let generated = codex.join("generated_images/active/image.png");
        for path in [&session, &archived, &attachment, &generated] {
            fs::create_dir_all(path.parent().unwrap()).unwrap();
        }
        fs::write(
            &session,
            format!(
                "{{\"type\":\"session_meta\",\"payload\":{{\"cwd\":{}}}}}\n",
                serde_json::to_string(&display_path(root)).unwrap()
            ),
        )
        .unwrap();
        fs::write(&archived, b"{\"type\":\"session_meta\"}\n").unwrap();
        fs::write(&attachment, b"context\n").unwrap();
        fs::write(&generated, b"not-a-real-png").unwrap();
        fs::write(
            codex.join("session_index.jsonl"),
            b"{\"id\":\"active\",\"thread_name\":\"Active\"}\n",
        )
        .unwrap();
        fs::write(codex.join("auth.json"), b"{\"token\":\"never-copy\"}\n").unwrap();
        codex
    }

    #[test]
    fn creates_refreshes_verifies_and_restores_plain_collection() {
        let temporary = TempDir::new().unwrap();
        let source = fixture(temporary.path());
        let collection = temporary.path().join("backup/codex");
        let first = sync_collection(&display_path(&source), &display_path(&collection)).unwrap();
        assert_eq!(first.collection.active_session_count, 1);
        assert_eq!(first.collection.archived_session_count, 1);
        assert_eq!(
            first.collection.workspace_roots,
            vec![display_path(temporary.path())]
        );
        assert_eq!(first.added_files, 5);
        assert!(!collection.join("codex-home/auth.json").exists());
        assert!(collection
            .join("codex-home/generated_images/active/image.png")
            .is_file());

        let second = sync_collection(&display_path(&source), &display_path(&collection)).unwrap();
        assert_eq!(second.added_files, 0);
        assert_eq!(second.updated_files, 0);
        assert_eq!(second.removed_files, 0);
        assert_eq!(second.unchanged_files, 5);
        assert!(
            verify_collection(&display_path(&collection))
                .unwrap()
                .verified
        );

        let restored = temporary.path().join("restored-codex");
        let result =
            restore_collection(&display_path(&collection), &display_path(&restored)).unwrap();
        assert!(result.restored);
        assert!(restored
            .join("sessions/2026/09/04/rollout-active.jsonl")
            .is_file());
        assert!(!restored.join("auth.json").exists());
        assert_eq!(
            result.resume_command,
            format!("CODEX_HOME='{}' codex resume", display_path(&restored))
        );
    }

    #[test]
    fn refresh_replaces_changed_files_and_preserves_manifest_history() {
        let temporary = TempDir::new().unwrap();
        let source = fixture(temporary.path());
        let collection = temporary.path().join("backup/codex");
        sync_collection(&display_path(&source), &display_path(&collection)).unwrap();
        fs::write(
            source.join("sessions/2026/09/04/rollout-active.jsonl"),
            b"{\"type\":\"session_meta\"}\n{\"type\":\"event_msg\"}\n",
        )
        .unwrap();
        let refreshed =
            sync_collection(&display_path(&source), &display_path(&collection)).unwrap();
        assert_eq!(refreshed.updated_files, 1);
        assert_eq!(fs::read_dir(collection.join("history")).unwrap().count(), 1);

        fs::remove_file(source.join("attachments/fixture/notes.txt")).unwrap();
        let removed = sync_collection(&display_path(&source), &display_path(&collection)).unwrap();
        assert_eq!(removed.removed_files, 1);
        assert!(!collection
            .join("codex-home/attachments/fixture/notes.txt")
            .exists());
    }

    #[test]
    fn verification_rejects_tampered_snapshot() {
        let temporary = TempDir::new().unwrap();
        let source = fixture(temporary.path());
        let collection = temporary.path().join("backup/codex");
        sync_collection(&display_path(&source), &display_path(&collection)).unwrap();
        fs::write(
            collection.join("codex-home/attachments/fixture/notes.txt"),
            b"tampered\n",
        )
        .unwrap();
        assert!(verify_collection(&display_path(&collection))
            .unwrap_err()
            .starts_with("codex_collection_checksum_mismatch"));
    }
}
