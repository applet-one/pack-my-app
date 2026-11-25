# Recovery and provenance

## Claude artifact apps

An app installed from Claude (typically under `~/Applications/Claude Apps/`) is a launcher: a small executable, an icon and an `Info.plist`. It contains no app code. Signs: `ClaudeArtifactAppId` and `ElectronAppShimHostPath` keys in `Info.plist`, and a bundle of well under 1 MB apart from the icon.

`scripts/pack.py inspect` resolves it: the `ClaudeArtifactAppId` install ID is looked up in `~/Library/Application Support/Claude/artifact-apps-installed.json`, whose matching entry holds the artifact UUID. The source is then at `https://claude.ai/code/artifact/<uuid>`. Read only that entry; never other apps' records, conversations or profiles.

Fetch through the artifact tool as the signed-in owner: the page, the list of published files, then each file by path. Fetching the page by path `index.html` saves exact bytes. Note the version identifier and declared runtime capabilities. A page with no declared capabilities and no `window.claude` use is plain browser code.

Do not launch the original to capture it, and do not dig through Claude's caches when the artifact is readable.

## Other inputs, in order of preference

1. Original repository or export, including license and lockfiles.
2. Deployed static build downloaded through an authorized session.
3. Explicitly captured network resources (DevTools save/HAR with content).
4. Narrowly scoped browser-cache recovery as a last resort.

A cache may omit lazy-loaded files, evicted assets, HTTP redirects, fonts, source maps, workers, WASM, and API responses. A JavaScript bundle is delivered source, not necessarily the original development source. Do not claim complete recovery without runtime evidence.

## Other installed wrappers

For a bundle that is not a Claude artifact app, inspect Contents/Info.plist, Resources and executable metadata without launching it. Determine whether it includes its implementation or points at a host runtime and remote content.

For Chromium/Electron cache recovery, determine the actual cache format and stream boundaries. Do not split arbitrary binary files at a gzip marker and assume the rest is one response. Handle content encoding and redirects explicitly, validate decompression completion, record the resource URL and original cache file, and compare output content type/signature. Skip unsupported encodings with a documented gap. Never alter a live cache. Prefer a read-only snapshot if the browser is running.

Chromium cache formats vary. No universal decoder is included in this initial skill; use a reviewed decoder or targeted recovery routine appropriate to the observed version. Recovered files from earlier ad hoc sessions need provenance and integrity checks too.

## Collection manifest

For each resource record:
- Local path, source origin and sanitized path; omit credentials and sensitive query values.
- Timestamp, retrieval method and SHA-256.
- Encoding, status, MIME type and redirect destination where known.
- Whether original, adapted, missing, or substituted.

Keep raw captures outside the packaged web root. HARs often contain cookies, authorization headers, request bodies, signed URLs and private API data: sanitize them before retention/sharing and never include them in the app.

Reject path traversal and symlinks when writing downloaded resources. Keep distinct versions separate rather than mixing files from different deployments. Verify that alleged image files are images rather than redirects/login/error pages.

## Runtime inventory

Review script/link/src attributes, CSS url(), dynamic imports, fetch, XHR, workers, service workers and WASM. Exercise file dialogs, fonts, samples, plugins, export formats and infrequently used tools. Compare observed resources with bundled assets. Preserve attribution and third-party notices.
