import { useEffect, useRef, useState } from "react";
import type {
  Account,
  ActivityEvent,
  CloudFile,
  CodexCollectionSummary,
  CodexRestoreResult,
  CodexSourceInventory,
  CodexSyncResult,
  CodexVerificationResult,
  Device,
  StorageHealth,
  UploadSession,
} from "@knowledge-dump/protocol";

import {
  activity as getActivity,
  abortUpload,
  createFolder,
  currentGatewayUrl,
  devices as getDevices,
  downloadFile,
  files as getFiles,
  login,
  logout,
  purgeFile,
  renameFile,
  revokeDevice,
  savedToken,
  saveGatewayUrl,
  session,
  setArchived,
  storageHealth,
  uploadFile,
} from "./api";
import {
  chooseLocalDirectory,
  codexStorageDefaults,
  inspectCodexCollection,
  localCodexAvailable,
  restoreCodexCollection,
  saveCodexStoragePreferences,
  scanCodexSource,
  syncCodexCollection,
  verifyCodexCollection,
} from "./localCodex";
import {
  ActivityIcon,
  ArchiveIcon,
  CheckIcon,
  CloseIcon,
  CloudIcon,
  DownloadIcon,
  FileIcon,
  FolderIcon,
  GridIcon,
  ImageIcon,
  ListIcon,
  MoreIcon,
  SearchIcon,
  SettingsIcon,
  UploadIcon,
} from "./components/Icons";

type View = "files" | "codex" | "recent" | "archived" | "transfers" | "settings";
type DisplayMode = "grid" | "list";
type TransferStatus = "queued" | "preparing" | "uploading" | "verifying" | "completed" | "failed" | "cancelled";

interface Transfer {
  id: string;
  name: string;
  size: number;
  progress: number;
  status: TransferStatus;
  file: File;
  parentId: string | null;
  sessionId?: string;
  error?: string;
  errorCode?: string;
}

