// Review this shell and all recovered assets before running them.
const { app, BrowserWindow, protocol, session } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const MIME = {
  '.html': 'text/html; charset=utf-8', '.htm': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json',
  '.webmanifest': 'application/manifest+json', '.wasm': 'application/wasm',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.avif': 'image/avif',
  '.gif': 'image/gif', '.ico': 'image/x-icon', '.woff': 'font/woff',
  '.woff2': 'font/woff2', '.ttf': 'font/ttf', '.otf': 'font/otf',
  '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.ogg': 'audio/ogg',
  '.mp4': 'video/mp4', '.webm': 'video/webm', '.pdf': 'application/pdf'
};

protocol.registerSchemesAsPrivileged([
  { scheme: 'app', privileges: { standard: true, secure: true, supportFetchAPI: true } }
]);

// Inline script/style supports recovered static sites. Tighten to hashes/nonces
// when practical. No eval, remote code, frames, plugins, or remote connections.
const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "media-src 'self' blob: data:",
  "connect-src 'self'",
  "worker-src 'self' blob:",
  "frame-src 'none'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'none'"
].join('; ');

function localURL(raw) {
  try {
    const u = new URL(raw);
    return u.protocol === 'app:' && u.hostname === 'bundle' &&
      !u.port && !u.username && !u.password;
  } catch { return false; }
}

let mainWindow;
app.whenReady().then(() => {
  const ses = session.defaultSession;
  ses.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  ses.setPermissionCheckHandler(() => false);
  // Defense in depth; CSP alone is not an offline guarantee.
  ses.webRequest.onBeforeRequest((details, callback) => {
    const inline = /^(data:|blob:|about:blank$)/.test(details.url);
    callback({ cancel: !(localURL(details.url) || inline) });
  });

  const webRoot = fs.realpathSync(path.join(__dirname, 'web'));
  protocol.handle('app', async (request) => {
    const headers = { 'Content-Security-Policy': CSP, 'X-Content-Type-Options': 'nosniff' };
    if (!localURL(request.url) || !['GET', 'HEAD'].includes(request.method)) {
      return new Response('Forbidden', { status: 403, headers });
    }
    try {
      const url = new URL(request.url);
      const decoded = decodeURIComponent(url.pathname);
      if (decoded.includes('\0') || decoded.includes('\\')) throw new Error('Invalid path');
      const relative = decoded.replace(/^\/+/, '') || 'index.html';
      const target = fs.realpathSync(path.resolve(webRoot, relative));
      const within = path.relative(webRoot, target);
      if (within.startsWith('..' + path.sep) || within === '..' || path.isAbsolute(within) || !fs.statSync(target).isFile()) {
        return new Response('Forbidden', { status: 403, headers });
      }
      const type = MIME[path.extname(target).toLowerCase()] || 'application/octet-stream';
      const body = request.method === 'HEAD' ? null : await fs.promises.readFile(target);
      return new Response(body, {
        status: 200, headers: { ...headers, 'Content-Type': type }
      });
    } catch {
      return new Response('Not found', { status: 404, headers });
    }
  });

  function createWindow() {
    mainWindow = new BrowserWindow({
      width: 1100, height: 800, title: app.getName(),
      webPreferences: {
        nodeIntegration: false, contextIsolation: true, sandbox: true,
        webSecurity: true, webviewTag: false, allowRunningInsecureContent: false
      }
    });
    mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    mainWindow.webContents.on('will-navigate', (event, url) => {
      if (!localURL(url)) event.preventDefault();
    });
    mainWindow.webContents.on('will-attach-webview', event => event.preventDefault());
    mainWindow.loadURL('app://bundle/index.html');
  }
  createWindow();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
