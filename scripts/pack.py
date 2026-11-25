#!/usr/bin/env python3
"""Dependency-free, non-executing helpers for the pack-my-app skill."""
import argparse
import hashlib
import json
import os
import plistlib
import re
import shutil
from pathlib import Path
from urllib.parse import unquote, urlsplit

TEXT = {'.html', '.htm', '.css', '.js', '.mjs', '.json', '.svg', '.webmanifest'}
MARKERS = {
    'network': r'\b(?:fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon)\b',
    'host_bridge': r'\b(?:claude|electron|ipcRenderer|webkit\.messageHandlers)\b',
    'dynamic_resources': r'\b(?:import\s*\(|Worker\s*\(|SharedWorker\s*\(|serviceWorker|WebAssembly)',
    'storage': r'\b(?:localStorage|sessionStorage|indexedDB)\b',
    'native_features': r'\b(?:Notification|showOpenFilePicker|showSaveFilePicker|clipboard|mediaDevices)\b',
}
# Advisory only: this deliberately does not attempt to parse arbitrary JavaScript.
RESOURCES = re.compile(
    r'''(?:\b(?:src|href)\s*=\s*["']([^"']+)["']'''
    r'''|url\(\s*["']?([^\s)"']+)'''
    r'''|\b(?:import\s*\(|fetch\s*\(|(?:Shared)?Worker\s*\()\s*["']([^"']+)["']'''
    # Static imports: only explicit paths, so bare specifiers and prose are ignored.
    r'''|\b(?:import|from)\s*["'](\.{0,2}/[^"']+)["'])''', re.I)
SRCSET = re.compile(r'''\b(?:image)?srcset\s*=\s*["']([^"']+)["']''', re.I)
URLS = re.compile(r'''https?://[^\s<>"'`\\)]+''')
# XML namespace/DTD identifiers, not fetched resources.
NAMESPACE = re.compile(r'http://www\.w3\.org/(?:\d{4}|TR|XML)/')
EXCLUDED = {'node_modules', '.git', '.DS_Store', '__pycache__'}
# Claude desktop's record of installed artifact apps: install ID -> artifact UUID.
REGISTRY = Path.home() / 'Library' / 'Application Support' / 'Claude' / 'artifact-apps-installed.json'
UUID = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}')
PACKED = '-Packed'
# A literal worth checking: path characters only, and either an explicit ./ ../ / prefix,
# a file extension, or a trailing slash. Filters minified-code fragments and MIME types.
PLAUSIBLE = re.compile(r'(?:\.{0,2}/[\w@%~.\-/]*|[\w@%~.\-/]*(?:\.\w{1,8}|/))')


def files(root):
    for p in sorted(root.rglob('*')):
        if any(part in EXCLUDED for part in p.relative_to(root).parts):
            continue
        if p.is_symlink():
            raise ValueError(f'Refusing symlink: {p}')
        if p.is_file():
            yield p


def public_url(value):
    """Never include URL credentials, queries or fragments in generated reports."""
    try:
        u = urlsplit(value)
        host = u.hostname or ''
        if ':' in host:
            host = '[' + host + ']'
        if u.port:
            host += ':' + str(u.port)
        return f'{u.scheme}://{host}{u.path}'
    except ValueError:
        return '<invalid-url>'