export default function App() {
  const [account, setAccount] = useState<Account | null>(null);
  const [localCodexOnly, setLocalCodexOnly] = useState(false);
  const [booting, setBooting] = useState(true);
  const [error, setError] = useState("");
  const [view, setView] = useState<View>("files");
  const [displayMode, setDisplayMode] = useState<DisplayMode>("list");
  const [items, setItems] = useState<CloudFile[]>([]);
  const [folderTrail, setFolderTrail] = useState<CloudFile[]>([]);
  const [search, setSearch] = useState("");
  const [health, setHealth] = useState<StorageHealth | null>(null);
  const [healthBusy, setHealthBusy] = useState(false);
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [transfers, setTransfers] = useState<Transfer[]>([]);
  const [folderModal, setFolderModal] = useState(false);
  const [menuFileId, setMenuFileId] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const transferControllers = useRef(new Map<string, AbortController>());
  const transferSessions = useRef(new Map<string, string>());

  const currentFolder = folderTrail.at(-1) || null;
  const currentStatus = view === "archived" ? "archived" : "active";

  useEffect(() => {
    let active = true;
    if (!savedToken()) {
      setBooting(false);
      return;
    }
    Promise.all([session(), storageHealth()])
      .then(([sessionAccount, storage]) => {
        if (!active) return;
        setAccount(sessionAccount);
        setHealth(storage);
      })
      .catch(() => { void logout(); })
      .finally(() => active && setBooting(false));
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!account || view === "settings" || view === "transfers" || view === "recent" || view === "codex") return;
    void refreshFiles();
  }, [account, currentFolder?.id, view, search]);

  useEffect(() => {
    if (!account) return;
    void getActivity().then(setEvents).catch(() => undefined);
  }, [account, view, transfers]);

  async function refreshFiles() {
    try {
      setError("");
      setItems(await getFiles(currentFolder?.id || null, currentStatus, search));
    } catch (reason) {
      setError(messageFor(reason));
    }
  }

  async function refreshHealth() {
    setHealthBusy(true);
    setError("");
    try {
      setHealth(await storageHealth());
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setHealthBusy(false);
    }
  }

  async function handleLogout() {
    await logout();
    setAccount(null);
    setItems([]);
    setFolderTrail([]);
  }

  function openFolder(folder: CloudFile) {
    setFolderTrail((current) => [...current, folder]);
    setSearch("");
  }

  async function handleUpload(selected: FileList | null) {
    if (!selected?.length) return;
    setView("files");
    const queue = Array.from(selected).map<Transfer>((file) => ({
      id: crypto.randomUUID(),
      name: file.name,
      size: file.size,
      progress: 0,
      status: "queued",
      file,
      parentId: currentFolder?.id || null,
    }));
    setTransfers((current) => [...queue, ...current]);

    for (let index = 0; index < selected.length; index += 1) {
      const transfer = queue[index];
      await runTransfer(transfer);
    }
    await Promise.all([refreshFiles(), refreshHealth()]);
  }

  async function runTransfer(transfer: Transfer, resume = false) {
    const controller = new AbortController();
    transferControllers.current.set(transfer.id, controller);
    updateTransfer(transfer.id, { status: "preparing", error: undefined, errorCode: undefined, progress: resume ? transfer.progress : 2 });
    try {
      await uploadFile(
        transfer.file,
        transfer.parentId,
        (progress) => updateTransfer(transfer.id, { status: progress >= 95 ? "verifying" : "uploading", progress }),
        (upload: UploadSession) => {
          transferSessions.current.set(transfer.id, upload.id);
          updateTransfer(transfer.id, { sessionId: upload.id });
        },
        controller.signal,
        resume ? transfer.sessionId : undefined,
      );
      updateTransfer(transfer.id, { status: "completed", progress: 100 });
    } catch (reason) {
      const cancelled = controller.signal.aborted;
      const errorCode = messageFor(reason);
      updateTransfer(transfer.id, {
        status: cancelled ? "cancelled" : "failed",
        error: cancelled ? "Transfer cancelled" : humanError(errorCode),
        errorCode: cancelled ? "upload_cancelled" : errorCode,
      });
    } finally {
      transferControllers.current.delete(transfer.id);
    }
  }

  async function cancelTransfer(transfer: Transfer) {
    transferControllers.current.get(transfer.id)?.abort();
    const sessionId = transferSessions.current.get(transfer.id) || transfer.sessionId;
    if (sessionId) {
      try {
        await abortUpload(sessionId);
      } catch (reason) {
        const errorCode = messageFor(reason);
        updateTransfer(transfer.id, { status: "failed", error: humanError(errorCode), errorCode });
      }
    }
  }

  async function retryTransfer(transfer: Transfer) {
    const restartErrors = new Set(["upload_expired", "upload_not_active", "upload_source_mismatch"]);
    const resume = transfer.status === "failed" && Boolean(transfer.sessionId) && !restartErrors.has(transfer.errorCode || "");
    if (!resume) {
      transferSessions.current.delete(transfer.id);
      updateTransfer(transfer.id, { sessionId: undefined, progress: 0 });
    }
    await runTransfer(transfer, resume);
    await Promise.all([refreshFiles(), refreshHealth()]);
  }

  function updateTransfer(id: string, update: Partial<Transfer>) {
    setTransfers((current) => current.map((item) => item.id === id ? { ...item, ...update } : item));
  }

  async function handleArchive(item: CloudFile) {
    setBusyAction(item.id);
    try {
      await setArchived(item.id, item.status !== "archived");
      await refreshFiles();
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusyAction("");
      setMenuFileId(null);
    }
  }

  async function handleRename(item: CloudFile) {
    const nextName = window.prompt("Rename item", item.name)?.trim();
    if (!nextName || nextName === item.name) return;
    setBusyAction(item.id);
    try {
      await renameFile(item.id, nextName);
      await refreshFiles();
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusyAction("");
      setMenuFileId(null);
    }
  }

  async function handlePurge(item: CloudFile) {
    if (!window.confirm(`Permanently delete “${item.name}”? This cannot be undone.`)) return;
    setBusyAction(item.id);
    try {
      await purgeFile(item.id);
      await refreshFiles();
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusyAction("");
      setMenuFileId(null);
    }
  }

  if (booting) return <div className="app-loading"><CloudIcon /><span>Opening Knowledge Dump…</span></div>;
  if (!account && localCodexOnly) return <div className="local-codex-shell"><header><div className="brand-lockup"><CloudIcon /><span>Knowledge Dump</span></div><button className="secondary" onClick={() => setLocalCodexOnly(false)}>Return to sign in</button></header><CodexStorageView /></div>;
  if (!account) return <LoginScreen onOpenLocalCodex={() => setLocalCodexOnly(true)} onAuthenticated={(nextAccount, nextHealth) => { setAccount(nextAccount); setHealth(nextHealth); }} />;

  return (
    <div className="app-shell">
      <Sidebar account={account} view={view} health={health} onView={(next) => { setView(next); if (next !== "files") setFolderTrail([]); }} onLogout={handleLogout} />

      <main className="workspace">
        <header className="topbar">
          <div className="search-box"><SearchIcon /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={view === "codex" ? "Codex storage is indexed locally" : "Search this folder"} disabled={view !== "files" && view !== "archived"} /></div>
          <button className={`health-chip ${health?.providerReachable ? "healthy" : "offline"}`} onClick={() => { setView("settings"); void refreshHealth(); }}>
            <span className="pulse-dot" />
            {health?.providerReachable ? "Storage online" : "Check storage"}
          </button>
          <div className="avatar" title={account.email}>{initials(account.displayName)}</div>
        </header>

        {error ? <div className="error-banner"><span>{humanError(error)}</span><button onClick={() => setError("")}><CloseIcon /></button></div> : null}

        {view === "codex" ? (
          <CodexStorageView />
        ) : view === "settings" ? (
          <SettingsView health={health} busy={healthBusy} onRefresh={refreshHealth} />
        ) : view === "transfers" ? (
          <TransfersView transfers={transfers} onCancel={cancelTransfer} onRetry={retryTransfer} />
        ) : view === "recent" ? (
          <ActivityView events={events} />
        ) : (
          <FilesView
            view={view}
            items={items}
            trail={folderTrail}
            displayMode={displayMode}
            menuFileId={menuFileId}
            busyAction={busyAction}
            onMode={setDisplayMode}
            onTrail={setFolderTrail}
            onFolder={openFolder}
            onNewFolder={() => setFolderModal(true)}
            onUpload={() => fileInput.current?.click()}
            onMenu={setMenuFileId}
            onDownload={(item) => downloadFile(item).catch((reason) => setError(messageFor(reason)))}
            onArchive={handleArchive}
            onRename={handleRename}
            onPurge={handlePurge}
          />
        )}
      </main>

      <aside className="activity-rail">
        <div className="rail-heading"><span>Activity</span><ActivityIcon /></div>
        <div className="activity-list">
          {events.slice(0, 7).map((event) => <article key={event.id}><span className="activity-mark" /><div><strong>{activityLabel(event.action)}</strong><p>{event.targetName}</p><time>{relativeTime(event.createdAt)}</time></div></article>)}
          {!events.length ? <p className="empty-note">Workspace activity will appear here.</p> : null}
        </div>
        <div className="rail-storage">
          <div><span>Storage</span><strong>{health ? formatBytes(health.usedBytes) : "—"}</strong></div>
          <div className="storage-bar"><span style={{ width: health ? `${Math.max(2, Math.min(100, health.usedBytes / health.quotaBytes * 100))}%` : "0%" }} /></div>
          <small>{health ? `${formatBytes(health.usedBytes)} of ${formatBytes(health.quotaBytes)} used` : "Health check required"}</small>
        </div>
      </aside>

      <input ref={fileInput} className="visually-hidden" type="file" multiple onChange={(event) => { void handleUpload(event.target.files); event.target.value = ""; }} />
      {folderModal ? <NewFolderModal parentId={currentFolder?.id || null} onClose={() => setFolderModal(false)} onCreated={async () => { setFolderModal(false); await refreshFiles(); }} /> : null}
    </div>
  );
}

