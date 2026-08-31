import { useEffect, useRef, useState } from "react";
import type { Account, ActivityEvent, CloudFile, StorageHealth } from "@knowledge-dump/protocol";

import {
  activity as getActivity,
  createFolder,
  currentGatewayUrl,
  downloadFile,
  files as getFiles,
  login,
  logout,
  purgeFile,
  registerUpload,
  renameFile,
  savedToken,
  saveGatewayUrl,
  session,
  setArchived,
  storageHealth,
} from "./api";
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

type View = "files" | "recent" | "archived" | "transfers" | "settings";
type DisplayMode = "grid" | "list";
type TransferStatus = "queued" | "uploading" | "completed" | "failed";

interface Transfer {
  id: string;
  name: string;
  size: number;
  progress: number;
  status: TransferStatus;
  error?: string;
}

const DEMO_EMAIL = "demo@knowledge-dump.local";

export default function App() {
  const [account, setAccount] = useState<Account | null>(null);
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
      .catch(() => window.sessionStorage.removeItem("knowledge-dump.session-token"))
      .finally(() => active && setBooting(false));
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!account || view === "settings" || view === "transfers" || view === "recent") return;
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
    }));
    setTransfers((current) => [...queue, ...current]);

    for (let index = 0; index < selected.length; index += 1) {
      const file = selected[index];
      const transfer = queue[index];
      updateTransfer(transfer.id, { status: "uploading", progress: 8 });
      try {
        for (const progress of [22, 41, 64, 82]) {
          await delay(90);
          updateTransfer(transfer.id, { progress });
        }
        await registerUpload(file, currentFolder?.id || null);
        updateTransfer(transfer.id, { status: "completed", progress: 100 });
      } catch (reason) {
        updateTransfer(transfer.id, { status: "failed", error: messageFor(reason) });
      }
    }
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
  if (!account) return <LoginScreen onAuthenticated={(nextAccount, nextHealth) => { setAccount(nextAccount); setHealth(nextHealth); }} />;

  return (
    <div className="app-shell">
      <Sidebar account={account} view={view} health={health} onView={(next) => { setView(next); if (next !== "files") setFolderTrail([]); }} onLogout={handleLogout} />

      <main className="workspace">
        <header className="topbar">
          <div className="search-box"><SearchIcon /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search this folder" disabled={view !== "files" && view !== "archived"} /></div>
          <button className={`health-chip ${health?.providerReachable ? "healthy" : "offline"}`} onClick={() => { setView("settings"); void refreshHealth(); }}>
            <span className="pulse-dot" />
            {health?.providerReachable ? "Storage online" : "Check storage"}
          </button>
          <div className="avatar" title={account.email}>{initials(account.displayName)}</div>
        </header>

        {error ? <div className="error-banner"><span>{humanError(error)}</span><button onClick={() => setError("")}><CloseIcon /></button></div> : null}

        {view === "settings" ? (
          <SettingsView health={health} busy={healthBusy} onRefresh={refreshHealth} />
        ) : view === "transfers" ? (
          <TransfersView transfers={transfers} />
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
          <small>{health ? `${formatBytes(health.quotaBytes)} available in development` : "Health check required"}</small>
        </div>
      </aside>

      <input ref={fileInput} className="visually-hidden" type="file" multiple onChange={(event) => { void handleUpload(event.target.files); event.target.value = ""; }} />
      {folderModal ? <NewFolderModal parentId={currentFolder?.id || null} onClose={() => setFolderModal(false)} onCreated={async () => { setFolderModal(false); await refreshFiles(); }} /> : null}
    </div>
  );
}

function LoginScreen({ onAuthenticated }: { onAuthenticated: (account: Account, health: StorageHealth) => void }) {
  const [email, setEmail] = useState(DEMO_EMAIL);
  const [password, setPassword] = useState("knowledge");
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
        <small>Mock account: {DEMO_EMAIL} / knowledge</small>
      </form>
    </section>
  </main>;
}

function Sidebar({ account, view, health, onView, onLogout }: { account: Account; view: View; health: StorageHealth | null; onView: (view: View) => void; onLogout: () => void }) {
  const navigation: Array<[View, string, React.ReactNode]> = [
    ["files", "My dump", <CloudIcon />],
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

function TransfersView({ transfers }: { transfers: Transfer[] }) {
  return <section className="content-view"><div className="view-heading"><div><p className="eyebrow">Local transfer queue</p><h1>Transfers</h1></div></div><div className="transfer-list">{transfers.map((transfer) => <article key={transfer.id}><div className={`transfer-icon ${transfer.status}`}>{transfer.status === "completed" ? <CheckIcon /> : <UploadIcon />}</div><div className="transfer-copy"><div><strong>{transfer.name}</strong><span>{transfer.status}</span></div><div className="transfer-track"><span style={{ width: `${transfer.progress}%` }} /></div><small>{formatBytes(transfer.size)}{transfer.error ? ` · ${transfer.error}` : ` · ${transfer.progress}%`}</small></div></article>)}{!transfers.length ? <div className="empty-state compact"><UploadIcon /><h3>No transfers yet</h3><p>Uploads and downloads will appear here with resumable progress.</p></div> : null}</div></section>;
}

function ActivityView({ events }: { events: ActivityEvent[] }) {
  return <section className="content-view"><div className="view-heading"><div><p className="eyebrow">Account audit</p><h1>Recent activity</h1></div></div><div className="timeline">{events.map((event) => <article key={event.id}><span /><div><strong>{activityLabel(event.action)}</strong><p>{event.targetName}</p></div><time>{new Date(event.createdAt).toLocaleString()}</time></article>)}</div></section>;
}

function SettingsView({ health, busy, onRefresh }: { health: StorageHealth | null; busy: boolean; onRefresh: () => void }) {
  const checks = [
    ["Gateway API", health?.gateway === "healthy", "Account and metadata service"],
    ["User session", health?.authenticated, "Bearer session accepted"],
    ["Object listing", health?.readAccess, "Storage read capability"],
    ["Object writes", health?.writeAccess, "Storage upload capability"],
  ] as const;
  return <section className="content-view"><div className="view-heading"><div><p className="eyebrow">Independent infrastructure</p><h1>Connection</h1></div><button className="primary" disabled={busy} onClick={onRefresh}>{busy ? "Checking…" : "Run health check"}</button></div><div className="settings-grid"><article className="connection-card"><div className="provider-mark">DO</div><div><p className="eyebrow">Configured storage adapter</p><h2>{health?.provider === "mock" ? "Local mock object store" : "DigitalOcean Spaces"}</h2><p>The production adapter will issue short-lived presigned requests. Provider credentials stay on the Knowledge Dump Gateway.</p></div><span className={`large-status ${health?.providerReachable ? "healthy" : "offline"}`}>{health?.providerReachable ? "Healthy" : "Unavailable"}</span></article><article className="health-checks"><div className="section-heading"><h3>Service checks</h3><span>{health ? `${health.latencyMs} ms` : "Not checked"}</span></div>{checks.map(([label, passing, detail]) => <div className="health-row" key={label}><span className={passing ? "pass" : "fail"}>{passing ? <CheckIcon /> : <CloseIcon />}</span><div><strong>{label}</strong><p>{detail}</p></div><i>{passing ? "Ready" : "Check"}</i></div>)}</article><article className="xdg-card"><p className="eyebrow">Ubuntu workstation contract</p><h3>XDG-native local state</h3><code>$XDG_CONFIG_HOME/knowledge-dump</code><code>$XDG_DATA_HOME/knowledge-dump</code><code>$XDG_CACHE_HOME/knowledge-dump</code><code>$XDG_STATE_HOME/knowledge-dump</code><p>Authentication secrets move to the Ubuntu keyring in the production client.</p></article></div></section>;
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
  return ({ file_uploaded: "Uploaded", folder_created: "Created folder", file_archived: "Archived", file_active: "Restored", file_deleted: "Deleted", file_updated: "Updated", workspace_seeded: "Workspace prepared" } as Record<string, string>)[action] || action.replaceAll("_", " ");
}

function initials(value: string): string {
  return value.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
}

function messageFor(reason: unknown): string {
  return reason instanceof Error ? reason.message : "unknown_error";
}

function humanError(value: string): string {
  const known: Record<string, string> = {
    credentials_invalid: "That email and password were not accepted.",
    authentication_required: "Your session expired. Sign in again.",
    folder_not_empty: "Move or remove the files in this folder first.",
    Failed_to_fetch: "The Knowledge Dump Gateway could not be reached.",
  };
  return known[value] || value.replaceAll("_", " ");
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}
