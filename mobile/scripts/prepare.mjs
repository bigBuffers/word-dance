// Capacitor hook `capacitor:copy:before` (mobile/package.json) — runs before every `cap copy` / `cap sync`, per platform, with the
// build profile in the environment (docs/MOBILE_APP.md §3):
//   1. renders www/index.html — the shell's offline / retry page, served from the LOCAL origin — from templates/index.html with the
//      server origin, so 重试 can navigate back to the site (www/ holds generated files only);
//   2. on iOS, toggles the App Transport Security exception a plain-http dev build needs: NSAllowsLocalNetworking (IP literals,
//      .local and unqualified names — since iOS 17 ATS refuses http to IP addresses without it); a store build gets no exception.
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

export function canonicalOrigin(value) {
  let url;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  return /^https?:$/.test(url.protocol) && url.origin === value ? value : null;
}

const url = canonicalOrigin(process.env.WD_APP_SERVER_URL ?? '');
if (!url) {
  console.error('prepare: set WD_APP_SERVER_URL to the canonical origin — https://host[:port], or http://ip[:port] for a dev build with WD_APP_ALLOW_HTTP=1 (no path, no trailing slash, no default port)');
  process.exit(2);
}
const allowHttp = url.startsWith('http://');
if (allowHttp && process.env.WD_APP_ALLOW_HTTP !== '1') {
  console.error('prepare: WD_APP_SERVER_URL is plain http; set WD_APP_ALLOW_HTTP=1 for a development build (never for a store build)');
  process.exit(2);
}
const root = fileURLToPath(new URL('../', import.meta.url));

// 1. the offline / retry page
mkdirSync(root + 'www', { recursive: true });
writeFileSync(root + 'www/index.html', readFileSync(root + 'templates/index.html', 'utf8').replace(/__WD_APP_SERVER_URL__/g, url));
console.log(`prepare: www/index.html → ${url}`);

// 2. iOS ATS exception for the dev profile only
if ((process.env.CAPACITOR_PLATFORM_NAME ?? 'ios') === 'ios') {
  const plistPath = root + 'ios/App/App/Info.plist';
  let plist = readFileSync(plistPath, 'utf8');
  plist = plist.replace(/\t<key>NSAppTransportSecurity<\/key>\n\t<dict>[\s\S]*?\n\t<\/dict>\n/, '');
  if (allowHttp) {
    plist = plist.replace('\t<key>UIApplicationSceneManifest</key>\n', '\t<key>NSAppTransportSecurity</key>\n\t<dict>\n\t\t<key>NSAllowsLocalNetworking</key>\n\t\t<true/>\n\t</dict>\n\t<key>UIApplicationSceneManifest</key>\n');
  }
  writeFileSync(plistPath, plist);
  console.log(`prepare: Info.plist ATS local-networking exception ${allowHttp ? 'ON (dev build)' : 'off'}`);
}