function CodexStorageView() {
  const nativeAvailable = localCodexAvailable();
  const [sourcePath, setSourcePath] = useState("");
  const [collectionPath, setCollectionPath] = useState("");
  const [restorePath, setRestorePath] = useState("");
  const [inventory, setInventory] = useState<CodexSourceInventory | null>(null);
  const [collection, setCollection] = useState<CodexCollectionSummary | null>(null);
  const [syncResult, setSyncResult] = useState<CodexSyncResult | null>(null);
  const [verification, setVerification] = useState<CodexVerificationResult | null>(null);
  const [restore, setRestore] = useState<CodexRestoreResult | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!nativeAvailable) return;
    let active = true;
    void codexStorageDefaults()
      .then(async (defaults) => {
        if (!active) return;
        setSourcePath(defaults.sourceCodexHome);
        setCollectionPath(defaults.collectionPath);
        setRestorePath(defaults.restorePath);
        const [source, existing] = await Promise.all([
          scanCodexSource(defaults.sourceCodexHome),
          inspectCodexCollection(defaults.collectionPath).catch(() => null),
        ]);
        if (!active) return;
        setInventory(source);
        setCollection(existing);
      })
      .catch((reason) => active && setError(humanError(messageFor(reason))));
    return () => { active = false; };
  }, [nativeAvailable]);

  async function scan() {
    setBusy("scan");
    setError("");
    try {
      setInventory(await scanCodexSource(sourcePath));
      await saveCodexStoragePreferences(sourcePath, collectionPath, restorePath);
    } catch (reason) {
      setError(humanError(messageFor(reason)));
    } finally {
      setBusy("");
    }
  }

  async function chooseDirectory(currentPath: string, assign: (path: string) => void) {
    setError("");
    try {
      const selected = await chooseLocalDirectory(currentPath);
      if (selected) assign(selected);
    } catch (reason) {
      setError(humanError(messageFor(reason)));
    }
  }

  async function chooseRestoreParent() {
    const separator = restorePath.lastIndexOf("/");
    const parent = separator > 0 ? restorePath.slice(0, separator) : restorePath;
    const leaf = separator >= 0 ? restorePath.slice(separator + 1) : "codex-knowledge-dump-restore";
    setError("");
    try {
      const selected = await chooseLocalDirectory(parent);
      if (selected) setRestorePath(`${selected.replace(/\/+$/, "")}/${leaf || "codex-knowledge-dump-restore"}`);
    } catch (reason) {
      setError(humanError(messageFor(reason)));
    }
  }

  async function refreshCollection() {
    setBusy("sync");
    setError("");
    setVerification(null);
    setRestore(null);
    try {
      const result = await syncCodexCollection(sourcePath, collectionPath);
      setSyncResult(result);
      setCollection(result.collection);
      setInventory(await scanCodexSource(sourcePath));
      await saveCodexStoragePreferences(sourcePath, collectionPath, restorePath);
    } catch (reason) {
      setError(humanError(messageFor(reason)));
    } finally {
      setBusy("");
    }
  }

  async function loadCollection() {
    setBusy("inspect");
    setError("");
    try {
      setCollection(await inspectCodexCollection(collectionPath));
      await saveCodexStoragePreferences(sourcePath, collectionPath, restorePath);
    } catch (reason) {
      setCollection(null);
      setError(humanError(messageFor(reason)));
    } finally {
      setBusy("");
    }
  }

  async function verify() {
    setBusy("verify");
    setError("");
    try {
      setVerification(await verifyCodexCollection(collectionPath));
      await saveCodexStoragePreferences(sourcePath, collectionPath, restorePath);
    } catch (reason) {
      setVerification(null);
      setError(humanError(messageFor(reason)));
    } finally {
      setBusy("");
    }
  }

  async function prepareRestore() {
    if (!window.confirm(`Prepare an isolated Codex home at “${restorePath}”? The destination must not already exist.`)) return;
    setBusy("restore");
    setError("");
    setRestore(null);
    try {
      setRestore(await restoreCodexCollection(collectionPath, restorePath));
      await saveCodexStoragePreferences(sourcePath, collectionPath, restorePath);
    } catch (reason) {
      setError(humanError(messageFor(reason)));
    } finally {
      setBusy("");
    }
  }

  return <section className="content-view codex-storage-view">
    <div className="view-heading">
      <div><p className="eyebrow">Local structured storage</p><h1>Codex workspace</h1><p className="view-intro">Collect the durable parts of your local Codex environment into a plain, refreshable folder before preparing any cloud copy.</p></div>
      <span className={`local-mode-badge ${nativeAvailable ? "ready" : "unavailable"}`}>{nativeAvailable ? "Native access ready" : "Native app required"}</span>
    </div>

    {error ? <div className="inline-error codex-storage-error">{error}</div> : null}

    <div className="codex-storage-grid">
      <article className="codex-storage-card source-card">
        <div className="section-heading"><div><p className="eyebrow">Step 1</p><h2>Inspect Codex source</h2></div><ArchiveIcon /></div>
        <p>Knowledge Dump reads only portable session content. Authentication, desktop cookies, logs, caches, and volatile databases are excluded.</p>
        <label>Codex home<input value={sourcePath} onChange={(event) => setSourcePath(event.target.value)} placeholder="~/.codex" disabled={!nativeAvailable || Boolean(busy)} /></label>
        <div className="button-row"><button className="secondary" disabled={!nativeAvailable || Boolean(busy) || !sourcePath.trim()} onClick={() => { void scan(); }}>{busy === "scan" ? "Scanning…" : "Refresh source inventory"}</button></div>
        {inventory ? <div className="codex-stat-grid">
          <div><strong>{inventory.activeSessionCount}</strong><span>Active tasks</span></div>
          <div><strong>{inventory.archivedSessionCount}</strong><span>Archived tasks</span></div>
          <div><strong>{inventory.fileCount}</strong><span>Portable files</span></div>
          <div><strong>{formatBytes(inventory.totalBytes)}</strong><span>Source size</span></div>
        </div> : null}
      </article>

      <article className="codex-storage-card collection-card">
        <div className="section-heading"><div><p className="eyebrow">Step 2</p><h2>Create local collection</h2></div><FolderIcon /></div>
        <p>This is an unencrypted directory. Choose a folder on an encrypted local drive. Running it again adds new files and replaces changed files without rebuilding unchanged content.</p>
        <label>Collection folder<input value={collectionPath} onChange={(event) => setCollectionPath(event.target.value)} placeholder="/media/your-drive/Knowledge Dump/Codex Workspace" disabled={!nativeAvailable || Boolean(busy)} /></label>
        <div className="button-row">
          <button className="secondary" disabled={!nativeAvailable || Boolean(busy)} onClick={() => { void chooseDirectory(collectionPath, setCollectionPath); }}>Choose folder</button>
          <button className="primary" disabled={!nativeAvailable || Boolean(busy) || !sourcePath.trim() || !collectionPath.trim()} onClick={() => { void refreshCollection(); }}>{busy === "sync" ? "Updating collection…" : collection ? "Update local collection" : "Create local collection"}</button>
          <button className="secondary" disabled={!nativeAvailable || Boolean(busy) || !collectionPath.trim()} onClick={() => { void loadCollection(); }}>{busy === "inspect" ? "Opening…" : "Open existing"}</button>
        </div>
        {syncResult ? <div className="codex-result-strip"><span>{syncResult.addedFiles} added</span><span>{syncResult.updatedFiles} updated</span><span>{syncResult.removedFiles} removed</span><span>{syncResult.unchangedFiles} unchanged</span></div> : null}
        {collection ? <div className="codex-collection-summary">
          <div><strong>Collection {collection.collectionId.slice(0, 8)}</strong><span>Updated {new Date(collection.updatedAt).toLocaleString()}</span></div>
          <div><span>{collection.activeSessionCount + collection.archivedSessionCount} tasks</span><span>{collection.fileCount} files</span><span>{formatBytes(collection.totalBytes)}</span></div>
          <code>{collection.collectionPath}</code>
        </div> : <p className="empty-note">No collection has been loaded from this path.</p>}
      </article>

      <article className="codex-storage-card verify-card">
        <div className="section-heading"><div><p className="eyebrow">Step 3</p><h2>Verify and test restore</h2></div><CheckIcon /></div>
        <p>Verification reads every collected file and checks it against the manifest. Restore always creates a separate Codex home and refuses to overwrite the active one.</p>
        <div className="button-row"><button className="secondary" disabled={!nativeAvailable || Boolean(busy) || !collection} onClick={() => { void verify(); }}>{busy === "verify" ? "Verifying every file…" : "Verify collection"}</button></div>
        {verification ? <div className="codex-verification"><CheckIcon /><div><strong>Collection verified</strong><span>{verification.fileCount} files · {formatBytes(verification.totalBytes)} · {new Date(verification.checkedAt).toLocaleString()}</span></div></div> : null}
        <label>Isolated restore destination<input value={restorePath} onChange={(event) => setRestorePath(event.target.value)} placeholder="~/.codex-knowledge-dump-restore" disabled={!nativeAvailable || Boolean(busy)} /></label>
        <div className="button-row"><button className="secondary" disabled={!nativeAvailable || Boolean(busy)} onClick={() => { void chooseRestoreParent(); }}>Choose destination parent</button><button className="primary" disabled={!nativeAvailable || Boolean(busy) || !collection || !restorePath.trim()} onClick={() => { void prepareRestore(); }}>{busy === "restore" ? "Preparing restore…" : "Prepare test restore"}</button></div>
        {restore ? <div className="codex-restore-result"><strong>Restored without authentication data</strong><span>Authenticate and inspect the restored task picker with:</span><code>{restore.loginCommand}</code><code>{restore.resumeCommand}</code></div> : null}
      </article>

      <article className="codex-storage-card future-card">
        <p className="eyebrow">Next stage</p><h2>Encrypted cloud publication</h2>
        <p>After this local collection passes a real restore test, Knowledge Dump can encrypt the verified manifest and files client-side and publish that immutable version through the gateway to DigitalOcean Spaces.</p>
        <span>Cloud upload intentionally deferred</span>
      </article>
    </div>
  </section>;
}

