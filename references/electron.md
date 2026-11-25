# Electron adaptation

## Defaults

Use a supported Electron version selected when building; lock it and the packaging tool. The scaffold intentionally does not hard-code a version that will become obsolete. Its dependencies are not installed until explicitly requested.

The generated app uses app://bundle/ as a stable local origin, not file:// or the original host URL. Paths are resolved within the bundled web root, symlink escapes are rejected, MIME types are provided, and requests are read-only. The simple handler reads entire files into memory and does not implement range requests or SPA history fallback: extend it deliberately if required by large media or client-side routing.

Node integration is off, context isolation and renderer sandbox are on, webviews are disabled, and no preload is provided. Permissions, popups, remote navigation and remote renderer requests are denied by default. When the app needs a permission, allow that one permission for the `app://bundle` origin only, by checking the permission name and requesting URL in both session permission handlers. The CSP allows inline code for compatibility with recovered apps but forbids eval and remote scripts. Tighten inline code to hashes/nonces where possible. WASM compilation and worker behavior need explicit testing; enabling WASM may require a narrowly reviewed CSP change.

This is a secure starting point, not a complete security audit or OS network sandbox. Use OS-level network controls during offline tests. Electron tooling/updaters and future main-process code may have independent network behavior.

## Allowances apps commonly need

Add only the rows the app's code actually uses, in the generated project's `main.cjs`, never in the template. Permissions go in both session permission handlers, checked against the permission name and the `app://bundle` origin.

| App does this | Look for | Add |
| --- | --- | --- |
| Compiles WebAssembly | `WebAssembly.` | `'wasm-unsafe-eval'` in CSP `script-src` (not `'unsafe-eval'`) |
| Copies or pastes images or text via the async API | `navigator.clipboard.` | `clipboard-read`, `clipboard-sanitized-write` permissions |
| Lists installed fonts | `queryLocalFonts` | `local-fonts` permission |
| Shows notifications | `Notification` | `notifications` permission |
| Fetches a `blob:` or `data:` URL | `fetch(` on object URLs | `blob:` / `data:` in CSP `connect-src` |

Workers created from `blob:` URLs, object-URL downloads through `<a download>`, `<input type=file>`, IndexedDB and localStorage need nothing. An `<a download>` click opens Electron's save dialog.

Embedded or separate `.wasm` needs no porting: it is copied with the other assets and runs as it did in the original.

## Native integration

Prefer browser APIs first. If IPC is needed:
- Add a sandbox-compatible preload exposing individual methods via contextBridge.
- Never expose ipcRenderer, require, generic shell commands, unrestricted paths, or arbitrary fetch.
- Validate sender frame/origin, arguments, resource size and file types in the main process.
- Choose file destinations through native dialogs. Limit operations to approved paths.
- Handle permission denial and cancellation visibly.

Keep remote pages out of privileged windows. Never add webSecurity:false, sandbox:false, nodeIntegration:true, arbitrary shell.openExternal, certificate bypasses, or blanket permission grants as compatibility fixes.

## Persistence and distribution

Set a unique reverse-domain app ID and stable package name. Chromium storage and userData are distinct from the original host's profile. Version any approved migrations. Review telemetry, service workers and update mechanisms, which may retain old origin assumptions.

Package only the allowlisted app files. Keep source provenance, captures and audits outside the distributable. Audit web assets for secrets and private content; excluded file names alone are not a sufficient check. Preserve licensing/notice files in packaged assets as appropriate.

Pass the original bundle's `.icns` to `scaffold --icon`; it lands in `build/icon.icns`, which electron-builder uses and does not package as an asset. Deploy with `pack.py deploy`, which names the copy `<Name>-Packed.app` beside the original. In development mode macOS attributes notifications and the Dock icon to Electron; judge those from the packed build.

Test both development mode and packaged ASAR builds on each target OS. A successful build does not prove runtime compatibility. macOS signing/notarization and Windows signing require additional setup and credentials; don't claim a distributable is signed unless verified. Independent packaging means owning future Electron and dependency security updates.
