import type { CapacitorConfig } from '@capacitor/cli';

// word-Dance mobile shell (docs/MOBILE_APP.md §3). A REMOTE shell: the WebView loads the live site, so the page origin equals the API
// origin and cookies / CSRF / media auth work unchanged. `server.url` MUST be the canonical origin the backend serves
// (WD_PUBLIC_URL, no redirects: Android injects the bridge only for that exact origin). Pick the profile with WD_APP_SERVER_URL:
//   WD_APP_SERVER_URL=https://words.example.com npm run sync            (release: https only)
//   WD_APP_SERVER_URL=http://192.168.1.250:8000 WD_APP_ALLOW_HTTP=1 npm run sync   (home-LAN development build only)
// Nothing is baked in by default: every sync / build names the origin explicitly (a forgotten variable must fail, not ship a placeholder).
// The `capacitor:copy:before` hook (scripts/prepare.mjs) renders the offline page with the same origin and, on iOS, the ATS exception
// a plain-http dev build needs (NSAllowsLocalNetworking — since iOS 17 ATS refuses http even to IP literals); Android gets
// `cleartext` (usesCleartextTraffic) below. A store build carries neither.
function canonicalOrigin(value: string | undefined): string | null {
  if (!value) return null;
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  return /^https?:$/.test(url.protocol) && url.origin === value ? value : null;
}
const serverUrl = canonicalOrigin(process.env.WD_APP_SERVER_URL);
if (!serverUrl) {
  throw new Error('WD_APP_SERVER_URL must be the canonical origin — https://host[:port], or http://ip[:port] for a home-LAN dev build with WD_APP_ALLOW_HTTP=1 (no path, no trailing slash, no default port)');
}
const allowHttp = process.env.WD_APP_ALLOW_HTTP === '1';
if (serverUrl.startsWith('http://') && !allowHttp) {
  throw new Error('WD_APP_SERVER_URL is plain http; set WD_APP_ALLOW_HTTP=1 for a development build (never for a store build)');
}

const config: CapacitorConfig = {
  appId: 'com.worddance.app', // can be changed until the first store upload; afterwards it is the app's identity for ever
  appName: 'word-Dance',
  webDir: 'www', // only the offline / retry page rendered by scripts/prepare.mjs (without a local index.html the shell cannot show it)
  server: {
    url: serverUrl,
    cleartext: allowHttp,
    errorPath: 'index.html',
    allowNavigation: [], // signed-out links (署名链接等) open in the system browser
    appendUserAgent: 'word-Dance-App/1',
  },
  ios: {
    limitsNavigationsToAppBoundDomains: false,
  },
  android: {
    allowMixedContent: false,
  },
  plugins: {
    LocalNotifications: {
      smallIcon: 'ic_stat_word_dance',
      iconColor: '#157a73',
    },
  },
};

export default config;