function LoginScreen({ onAuthenticated, onOpenLocalCodex }: { onAuthenticated: (account: Account, health: StorageHealth) => void; onOpenLocalCodex: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [gateway, setGateway] = useState(currentGatewayUrl());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    saveGatewayUrl(gateway === "/api" ? "" : gateway);
    try {
      const authenticated = await login(email, password);
      const health = await storageHealth();
      onAuthenticated(authenticated.account, health);
    } catch (reason) {
      setError(humanError(messageFor(reason)));
    } finally {
      setBusy(false);
    }
  }

  return <main className="login-screen">
    <section className="login-story">
      <div className="brand-lockup"><CloudIcon /><span>Knowledge Dump</span></div>
      <div className="story-copy"><p className="eyebrow">Your working memory, portable.</p><h1>Carry the useful parts of your digital life.</h1><p>One private workspace for project archives, media, reference files, and the context you want waiting on your next machine.</p></div>
      <div className="story-orbit"><span>Encrypted transfer</span><span>Device recovery</span><span>Cloud health</span></div>
    </section>
    <section className="login-panel">
      <form onSubmit={submit}>
        <div><p className="eyebrow">Development gateway</p><h2>Open your dump.</h2><p>Authenticate with the standalone storage service to continue.</p></div>
        {error ? <div className="login-error">{error}</div> : null}
        <label>Gateway URL<input value={gateway} onChange={(event) => setGateway(event.target.value)} required /></label>
        <label>Email<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="username" required /></label>
        <label>Password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required /></label>
        <button className="primary wide" disabled={busy}>{busy ? "Authenticating…" : "Sign in to Knowledge Dump"}</button>
        <button type="button" className="secondary wide local-storage-entry" disabled={!localCodexAvailable()} onClick={onOpenLocalCodex}>Open local Codex storage</button>
        <small>Accounts are provisioned by the Knowledge Dump gateway operator.</small>
        {!localCodexAvailable() ? <small>Local Codex storage is available in the native desktop app.</small> : null}
      </form>
    </section>
  </main>;
}

