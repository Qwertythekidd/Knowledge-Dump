# XDG filesystem contract

Knowledge Dump follows freedesktop XDG conventions from its first release.

```text
$XDG_CONFIG_HOME/knowledge-dump/
  settings.toml

$XDG_DATA_HOME/knowledge-dump/
  catalog.db
  mock-objects/
  downloads/
  local-collections/  # default local collection parent

$XDG_CACHE_HOME/knowledge-dump/
  previews/
  chunks/

$XDG_STATE_HOME/knowledge-dump/
  logs/
  transfers/
  sync-cursor.json
```

When an XDG variable is unset, the application uses the conventional directory
beneath the current Linux user's home directory.

Configuration contains only non-secret settings such as gateway URL, device
label, display preferences, and cache limits. Authentication tokens and future
encryption keys belong in the Ubuntu Secret Service keyring.

Package code is immutable beneath `/usr/lib/knowledge-dump`. Runtime data must
never be written beneath `/usr`, the source checkout, or the installed package.

The Codex storage interface permits an explicit absolute collection path so a
user can place the collection on an encrypted secondary or removable drive.
When no path is chosen, Knowledge Dump suggests the XDG data location above.
