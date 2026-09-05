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
7. Authenticate that isolated home and open its task picker with `codex resume`
   using the commands shown by Knowledge Dump.
8. Clone the relevant Git repository separately and let Codex rebind the task
   to that working directory when prompted.

Restore never writes over the active `~/.codex` directory. This makes the first
recovery drill reversible and avoids mixing restored task state with the
currently running desktop environment.

## Fresh-system restoration

After verifying a collection with an isolated restore, install it on a new
workstation before the first Codex or ChatGPT launch:

```bash
knowledge-dump codex-storage verify "/media/user/encrypted-drive/Knowledge Dump/Codex Workspace"
knowledge-dump codex-storage restore-default "/media/user/encrypted-drive/Knowledge Dump/Codex Workspace"
codex login
codex resume
```

`restore-default` writes to the effective `CODEX_HOME`, normally `~/.codex`.
It verifies every copied file against the collection manifest and renames the
completed restore into place atomically. It has no overwrite or merge mode and
fails if the destination already exists, including an existing symbolic link.
Use `restore-test` instead when Codex has already created a local profile.

The restored files provide the durable task history, task index, selected
artifacts, rules, skills, and recorded workspace paths. Authentication, desktop
cookies, browser state, caches, logs, volatile databases, and Git repositories
are intentionally excluded. Sign in again and clone or restore the referenced
repositories separately.

## Automatic terminal workflow

The repository includes a wrapper that discovers `CODEX_HOME` (or `~/.codex`),
uses the remembered Knowledge Dump collection location, and runs the same
native collection and verification implementation as the desktop interface:

```bash
npm run codex:storage -- discover
npm run codex:storage -- collect
npm run codex:storage -- verify
```

Pass a destination to `collect` to select a different local collection:

```bash
npm run codex:storage -- collect "/media/user/encrypted-drive/Knowledge Dump/Codex Workspace"
```

An installed package exposes the same commands without the development wrapper:

```bash
knowledge-dump codex-storage discover
knowledge-dump codex-storage collect
knowledge-dump codex-storage verify
knowledge-dump codex-storage restore-default [COLLECTION_PATH]
```

The collection manifest records every absolute workspace path found in session
metadata. Whole Git repositories are not copied implicitly: they may contain
large build directories, ignored credentials, or unrelated data. A later
workspace-restoration pass can use these references and explicit repository
metadata to clone or restore each selected workspace safely.

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