function Sidebar({ account, view, health, onView, onLogout }: { account: Account; view: View; health: StorageHealth | null; onView: (view: View) => void; onLogout: () => void }) {
  const navigation: Array<[View, string, React.ReactNode]> = [
    ["files", "My dump", <CloudIcon />],
    ["codex", "Codex storage", <ArchiveIcon />],
    ["recent", "Recent activity", <ActivityIcon />],
    ["archived", "Archive", <ArchiveIcon />],
    ["transfers", "Transfers", <UploadIcon />],
    ["settings", "Connection", <SettingsIcon />],
  ];
  return <aside className="sidebar">
    <div className="brand-lockup compact"><CloudIcon /><span>Knowledge<br />Dump</span></div>
    <nav>{navigation.map(([id, label, icon]) => <button key={id} className={view === id ? "active" : ""} onClick={() => onView(id)}>{icon}<span>{label}</span>{id === "settings" ? <i className={health?.providerReachable ? "online" : ""} /> : null}</button>)}</nav>
    <div className="sidebar-account"><div className="avatar small">{initials(account.displayName)}</div><div><strong>{account.displayName}</strong><span>{account.plan} workspace</span></div><button onClick={onLogout}>Sign out</button></div>
  </aside>;
}

interface FilesViewProps {
  view: View;
  items: CloudFile[];
  trail: CloudFile[];
  displayMode: DisplayMode;
  menuFileId: string | null;
  busyAction: string;
  onMode: (mode: DisplayMode) => void;
  onTrail: (trail: CloudFile[]) => void;
  onFolder: (item: CloudFile) => void;
  onNewFolder: () => void;
  onUpload: () => void;
  onMenu: (id: string | null) => void;
  onDownload: (item: CloudFile) => void;
  onArchive: (item: CloudFile) => void;
  onRename: (item: CloudFile) => void;
  onPurge: (item: CloudFile) => void;
}

