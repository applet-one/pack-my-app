# Verification checklist

Record environment, OS, Electron version, capture/build version and exact results. Use synthetic fixtures rather than private documents. Do not execute unreviewed recovered code just to inspect it.

## Before execution

- Inventory assets, redirects, dynamic code, services and host API usage.
- Inspect npm scripts, dependencies and recovered code for unexpected behavior.
- Review licensing and remove credentials, cookies, tokens and private data.
- Inspect the Electron main/preload security boundary and CSP.

## Clean-profile desktop tests

Use a disposable profile or test user; never overwrite an existing app profile. Verify that the app does not rely on the original host's cookies or cached responses.

Test in development and from the packaged app:
- Cold start, reload, quit and restart.
- All entry points, themes, fonts, icons and images.
- Agreed core workflows: import, edit, undo/redo, save, export and reopen.
- Lazy tools, sample documents, large files and supported formats.
- Storage persistence after restart; no assumption that original-host data migrated.
- Permissions denied, file-dialog cancellation and invalid input.
- Notification and audio behavior where applicable.
- External links/popups, attempted webviews and navigation cannot acquire privileges.
- Unknown protocol hosts, encoded traversal, missing assets and unsupported methods fail safely.

## Driving the packed app

Observing a desktop window by hand is slow and unrepeatable. Launch the deployed binary directly with a debugging port and a disposable profile, then drive the page over the Chrome DevTools Protocol:

```sh
"/path/Name-Packed.app/Contents/MacOS/Name" --remote-debugging-port=9333 --user-data-dir=/path/to/scratch/profile &
```

Fetch `http://127.0.0.1:9333/json`, open the page target's `webSocketDebuggerUrl`, and use `Runtime.evaluate` (with `awaitPromise` and `userGesture`) to click controls and read state. Enable `Runtime`, `Log` and `Network`, then `Page.reload`, to collect console errors, exceptions, CSP violations and every request URL from start-up. `Page.captureScreenshot` gives an image to look at. Node 22+ has `fetch` and `WebSocket` built in, so no dependencies are needed.

Check at least: the URL is `app://bundle/index.html`; the app's own UI is showing, not an install or landing page; no request leaves `app://bundle`, `data:` or `blob:`; `typeof require` and `typeof process` are `undefined`; a remote `fetch` is rejected; granted permissions are exactly the intended ones (`navigator.permissions.query`).

Traps:

- Code run through `Runtime.evaluate` is exempt from the CSP's `eval` block, including scripts it injects synchronously. To test `eval`, schedule it with `setTimeout` and read the result in a later call.
- Wait for the page target before evaluating; an immediate call can run before the document exists.
- `queryLocalFonts` and some other APIs reject while the window is not visible. That is the test setup, not the app.
- To test a long timer, shift `Date.now` in the page rather than waiting. Say so in the report.
- A save dialog cannot be dismissed over the protocol. Either observe the generated file by wrapping `HTMLAnchorElement.prototype.click`, or leave the dialog step for the user; report which.
- Quit the instance and delete the scratch profile afterwards. Relaunch on the same profile first if testing persistence.

This shows what the page does. It does not show a notification banner, play sound to you, or prove OS-level isolation.

## Network isolation

Close the original host and disable external networking using OS-level controls. The shell's renderer request blocker is useful defense, not independent proof. Inspect DevTools console/network for attempted remote calls, missing requests, CSP violations and runtime errors. Local static pages can still hide unused dependencies: exercise every supported feature.

Document intentionally online features separately. Test their failure mode offline and verify they don't prevent local workflows. Never claim fully offline when AI, authentication, sync or storage still requires a service.

## Result labels

- **Recovered only**: files collected; app not executed.
- **Scaffolded**: shell generated; compatibility unverified.
- **Standalone, online features remain**: works without the original host but uses named services.
- **Offline core verified**: listed core workflows pass under network isolation; remaining gaps explicit.
- **Offline scope verified**: all agreed supported workflows pass under network isolation on named targets. Not a claim about every possible feature or OS.

Static inventory, JS syntax checks and unit tests alone never establish desktop/offline success.
