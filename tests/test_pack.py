import importlib.util
import json
from pathlib import Path
import plistlib
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('pack', Path(__file__).resolve().parents[1] / 'scripts' / 'pack.py')
pack = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pack)


class PackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.web = self.root / 'web'
        self.web.mkdir()
        (self.web / 'index.html').write_text('<script src="main.js"></script>')
        (self.web / 'main.js').write_text('console.log("hello")')

    def scaffold(self, dest=None, **kwargs):
        args = dict(name='Test App', slug='test-app', app_id='com.example.testapp')
        args.update(kwargs)
        pack.scaffold(self.web, dest or self.root / 'desktop', **args)

    def test_audit_hashes_and_existing_resource(self):
        result = pack.audit(self.web)
        self.assertEqual(len(result['files']), 2)
        self.assertEqual(result['missing_literal_resources'], [])
        self.assertEqual(len(result['files'][0]['sha256']), 64)

    def test_missing_root_relative_and_escape(self):
        (self.web / 'main.js').write_text('fetch("/missing.json"); fetch("../outside.json")')
        result = pack.audit(self.web)
        self.assertEqual({x['reason'] for x in result['missing_literal_resources']},
                         {'not-found', 'outside-web-root'})

    def test_redacts_url_credentials_and_queries(self):
        (self.web / 'main.js').write_text('fetch("https://user:password@example.com/api?token=secret#private")')
        result = pack.audit(self.web)
        self.assertEqual(result['candidate_remote_urls'], ['https://example.com/api'])
        self.assertNotIn('password', json.dumps(result))
        self.assertNotIn('token=secret', json.dumps(result))

    def test_integration_indicators(self):
        (self.web / 'main.js').write_text('claude.use("files"); new Worker("x"); localStorage.getItem("a")')
        categories = {x['category'] for x in pack.audit(self.web)['indicators']}
        self.assertTrue({'host_bridge', 'dynamic_resources', 'storage'} <= categories)

    def missing(self):
        return {(x['resource'], x['reason']) for x in pack.audit(self.web)['missing_literal_resources']}

    def test_protocol_relative_url_is_remote(self):
        (self.web / 'index.html').write_text('<script src="//cdn.example.com/lib.js?k=secret"></script>')
        result = pack.audit(self.web)
        self.assertEqual(result['candidate_remote_urls'], ['//cdn.example.com/lib.js'])
        self.assertEqual(result['missing_literal_resources'], [])

    def test_srcset_candidates(self):
        (self.web / 'a.png').write_bytes(b'x')
        (self.web / 'index.html').write_text(
            '<img srcset="a.png 1x, b.png 2x"><img srcset="data:image/png;base64,AAAA 1x">')
        self.assertEqual(self.missing(), {('b.png', 'not-found')})

    def test_static_imports_and_workers(self):
        (self.web / 'main.js').write_text(
            'import x from "./mod.js";import{y}from"./min.js";import "./side.js";'
            'import React from "react"; new Worker("w.js"); new SharedWorker("sw.js")')
        self.assertEqual(self.missing(), {(r, 'not-found') for r in
                                          ('./mod.js', './min.js', './side.js', 'w.js', 'sw.js')})

    def test_directory_links(self):
        (self.web / 'sub').mkdir()
        (self.web / 'sub' / 'index.html').write_text('')
        (self.web / 'index.html').write_text('<a href="sub/"></a><a href="/"></a><a href="./"></a>')
        self.assertEqual(self.missing(), {('sub/', 'directory-not-served')})

    def test_ignores_namespaces_and_template_placeholders(self):
        (self.web / 'index.html').write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"></svg><img src="${base}/a.png"><a href="{{ url }}"></a>')
        result = pack.audit(self.web)
        self.assertEqual(result['candidate_remote_urls'], [])
        self.assertEqual(result['missing_literal_resources'], [])

    def test_ignores_minified_fragments_and_mime_types(self):
        (self.web / 'main.js').write_text(
            'a.src=t;new Worker("o");fetch("new");x.href="+c[1]+";y.src="sky-";'
            'z.href="image/png";w.src="o,location.href";fetch("/api/data");q.src="real.png"')
        self.assertEqual(self.missing(), {('/api/data', 'not-found'), ('real.png', 'not-found')})

    def test_urls_in_comments_are_counted_not_listed(self):
        (self.web / 'main.js').write_text(
            '// see https://example.org/docs and http://example.net/paper.pdf\n'
            '/* https://example.org/more */ const u = "https://api.example.com/v1"; el.src=\'https://cdn.example.com/a.js\''
        )
        (self.web / 'index.html').write_text('<link href="https://fonts.example.com/css"><style>a{background:url(https://img.example.com/x.png)}</style>')
        result = pack.audit(self.web)
        self.assertEqual(result['candidate_remote_urls'], ['https://api.example.com/v1', 'https://cdn.example.com/a.js',
                                                           'https://fonts.example.com/css', 'https://img.example.com/x.png'])
        self.assertEqual(result['urls_only_mentioned'], {'main.js': 3})

    def test_rejects_invalid_names(self):
        for name in ['', ' ', 'a/b', 'a\\b', 'a: b', 'a"b', ' padded', 'dot.', 'x' * 101, 'a\nb']:
            with self.assertRaises(ValueError, msg=repr(name)):
                self.scaffold(name=name)
        self.assertFalse((self.root / 'desktop').exists())
        self.scaffold(name="Café Timer (v2) - Mike's")

    def bundle(self, path, **info):
        (path / 'Contents' / 'Resources').mkdir(parents=True)
        with (path / 'Contents' / 'Info.plist').open('wb') as f:
            plistlib.dump({'CFBundleName': path.stem, **info}, f)
        (path / 'Contents' / 'marker').write_text(path.name)
        return path

    def claude_app(self):
        apps = self.root / 'Claude Apps'
        app = self.bundle(apps / 'Focus.app', ClaudeArtifactAppId='abc123',
                          ElectronAppShimHostPath='/Applications/Claude.app', CFBundleIconFile='app')
        (app / 'Contents' / 'Resources' / 'app.icns').write_bytes(b'icns')
        registry = self.root / 'installed.json'
        registry.write_text(json.dumps({'apps': [
            {'installId': 'other', 'artifactUuid': '11111111-1111-1111-1111-111111111111', 'org': 'org-secret'},
            {'installId': 'abc123', 'artifactUuid': '6edc65a4-d5cc-4c27-937a-c27a7998aa86', 'org': 'org-secret'}]}))
        return app, registry

    def test_inspect_resolves_claude_app_to_artifact(self):
        app, registry = self.claude_app()
        result = pack.inspect(app, registry)
        self.assertTrue(result['claude_artifact_app'] and result['launcher_only'])
        self.assertEqual(result['artifact_url'],
                         'https://claude.ai/code/artifact/6edc65a4-d5cc-4c27-937a-c27a7998aa86')
        self.assertEqual(Path(result['deploy_target']).name, 'Focus-Packed.app')
        self.assertEqual(Path(result['icon']).name, 'app.icns')
        self.assertTrue(result['deploy_dir_writable'])
        self.assertNotIn('org-secret', json.dumps(result))
        self.assertNotIn('11111111', json.dumps(result))

    def test_inspect_without_registry_entry_or_claude_id(self):
        app, registry = self.claude_app()
        registry.write_text('{"apps": []}')
        self.assertIsNone(pack.inspect(app, registry)['artifact_url'])
        self.assertIsNone(pack.inspect(app, self.root / 'absent.json')['artifact_url'])
        registry.write_text(json.dumps({'apps': [{'installId': 'abc123', 'artifactUuid': '../evil'}]}))
        self.assertIsNone(pack.inspect(app, registry)['artifact_url'])
        plain = pack.inspect(self.bundle(self.root / 'Plain.app'), registry)
        self.assertFalse(plain['claude_artifact_app'] or plain['launcher_only'])
        with self.assertRaisesRegex(ValueError, 'bundle'):
            pack.inspect(self.web, registry)

    def test_deploy_beside_original(self):
        app, _ = self.claude_app()
        built = self.bundle(self.root / 'release' / 'Focus.app')
        (built / 'Contents' / 'link').symlink_to('marker')
        target = pack.deploy(built, app)
        self.assertEqual(target, app.resolve().parent / 'Focus-Packed.app')
        self.assertTrue((target / 'Contents' / 'link').is_symlink())
        self.assertEqual((app / 'Contents' / 'marker').read_text(), 'Focus.app')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            pack.deploy(built, app)
        (built / 'Contents' / 'marker').write_text('v2')
        pack.deploy(built, app, replace=True)
        self.assertEqual((target / 'Contents' / 'marker').read_text(), 'v2')
        self.assertEqual(sorted(p.name for p in app.parent.iterdir()), ['Focus-Packed.app', 'Focus.app'])

    def test_deploy_refusals(self):
        app, _ = self.claude_app()
        built = self.bundle(self.root / 'release' / 'Focus.app')
        with self.assertRaisesRegex(ValueError, 'separate'):
            pack.deploy(app, app)
        with self.assertRaisesRegex(ValueError, 'already a packed app'):
            pack.deploy(built, self.bundle(app.parent / 'Other-Packed.app'))
        with self.assertRaisesRegex(ValueError, 'bundle'):
            pack.deploy(self.web, app)
        app.parent.chmod(0o555)
        self.addCleanup(app.parent.chmod, 0o755)
        with self.assertRaisesRegex(ValueError, 'No write permission'):
            pack.deploy(built, app)
        self.assertFalse((app.parent / 'Focus-Packed.app').exists())

    def test_scaffold_icon(self):
        icon = self.root / 'app.icns'
        icon.write_bytes(b'icns')
        self.scaffold(icon=icon)
        self.assertEqual((self.root / 'desktop' / 'build' / 'icon.icns').read_bytes(), b'icns')
        with self.assertRaisesRegex(ValueError, 'icns'):
            self.scaffold(dest=self.root / 'other', icon=self.web / 'main.js')
        self.assertFalse((self.root / 'other').exists())

    def test_scaffold(self):
        self.scaffold()
        out = self.root / 'desktop'
        package = json.loads((out / 'package.json').read_text())
        self.assertEqual(package['build']['appId'], 'com.example.testapp')
        self.assertEqual((out / 'web' / 'main.js').read_bytes(), (self.web / 'main.js').read_bytes())
        self.assertNotIn('devDependencies', package)
        main = (out / 'main.cjs').read_text()
        for setting in ['nodeIntegration: false', 'contextIsolation: true', 'sandbox: true',
                        "action: 'deny'", 'Content-Security-Policy']:
            self.assertIn(setting, main)

    def test_refuses_overwrite(self):
        self.scaffold()
        with self.assertRaisesRegex(ValueError, 'already exist'):
            self.scaffold()

    def test_refuses_nested_destination(self):
        with self.assertRaisesRegex(ValueError, 'contain'):
            self.scaffold(dest=self.web / 'desktop')

    def test_rejects_invalid_identifiers(self):
        with self.assertRaises(ValueError):
            self.scaffold(slug='../bad')
        with self.assertRaises(ValueError):
            self.scaffold(app_id='no-domain')
        self.assertFalse((self.root / 'desktop').exists())

    def test_rejects_symlinks(self):
        (self.web / 'escape').symlink_to(self.root)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.scaffold()
        self.assertFalse((self.root / 'desktop').exists())

    def test_excludes_development_directories(self):
        (self.web / 'node_modules').mkdir()
        (self.web / 'node_modules' / 'ignored.js').write_text('ignore')
        self.scaffold()
        self.assertFalse((self.root / 'desktop' / 'web' / 'node_modules').exists())

    def test_requires_entry_point(self):
        (self.web / 'index.html').unlink()
        with self.assertRaisesRegex(ValueError, 'index.html'):
            self.scaffold()


if __name__ == '__main__':
    unittest.main()