function FilesView(props: FilesViewProps) {
  const title = props.view === "archived" ? "Archive" : props.trail.at(-1)?.name || "My dump";
  return <section className="content-view files-view">
    <div className="view-heading"><div><p className="eyebrow">{props.view === "archived" ? "Recover or permanently remove" : "Cloud workspace"}</p><h1>{title}</h1></div><div className="toolbar"><button className="secondary" onClick={props.onNewFolder} disabled={props.view === "archived"}><FolderIcon />New folder</button><button className="primary" onClick={props.onUpload} disabled={props.view === "archived"}><UploadIcon />Upload files</button></div></div>
    <div className="file-controls"><div className="breadcrumbs"><button onClick={() => props.onTrail([])}>Knowledge Dump</button>{props.trail.map((folder, index) => <span key={folder.id}>/<button onClick={() => props.onTrail(props.trail.slice(0, index + 1))}>{folder.name}</button></span>)}</div><div className="mode-toggle"><button className={props.displayMode === "list" ? "active" : ""} onClick={() => props.onMode("list")}><ListIcon /></button><button className={props.displayMode === "grid" ? "active" : ""} onClick={() => props.onMode("grid")}><GridIcon /></button></div></div>
    {props.items.length ? props.displayMode === "list" ? <div className="file-table"><div className="file-row table-head"><span>Name</span><span>Size</span><span>Modified</span><span>Version</span><span /></div>{props.items.map((item) => <FileRow key={item.id} item={item} menuOpen={props.menuFileId === item.id} busy={props.busyAction === item.id} {...props} />)}</div> : <div className="file-grid">{props.items.map((item) => <FileCard key={item.id} item={item} menuOpen={props.menuFileId === item.id} busy={props.busyAction === item.id} {...props} />)}</div> : <div className="empty-state"><div><CloudIcon /></div><h3>{props.view === "archived" ? "The archive is clear" : "This folder has room to think"}</h3><p>{props.view === "archived" ? "Archived files will wait here until you restore or delete them." : "Upload reference material or create a folder to begin organizing this space."}</p></div>}
  </section>;
}

function FileRow({ item, menuOpen, busy, ...props }: FilesViewProps & { item: CloudFile; menuOpen: boolean; busy: boolean }) {
  return <div className="file-row"><button className="file-name" onDoubleClick={() => item.kind === "folder" && props.onFolder(item)} onClick={() => item.kind === "folder" && props.onFolder(item)}><FileKindIcon item={item} /><span><strong>{item.name}</strong><small>{item.mimeType || (item.kind === "folder" ? "Folder" : "Cloud object")}</small></span></button><span>{item.kind === "folder" ? "—" : formatBytes(item.sizeBytes)}</span><span>{relativeTime(item.updatedAt)}</span><span>v{item.version}</span><FileMenu item={item} open={menuOpen} busy={busy} {...props} /></div>;
}

function FileCard({ item, menuOpen, busy, ...props }: FilesViewProps & { item: CloudFile; menuOpen: boolean; busy: boolean }) {
  return <article className="file-card" onDoubleClick={() => item.kind === "folder" && props.onFolder(item)}><div className={`file-preview ${item.kind}`}><FileKindIcon item={item} /><FileMenu item={item} open={menuOpen} busy={busy} {...props} /></div><strong>{item.name}</strong><span>{item.kind === "folder" ? "Folder" : formatBytes(item.sizeBytes)} · {relativeTime(item.updatedAt)}</span></article>;
}