def audit(root):
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Web root must be a directory')
    entries, urls, missing, indicators = [], set(), [], []
    for p in files(root):
        data = p.read_bytes()
        rel = p.relative_to(root).as_posix()
        entries.append({'path': rel, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        if p.suffix.lower() not in TEXT:
            continue
        text = data.decode('utf-8', errors='replace')
        urls.update(public_url(m.group()) for m in URLS.finditer(text) if not NAMESPACE.match(m.group()))
        for category, pattern in MARKERS.items():
            hits = list(re.finditer(pattern, text))
            if hits:
                indicators.append({'path': rel, 'category': category, 'matches': len(hits)})
        def check(value):
            if '${' in value or '{{' in value:  # Template placeholder, not a literal path.
                return
            try:
                u = urlsplit(value)
            except ValueError:
                return
            if u.netloc and not u.scheme:  # Protocol-relative remote URL.
                shown = public_url('https:' + value)
                urls.add(shown[len('https:'):] if shown.startswith('https://') else shown)
                return
            if u.scheme or u.netloc or not u.path or not PLAUSIBLE.fullmatch(u.path):
                return
            candidate = (root if u.path.startswith('/') else p.parent) / unquote(u.path).lstrip('/')
            candidate = candidate.resolve()
            if not candidate.is_relative_to(root):
                missing.append({'file': rel, 'resource': u.path, 'reason': 'outside-web-root'})
            elif not candidate.exists():
                missing.append({'file': rel, 'resource': u.path, 'reason': 'not-found'})
            elif candidate.is_dir() and candidate != root:
                # The generated shell serves index.html only for the root, not subdirectories.
                missing.append({'file': rel, 'resource': u.path, 'reason': 'directory-not-served'})

        for m in RESOURCES.finditer(text):
            check(next(x for x in m.groups() if x is not None))
        for m in SRCSET.finditer(text):
            if 'data:' in m.group(1):  # data: URLs contain commas; skip rather than misparse.
                continue
            for part in m.group(1).split(','):
                if part.split():
                    check(part.split()[0])
    return {'warning': 'Advisory static scan only; not a parser or offline verification. URLs omit credentials, queries and fragments; URL paths may still be sensitive.',
            'files': entries, 'candidate_remote_urls': sorted(urls),
            'missing_literal_resources': missing, 'indicators': indicators}


def app_bundle(path):
    path = path.resolve(strict=True)
    if path.suffix != '.app' or not (path / 'Contents' / 'Info.plist').is_file():
        raise ValueError(f'Not a macOS .app bundle: {path}')
    return path


def packed_target(original):
    if original.stem.endswith(PACKED):
        raise ValueError('That bundle is already a packed app; point at the original')
    return original.parent / f'{original.stem}{PACKED}.app'


def inspect(bundle, registry=REGISTRY):
    """Read an installed bundle's metadata without launching it or touching other apps' records."""
    bundle = app_bundle(bundle)
    with (bundle / 'Contents' / 'Info.plist').open('rb') as f:
        info = plistlib.load(f)
    install_id = info.get('ClaudeArtifactAppId')
    icon = bundle / 'Contents' / 'Resources' / (Path(str(info.get('CFBundleIconFile') or 'app')).stem + '.icns')
    result = {
        'bundle': str(bundle),
        'name': info.get('CFBundleDisplayName') or info.get('CFBundleName') or bundle.stem,
        'bundle_id': info.get('CFBundleIdentifier'),
        'claude_artifact_app': bool(install_id),
        # A Claude artifact app bundle is a launcher: metadata and an icon, no app code.
        'launcher_only': bool(install_id or info.get('ElectronAppShimHostPath')),
        'host_app': info.get('ElectronAppShimHostPath'),
        'install_id': install_id,
        'artifact_uuid': None, 'artifact_url': None,
        'icon': str(icon) if icon.is_file() else None,
        'deploy_target': None, 'deploy_dir_writable': os.access(bundle.parent, os.W_OK),
        'notes': [],
    }
    try:
        target = packed_target(bundle)
        result['deploy_target'] = str(target)
        if target.exists():
            result['notes'].append('Deploy target already exists; deploy needs --replace.')
    except ValueError as exc:
        result['notes'].append(str(exc))
    if not install_id:
        result['notes'].append('No ClaudeArtifactAppId: not a Claude artifact app. Inspect the bundle contents for its implementation.')
        return result
    try:
        apps = json.loads(Path(registry).read_text()).get('apps', [])
        match = next((a for a in apps if isinstance(a, dict) and a.get('installId') == install_id), None)
    except (OSError, ValueError, AttributeError) as exc:
        result['notes'].append(f'Could not read Claude install registry: {exc}')
        return result
    uuid = (match or {}).get('artifactUuid')
    if isinstance(uuid, str) and UUID.fullmatch(uuid):
        result['artifact_uuid'] = uuid
        result['artifact_url'] = f'https://claude.ai/code/artifact/{uuid}'
        result['notes'].append('Fetch the app source from artifact_url; the bundle itself contains no app code.')
    else:
        result['notes'].append('Install ID not found in the Claude install registry; ask the user for the artifact link.')
    return result


def deploy(built, original, replace=False):
    """Copy a built app next to the original as '<Name>-Packed.app'. Never touches the original."""
    built, original = app_bundle(built), app_bundle(original)
    target = packed_target(original)
    if built == original or built == target:
        raise ValueError('Built app must be a separate bundle from the original and the deploy target')
    if not os.access(original.parent, os.W_OK):
        raise ValueError(f'No write permission for {original.parent}; packed app left at {built}')
    exists = target.exists() or target.is_symlink()
    if exists and not replace:
        raise ValueError(f'{target} already exists; pass --replace to replace that earlier packed copy')
    staging = original.parent / f'.{target.name}.incoming'
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(built, staging, symlinks=True)  # Bundles contain framework symlinks.
    if exists:
        target.unlink() if target.is_symlink() else shutil.rmtree(target)
    staging.rename(target)
    return target


def scaffold(source, dest, name, slug, app_id, icon=None):
    source = source.resolve(strict=True)
    dest = dest.resolve()
    if not source.is_dir() or not (source / 'index.html').is_file():
        raise ValueError('Source must be a directory containing index.html')
    if dest.exists():
        raise ValueError('Destination must not already exist')
    if dest.is_relative_to(source) or source.is_relative_to(dest):
        raise ValueError('Source and destination must not contain one another')
    if not re.fullmatch(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*', slug):
        raise ValueError('Slug must use lowercase letters, digits and single hyphens')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9-]*(?:\.[A-Za-z][A-Za-z0-9-]*)+', app_id):
        raise ValueError('App ID must be a reverse-domain identifier')
    # The name becomes file and folder names in packaged output on every target OS.
    if (not name or name != name.strip() or name.endswith('.') or len(name) > 100
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)):
        raise ValueError('Name must be 1-100 characters without < > : " / \\ | ? * or control '
                         'characters, surrounding whitespace, or a trailing dot')
    if icon is not None:
        icon = icon.resolve(strict=True)
        if icon.suffix != '.icns' or not icon.is_file():
            raise ValueError('Icon must be an .icns file')
    selected = list(files(source))  # Validate all paths before creating output.
    dest.mkdir(parents=True)
    for p in selected:
        out = dest / 'web' / p.relative_to(source)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, out)
    templates = Path(__file__).resolve().parent.parent / 'templates' / 'electron'
    shutil.copy2(templates / 'main.cjs', dest / 'main.cjs')
    if icon is not None:  # electron-builder picks up build/icon.icns; it is not packaged as an asset.
        (dest / 'build').mkdir()
        shutil.copy2(icon, dest / 'build' / 'icon.icns')
    package = {
        'name': slug, 'productName': name, 'version': '0.1.0', 'private': True,
        'description': f'Standalone desktop package for {name}', 'main': 'main.cjs',
        'scripts': {'start': 'electron .', 'pack': 'electron-builder --dir', 'dist': 'electron-builder'},
        'build': {'appId': app_id, 'productName': name,
                  'files': ['main.cjs', 'web/**/*', 'package.json'],
                  'asar': True, 'directories': {'output': 'release'}},
    }
    (dest / 'package.json').write_text(json.dumps(package, indent=2) + '\n')
    (dest / '.gitignore').write_text('node_modules/\nrelease/\n.DS_Store\n')
    (dest / 'ASSET-AUDIT.json').write_text(json.dumps(audit(source), indent=2) + '\n')
    (dest / 'README.md').write_text(
        '# ' + name + '\n\nGenerated by pack-my-app. Not yet verified offline.\n\n'
        'Review assets and main.cjs before executing. Install supported, explicitly selected versions:\n\n'
        '```sh\nnpm install --save-dev --save-exact electron@<version> electron-builder@<version>\n'
        'npm start\nnpm run pack\n```\n\n'
        'Commit package-lock.json. Remote requests and permissions are denied by default. '
        'Native integrations require reviewed, narrow IPC; no preload is provided by default. '
        'Audit licenses and secrets before distributing. Signing/notarization are not configured.\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    i = commands.add_parser('inspect', help='Identify an installed app bundle and its Claude artifact')
    i.add_argument('bundle', type=Path)
    i.add_argument('--registry', type=Path, default=REGISTRY, help=argparse.SUPPRESS)
    d = commands.add_parser('deploy', help="Copy a built app beside the original as '<Name>-Packed.app'")
    d.add_argument('built', type=Path)
    d.add_argument('original', type=Path)
    d.add_argument('--replace', action='store_true', help='Replace an earlier packed copy (never the original)')
    a = commands.add_parser('audit', help='Inventory assets and flag potential dependencies')
    a.add_argument('source', type=Path)
    s = commands.add_parser('scaffold', help='Copy web assets and create a secure Electron shell')
    s.add_argument('source', type=Path)
    s.add_argument('destination', type=Path)
    s.add_argument('--name', required=True)
    s.add_argument('--slug', required=True)
    s.add_argument('--app-id', required=True)
    s.add_argument('--icon', type=Path, help='.icns icon, e.g. the one reported by inspect')
    args = parser.parse_args()
    try:
        if args.command == 'audit':
            print(json.dumps(audit(args.source), indent=2))
        elif args.command == 'inspect':
            print(json.dumps(inspect(args.bundle, args.registry), indent=2))
        elif args.command == 'deploy':
            print(f'Deployed {deploy(args.built, args.original, args.replace)}; original untouched.')
        else:
            scaffold(args.source, args.destination, args.name, args.slug, args.app_id, args.icon)
            print(f'Created {args.destination}; dependencies not installed, app not executed.')
    except (ValueError, OSError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
