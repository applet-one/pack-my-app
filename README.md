# pack-my-app

An agent skill that turns apps built with Claude into independent Electron desktop apps.

Point it at an installed Claude app, for example `~/Applications/Claude Apps/Focus.app`. The skill recognises that the bundle is only a launcher, fetches the app's real source from its artifact, adapts it to run without Claude, builds it, and puts `Focus-Packed.app` next to the original. The original is never modified.

It also works on other web apps (a URL or a build directory), but Claude-built apps are the primary purpose.

**Independent** means it does not need Claude to run. **Offline** is a separate, tested capability. Features that depend on Claude's servers may need replacements or stay online.

## Contents

- `SKILL.md`: the workflow: identify, fetch, inventory, adapt, build, deploy, verify.
- `scripts/pack.py`: dependency-free helpers (`inspect`, `audit`, `scaffold`, `deploy`).
- `templates/electron/main.cjs`: local protocol, sandboxed renderer, no native bridge, network and permissions denied by default.
- `references/`: recovery guidance, Electron security, verification checklist and report template.
- `tests/`: helper tests.

## Use

Install this directory as a skill in your agent, then ask, for example:

```text
Pack this app: ~/Applications/Claude Apps/Focus.app
```

Fetching the source needs an agent that can read the user's Claude artifacts. Without that, supply the artifact's exported source.

## Helpers

Python 3.10+ required. No third-party Python dependencies.

```sh
python3 scripts/pack.py inspect "/path/to/Name.app"
python3 scripts/pack.py audit /path/to/web > /path/to/audit.json
python3 scripts/pack.py scaffold /path/to/web /path/to/desktop \
  --name 'My App' --slug my-app --app-id com.example.myapp --icon /path/to/app.icns
python3 scripts/pack.py deploy /path/to/desktop/release/mac-arm64/My\ App.app "/path/to/Name.app"
python3 -m unittest discover -s tests -v
```

- `inspect` reads the bundle's `Info.plist` and the matching entry in Claude's install registry, and prints the artifact link, icon path and deploy target. It does not launch anything.
- `audit` is an advisory static scan for remote URLs, missing files and host integrations.
- `scaffold` needs a source containing `index.html` and a destination that does not exist. Symlinks are rejected. `.git`, `node_modules`, `__pycache__` and `.DS_Store` are omitted; everything else is copied, so check the source for secrets first.
- `deploy` copies a built app to `<Name>-Packed.app` beside the original. It refuses without write permission, and replaces an earlier packed copy only with `--replace`.

The helpers do not install dependencies or execute app code. Building requires Node.js, npm, and a download of Electron.

## Known limitations

- macOS only for installed bundles and deployment.
- The helpers do not fetch artifacts themselves; the agent does, with its artifact tool.
- Apps that use Claude's runtime (`window.claude.*`: shared data, asking Claude, viewer identity) need app-specific adapters, and server-backed features cannot be made offline.
- Asset scanning is heuristic; it does not parse all JavaScript or prove completeness.
- No native bridge, updater, notarization, data migration, range requests or SPA fallback by default. Builds are ad-hoc signed at most.
- Offline verification requires running the packed app and exercising its workflows.

## Not yet supported (TODO)

- **Apps that need native access.** An app whose manifest asks for `full-access` and that calls Claude's `desktop` runtime for a shell, command execution or file access (`pty`, `childProcess`, `fs`) has no browser fallback. Packing it needs a native bridge: a preload exposing only the methods the app calls, main-process handlers, and the `node-pty` native module. The bridge then replaces Claude's permission prompt as the only gate on that access, so it also needs a consent step and a rule for apps the user did not write. First case seen: Tern Terminal (third-party artifact; analysed, not packed).