function FileMenu({ item, open, busy, onMenu, onDownload, onArchive, onRename, onPurge }: FilesViewProps & { item: CloudFile; open: boolean; busy: boolean }) {
  return <div className="file-menu-wrap"><button className="icon-button" disabled={busy} onClick={(event) => { event.stopPropagation(); onMenu(open ? null : item.id); }}><MoreIcon /></button>{open ? <div className="file-menu" onClick={(event) => event.stopPropagation()}>{item.kind !== "folder" ? <button onClick={() => onDownload(item)}><DownloadIcon />Download</button> : null}<button onClick={() => onRename(item)}>Rename</button><button onClick={() => onArchive(item)}>{item.status === "archived" ? "Restore" : "Archive"}</button>{item.status === "archived" ? <button className="danger" onClick={() => onPurge(item)}>Delete permanently</button> : null}</div> : null}</div>;
}

function FileKindIcon({ item }: { item: CloudFile }) {
  if (item.kind === "folder") return <FolderIcon />;
  if (item.kind === "image" || item.kind === "video") return <ImageIcon />;
  if (item.kind === "archive") return <ArchiveIcon />;
  return <FileIcon />;
}

function TransfersView({ transfers, onCancel, onRetry }: { transfers: Transfer[]; onCancel: (transfer: Transfer) => Promise<void>; onRetry: (transfer: Transfer) => Promise<void> }) {
  return <section className="content-view"><div className="view-heading"><div><p className="eyebrow">Resumable multipart queue</p><h1>Transfers</h1></div></div><div className="transfer-list">{transfers.map((transfer) => <article key={transfer.id}><div className={`transfer-icon ${transfer.status}`}>{transfer.status === "completed" ? <CheckIcon /> : <UploadIcon />}</div><div className="transfer-copy"><div><strong>{transfer.name}</strong><span>{transfer.status}</span></div><div className="transfer-track"><span style={{ width: `${transfer.progress}%` }} /></div><small>{formatBytes(transfer.size)}{transfer.error ? ` · ${transfer.error}` : ` · ${transfer.progress}%`}</small></div><div className="transfer-actions">{["preparing", "uploading", "verifying"].includes(transfer.status) ? <button className="secondary" onClick={() => { void onCancel(transfer); }}>Cancel</button> : null}{["failed", "cancelled"].includes(transfer.status) ? <button className="secondary" onClick={() => { void onRetry(transfer); }}>Retry</button> : null}</div></article>)}{!transfers.length ? <div className="empty-state compact"><UploadIcon /><h3>No transfers yet</h3><p>Uploads and downloads will appear here with resumable progress.</p></div> : null}</div></section>;
}

function ActivityView({ events }: { events: ActivityEvent[] }) {
  return <section className="content-view"><div className="view-heading"><div><p className="eyebrow">Account audit</p><h1>Recent activity</h1></div></div><div className="timeline">{events.map((event) => <article key={event.id}><span /><div><strong>{activityLabel(event.action)}</strong><p>{event.targetName}</p></div><time>{new Date(event.createdAt).toLocaleString()}</time></article>)}</div></section>;
}

function SettingsView({ health, busy, onRefresh }: { health: StorageHealth | null; busy: boolean; onRefresh: () => void }) {
  const [deviceList, setDeviceList] = useState<Device[]>([]);
  const [currentDeviceId, setCurrentDeviceId] = useState("");
  const [deviceError, setDeviceError] = useState("");
  const [revoking, setRevoking] = useState("");
  useEffect(() => {
    void refreshDevices();
  }, []);

  async function refreshDevices() {
    try {
      const result = await getDevices();
      setDeviceList(result.devices);
      setCurrentDeviceId(result.currentDeviceId);
      setDeviceError("");
    } catch (reason) {
      setDeviceError(humanError(messageFor(reason)));
    }
  }

  async function handleRevoke(device: Device) {
    if (!window.confirm(`Revoke “${device.label}”? It will need to sign in again.`)) return;
    setRevoking(device.id);
    try {
      await revokeDevice(device.id);
      await refreshDevices();
    } catch (reason) {
      setDeviceError(humanError(messageFor(reason)));
    } finally {
      setRevoking("");
    }
  }

  const checks = [
    ["Gateway API", health?.gateway === "healthy", "Account and metadata service"],
    ["User session", health?.authenticated, "Bearer session accepted"],
    ["Object listing", health?.readAccess, "Storage read capability"],
    ["Object writes", health?.writeAccess, "Storage upload capability"],
  ] as const;
  return <section className="content-view"><div className="view-heading"><div><p className="eyebrow">Independent infrastructure</p><h1>Connection</h1></div><button className="primary" disabled={busy} onClick={onRefresh}>{busy ? "Checking…" : "Run health check"}</button></div><div className="settings-grid"><article className="connection-card"><div className="provider-mark">DO</div><div><p className="eyebrow">Configured storage adapter</p><h2>{health?.provider === "mock" ? "Local mock object store" : "DigitalOcean Spaces"}</h2><p>The gateway issues short-lived multipart and download requests. Provider credentials stay on the Knowledge Dump Gateway.</p></div><span className={`large-status ${health?.providerReachable ? "healthy" : "offline"}`}>{health?.providerReachable ? "Healthy" : "Unavailable"}</span></article><article className="health-checks"><div className="section-heading"><h3>Service checks</h3><span>{health ? `${health.latencyMs} ms` : "Not checked"}</span></div>{checks.map(([label, passing, detail]) => <div className="health-row" key={label}><span className={passing ? "pass" : "fail"}>{passing ? <CheckIcon /> : <CloseIcon />}</span><div><strong>{label}</strong><p>{detail}</p></div><i>{passing ? "Ready" : "Check"}</i></div>)}</article><article className="xdg-card"><p className="eyebrow">Ubuntu workstation contract</p><h3>XDG-native local state</h3><code>$XDG_CONFIG_HOME/knowledge-dump</code><code>$XDG_DATA_HOME/knowledge-dump</code><code>$XDG_CACHE_HOME/knowledge-dump</code><code>$XDG_STATE_HOME/knowledge-dump</code><p>Refresh tokens move to the Ubuntu keyring before production desktop release.</p></article><article className="device-card"><div className="section-heading"><div><p className="eyebrow">Account security</p><h3>Authorized workstations</h3></div><span>{deviceList.filter((device) => device.status === "active").length} active</span></div>{deviceError ? <p className="inline-error">{deviceError}</p> : null}<div className="device-list">{deviceList.map((device) => <div className="device-row" key={device.id}><div className={`device-mark ${device.status}`}><CloudIcon /></div><div><strong>{device.label}</strong><p>{device.platform} · Last used {relativeTime(device.lastSeenAt)}</p></div><span>{device.id === currentDeviceId ? "This device" : device.status}</span><button className="secondary" disabled={device.id === currentDeviceId || device.status !== "active" || revoking === device.id} onClick={() => { void handleRevoke(device); }}>{revoking === device.id ? "Revoking…" : "Revoke"}</button></div>)}</div></article></div></section>;
}

