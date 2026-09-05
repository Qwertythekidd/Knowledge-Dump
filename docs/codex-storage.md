# Codex structured storage

Knowledge Dump treats a portable Codex workspace as a structured local
collection, not as a copy of the entire Codex desktop profile. The first
implementation is local-only and intentionally unencrypted. Store collections
on an encrypted filesystem or encrypted removable drive.

## Collection format

A collection uses the versioned format
`knowledge-dump.codex-workspace-snapshot.v1`:

```text
codex-workspace/
  manifest.json
  codex-home/
    sessions/
    archived_sessions/
    attachments/
    generated_images/
    visualizations/
    memories/
    rules/
    skills/
    session_index.jsonl
    AGENTS.md
    AGENTS.override.md
    version.json
  history/
    manifest-<timestamp>-<id>.json
```

The manifest records a stable collection ID, source path, timestamps, file
sizes, source modification times, and SHA-256 hashes. Refresh keeps unchanged
files in place, atomically replaces changed files, adds new files, and removes
files no longer present in the source. The previous manifest is retained before
each successful refresh.

Knowledge Dump remembers the selected source, collection, and restore paths in
`$XDG_CONFIG_HOME/knowledge-dump/codex-storage.json`. That record contains no
task content or credentials; it only lets later refreshes reopen the same local
collection.

Knowledge Dump includes durable task transcripts and task-owned artifacts. It
excludes login tokens, desktop cookies and browser state, logs, caches,
installation identifiers, volatile SQLite files, plugins, and temporary
worktrees. Git repositories are not part of this collection and should be
cloned separately on the destination workstation.

## Local workflow

1. Open `Codex storage` in the native Knowledge Dump application. Gateway login
   is not required for local collection work.
2. Inspect the source, normally `~/.codex`.
3. Select an empty or existing collection directory on an encrypted local
   drive.
4. Create the collection. Run `Update local collection` whenever new Codex work
   should be captured.
5. Run `Verify collection` before treating the copy as recoverable.
6. Prepare a test restore into a new directory such as
   `~/.codex-knowledge-dump-restore`.
7. Authenticate that isolated home and open its task picker using the commands
   shown by Knowledge Dump.
8. Clone the relevant Git repository separately and let Codex rebind the task
   to that working directory when prompted.

Restore never writes over the active `~/.codex` directory. This makes the first
recovery drill reversible and avoids mixing restored task state with the
currently running desktop environment.

## Cloud boundary

The plain collection is the source material for the next phase, not an object
that may be uploaded directly. Cloud publication must first verify the local
manifest, encrypt files and metadata client-side, and then upload an immutable
encrypted version through the Knowledge Dump Gateway. DigitalOcean Spaces must
never receive the plain collection or Codex authentication state.

Native task restoration is best-effort because Codex does not currently expose
a supported arbitrary archive-import API. The durable transcript remains useful
as development context even when a future Codex version cannot resume a native
task record directly.