function NewFolderModal({ parentId, onClose, onCreated }: { parentId: string | null; onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await createFolder(name, parentId);
      onCreated();
    } catch (reason) {
      setError(humanError(messageFor(reason)));
    } finally {
      setBusy(false);
    }
  }
  return <div className="modal-backdrop" onMouseDown={onClose}><form className="modal-card" onSubmit={submit} onMouseDown={(event) => event.stopPropagation()}><button type="button" className="modal-close" onClick={onClose}><CloseIcon /></button><div className="modal-icon"><FolderIcon /></div><p className="eyebrow">Organize this dump</p><h2>New folder</h2><label>Folder name<input autoFocus value={name} onChange={(event) => setName(event.target.value)} placeholder="Project references" required /></label>{error ? <p className="inline-error">{error}</p> : null}<button className="primary wide" disabled={busy}>{busy ? "Creating…" : "Create folder"}</button></form></div>;
}

function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function relativeTime(value: string): string {
  const seconds = Math.max(1, Math.round((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function activityLabel(action: string): string {
  return ({ file_uploaded: "Uploaded", file_downloaded: "Downloaded", folder_created: "Created folder", file_archived: "Archived", file_active: "Restored", file_deleted: "Deleted", file_updated: "Updated", upload_started: "Started upload", upload_aborted: "Cancelled upload", upload_expired: "Expired upload", workspace_seeded: "Workspace prepared" } as Record<string, string>)[action] || action.replaceAll("_", " ");
}

function initials(value: string): string {
  return value.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
}

function messageFor(reason: unknown): string {
  return reason instanceof Error ? reason.message : typeof reason === "string" ? reason : "unknown_error";
}

function humanError(value: string): string {
  const known: Record<string, string> = {
    credentials_invalid: "That email and password were not accepted.",
    authentication_required: "Your session expired. Sign in again.",
    refresh_token_invalid: "Your session expired. Sign in again.",
    device_revoked: "This workstation was revoked. Clear its local device registration before signing in again.",
    quota_bytes_exceeded: "This upload exceeds the workspace storage quota.",
    quota_objects_exceeded: "This workspace has reached its file-count quota.",
    upload_part_etag_missing: "The storage provider did not expose the part receipt. Check the Space CORS policy.",
    upload_source_mismatch: "The selected file no longer matches this resumable upload.",
    upload_expired: "This upload expired. Retry it to start a new transfer.",
    upload_not_active: "This transfer can no longer be resumed. Retry it as a new upload.",
    storage_provider_error: "The object storage provider could not complete this operation.",
    download_failed: "The file could not be downloaded from object storage.",
    folder_not_empty: "Move or remove the files in this folder first.",
    native_desktop_required: "Open Knowledge Dump through its native desktop application to access local Codex files.",
    codex_source_not_found: "The selected Codex home does not exist or cannot be read.",
    codex_collection_not_found: "No Knowledge Dump Codex collection was found at that path.",
    codex_collection_overlaps_source: "The backup collection cannot be stored inside the active Codex home.",
    codex_restore_active_home_forbidden: "Test restore cannot overwrite or overlap the active Codex home.",
    codex_restore_destination_exists: "Choose a new restore destination that does not already exist.",
    codex_restore_destination_overlaps_collection: "The restore destination cannot overlap the backup collection.",
    Failed_to_fetch: "The Knowledge Dump Gateway could not be reached.",
  };
  return known[value] || value.replaceAll("_", " ");
}
