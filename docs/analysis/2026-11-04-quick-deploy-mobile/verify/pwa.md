# Verification report — slice `pwa` (word-Dance quick-deploy + mobile research)

Date 2026-11-04 · repo `/Users/sqin/word-dance` @ `9ab13a5` (git status: only the pre-existing untracked `docs/` files, before and after) · digest verified: `…/scratchpad/quick/facts/pwa.md` · verifier scratch: `…/scratchpad/quick/verify-pwa/` (throwaway data dir, dist builds, icons, server logs).

Hard rules respected: nothing under `/Users/sqin/word-dance-data`, port 8000, the real `claude` binary or any tracked file was touched. Throwaway `wd serve` processes ran on `127.0.0.1:8027` with `WD_DATA_DIR=…/verify-pwa/data`, `WD_CLAUDE_BIN=backend/tests/fake_claude.py`, `WD_WORKER_ENABLED=0`, `WD_DEV=1`, and were killed (`lsof -nP -iTCP:8027 -sTCP:LISTEN` → nothing).

| Claim | Verdict | One-line reason |
|---|---|---|
| F2 | confirmed | `public/` = `favicon.svg` only; grep hits only the Apple meta at `index.html:11`; every cited runtime-shell line matches |
| F3 | confirmed | exact CSP observed on `/sw.js`, `/manifest.webmanifest`, icons; MDN fallback chains quoted; trial `index.html` registers via external `/registerSW.js` |
| F4 | corrected | headers/MIME/200-HTML fallback reproduced by curl; **but** `FileResponse` never returns 304 (If-None-Match/If-Modified-Since → 200), and the literal `/index.html` path is `max-age=3600` |
| F5 | corrected | recipe reproduced byte-identically (40,133 B, opaque 180 px, glyph in safe zone); immaterial error: `qlmanage` drew the icon at 109 px, not 64 px |
| F6 | confirmed | rebuilt in the scratch copy: identical `sw.js` 4,470 B, 69 entries / 550.35 KiB, lock 124→462, node_modules 110→174 MB (digest said 109→173) |
| F7 | confirmed | all vendor quotes verified verbatim on 2026-11-04; Chrome post shows no date (currency of the prompt rule stays unverified) |
| F8 | confirmed | Max-Age=2592000, `Content-Disposition: attachment` and no-CSRF-on-GET reproduced live; Apple transcript + WebKit 290847 quoted; minor nuances noted |
| F9 | unverifiable | UA idiom, repo grep and polyfill confirmed; the WeChat/QQ "no A2HS" behaviour itself cannot be tested here |
| F10 | confirmed | lint OK, typecheck OK, vitest **295/295** (flaky case did not fail), build 704 KB / `index-CsasxgTd.js` 302.86 kB → 99.61 kB gzip, `public/` copied to dist root |
| F12 | confirmed | live swap of the `frontend` symlink left the running process on the old snapshot; prune → 503; restart → new snapshot; `config.py:268` `.resolve()` |

---

## F2 — installability surface missing, runtime shell ready — **confirmed**

Ran (repo root):

```
ls -la frontend/public                      → favicon.svg (248 B) only
grep -rniE 'manifest|serviceWorker|apple-touch-icon|MicroMessenger|beforeinstallprompt|display-mode|mobile-web-app-capable' \
     frontend/src frontend/index.html frontend/vite.config.ts frontend/package.json
  → frontend/index.html:11:    <meta name="apple-mobile-web-app-capable" content="yes" />   (the only hit)
cat -n frontend/index.html                  → lines 5–14 exactly as cited; :14 <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
```

Cited lines read with `sed -n`: `tokens.css:55–57` (`--safe-top/--safe-bottom: env(safe-area-inset-*)`, `--tabbar-h`); `global.css:23,29` (`min-height: 100dvh` on body/#root), `:150` (`padding-block … calc(var(--space-6) + var(--safe-bottom) + var(--tabbar-h))`); `AppLayout.css:26` (`padding-top: var(--safe-top)`), `:120` (`padding-bottom: var(--safe-bottom)`); `usePolling.ts:31–33,72–75,101–106` (skip while hidden, resume on `visibilitychange`); `App.tsx:13–38` (`AppErrorBoundary`, `/import|fetch|chunk|module/i` → `zh.errors.network` + reload); `docs/analysis/2026-11-03-public-launch/facts/frontend-parity.md:5` ("there is no service worker, no manifest and no offline data"). A fresh build (F10) confirms the dist root holds only `index.html`, `favicon.svg`, `assets/`.

## F3 — CSP already permits same-origin manifest + SW; only inline registration blocked — **confirmed**

- `backend/wd/main.py:93–101` SECURITY_HEADERS; observed verbatim on every response of the throwaway server (`curl -s -D - …/sw.js`, `/manifest.webmanifest`, `/icons/icon-192.png`, `/`):
  `content-security-policy: default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'` — no `worker-src`/`child-src`/`manifest-src`, no `'unsafe-inline'` in `script-src`. The same CSP rides on `/sw.js` and `/workbox-*.js`, so the worker's `importScripts` and precache fetches are bounded to `'self'` — all Variant B needs.
- `.venv/bin/pytest -q backend/tests/integration/test_health.py -k "spa or security"` → `4 passed` (`test_health.py:53–54` prefix pin is live).
- MDN `worker-src` (fetched 2026-11-04): "specifies valid sources for Worker, SharedWorker, or ServiceWorker scripts" … "If this directive is absent, the user agent will first look for the child-src directive, then the script-src directive, then finally for the default-src directive, when governing worker execution." MDN `manifest-src`: "If this directive is absent, the user agent will look for the default-src directive."
- Trial build re-executed (F6): `index.html` contains `<script id="vite-plugin-pwa:register-sw" src="/registerSW.js" defer></script>`; `registerSW.js` (134 B) = `if('serviceWorker' in navigator) {window.addEventListener('load', () => {navigator.serviceWorker.register('/sw.js', { scope: '/' })})}`. vite-pwa docs: `inline` "injects a simple register script, inlined in the application entry point"; `script-defer` "injects a script tag with defer attribute in the head with the src attribute".
- Limit: no browser was driven; the verdict rests on the observed header plus the MDN fallback semantics.

## F4 — Cache-Control/MIME for root files; missing `/assets/*` → `index.html` 200 — **corrected**

Throwaway server: `WD_FRONTEND_DIST` → copy of the Variant B build plus a hand-written `manifest.webmanifest`, `icons/icon-192.png`, `apple-touch-icon.png`. `curl -s -D - -o body <url>`:

| path | status | Cache-Control | Content-Type |
|---|---|---|---|
| `/` | 200 | `no-cache` | `text/html; charset=utf-8` (ETag `"31aecd57…"`) |
| `/sw.js` | 200 | `public, max-age=3600` | `text/javascript; charset=utf-8` |
| `/registerSW.js`, `/workbox-9c191d2f.js` | 200 | `public, max-age=3600` | `text/javascript; charset=utf-8` |
| `/manifest.webmanifest` | 200 | `public, max-age=3600` | `application/manifest+json` |
| `/icons/icon-192.png`, `/apple-touch-icon.png` | 200 | `public, max-age=3600` | `image/png` |
| `/favicon.svg` | 200 | `public, max-age=3600` | `image/svg+xml` |
| `/assets/index-CsasxgTd.js` | 200 | `public, max-age=31536000, immutable` | `text/javascript; charset=utf-8` |
| `/assets/missing-deadbeef.js` | **200** | `no-cache` | **`text/html`** — body is `index.html` (same ETag as `/`) |
| `/assets/`, `/assets` | 200 | `no-cache` | `text/html` (same fallback) |
| `/index.html` (literal path) | 200 | **`public, max-age=3600`** | `text/html` |

MIME: `.venv/bin/python -I -c "import mimetypes; mimetypes.init(files=[]); print(mimetypes.guess_type('manifest.webmanifest'), mimetypes.guess_type('sw.js'))"` → `('application/manifest+json', None) ('text/javascript', None)` on Python 3.12.16; the live server (which additionally reads this Mac's OS mime files) returned the same types, and `X-Content-Type-Options: nosniff` is present.

Spec/vendor (fetched 2026-11-04): SW spec `RegistrationOptions`: `updateViaCache = "imports"`; Update algorithm step 7.2: "Set request's cache mode to "no-cache" if any of the following are true: registration's update via cache mode is not "all". job's force bypass cache flag is set. newestWorker is not null and registration is stale." (stale = last update check "greater than 86400" s). web.dev service-worker-lifecycle: "Most browsers, including Chrome 68 and later, default to ignoring caching headers when checking for updates of the registered service worker script." and updates trigger on "A navigation to an in-scope page. A functional events such as push and sync, unless there's been an update check within the previous 24 hours." Safari's behaviour remains unverified (digest says so too).

Pins: `test_health.py:185–203` (`/` no-cache, `/assets/app-abc123.js` immutable, `/today` fallback) pass; nothing pins the 3600 branch or the missing-asset fallback — confirmed.

**Correction 1 — no 304s.** The digest's "Starlette's FileResponse adds ETag/Last-Modified … so no-cache revalidates with 304s" is false by execution:
```
curl -s -D - -o /dev/null -H 'If-None-Match: "9d31572fa4c47ff810499ff595231ac9"' http://127.0.0.1:8027/sw.js → HTTP/1.1 200 OK
curl -s -D - -o /dev/null -H "If-Modified-Since: Wed, 04 Nov 2026 11:41:36 GMT" http://127.0.0.1:8027/sw.js → HTTP/1.1 200 OK
```
Starlette 1.10.0 implements conditional responses only in `StaticFiles.is_not_modified` (`starlette/staticfiles.py:191,211–224`); `main.py:257,260` return `FileResponse` directly, which merely *emits* the validators (`responses.py:336–344`). `no-cache` therefore means a full body on every navigation (`index.html` 1,026 B, `sw.js` 4,470 B) — harmless at this size, but the stated rationale is wrong and must not be used to justify `no-cache` on larger files.

**Correction 2 — `/index.html` is 1 h cacheable.** Only `/` and SPA-fallback paths get `no-cache`; the literal `index.html` file goes through the generic branch (`public, max-age=3600`). Workbox precaches the URL `index.html` and uses `/index.html` as `navigateFallback` (its own precache fetch carries `__WB_REVISION__`, so it is unaffected), but A4's no-cache set should include `index.html` too.

## F5 — `sips` rasterises SVG; five-command recipe; qlmanage unusable — **corrected (immaterial detail)**

```
which rsvg-convert magick convert inkscape cairosvg → all MISSING; /usr/bin/sips, /usr/bin/qlmanage, node v22.23.4 present
sips --version → sips-316 ; sw_vers → macOS 26.7.1 (25G241)
```
Re-ran the exact A3 recipe into `verify-pwa/icons/` (favicon.svg copied from the checkout, `icon-maskable.svg` written from the digest):
`icon-192.png` 5,257 B · `icon-512.png` 18,347 B · `icon-maskable-192.png` 2,949 B · `icon-maskable-512.png` 10,939 B · `apple-touch-icon.png` 2,641 B (five files = 40,133 B) · `icon-1024.png` 48,279 B; `file` → `PNG image data, N x N, 8-bit/color RGBA`; `cmp` against the research probe → **all five byte-identical**.
Pillow 12.3.0 (`.venv`) pixel check: `apple-touch-icon.png` alpha min = max = 255 (fully opaque), corner `(59,91,219)` = `#3b5bdb`; `icon-maskable-512.png` glyph bbox (170,199)–(323,313) → inside the central 80 % safe zone (51–461); `icon-192/512/1024` ('any') have transparent corners (alpha 0 at (0,0)) and 197/323/382 distinct colours → anti-aliased vector rendering, not an upscaled 64 px bitmap (icon-192.png viewed: crisp).
`qlmanage -t -s 512 -o ql public/favicon.svg` → 512×512 PNG (9,281 B), opaque white canvas, icon in the top-left corner with blue bbox **(0,0)–(109,109)**: unusable as claimed, but the digest's "drew the icon at its intrinsic 64 px" is inaccurate (109 px, plus an opaque background).

## F6 — `vite-plugin-pwa@2.0.0` builds against Vite 8.3.4 at a +338-package cost — **confirmed**

```
npm view vite-plugin-pwa version peerDependencies
  → 2.0.0 ; vite: '^3.1.0 || ^4.0.0 || ^5.0.0 || ^6.0.0 || ^7.0.0 || ^8.0.0' ; workbox-build ^7.4.1 ; workbox-window ^7.4.1
cd …/scratchpad/quick/pwa-sw-trial && npm ci --prefer-offline          → added 412 packages in 2s
npx vite build -c vite.config.pwa.ts --outDir …/verify-pwa/dist-sw     → vite v8.3.4 … ✓ built in 627ms
  PWA v2.0.0 / mode generateSW / precache 69 entries (550.35 KiB) / sw.js, workbox-9c191d2f.js
```
Outputs: `sw.js` 4,470 B (**byte-identical** to the research output, `cmp`), `workbox-9c191d2f.js` 15,112 B, `registerSW.js` 134 B; `sw.js` contains `skipWaiting()`, `clientsClaim()`, `precacheAndRoute`, `cleanupOutdatedCaches` and the literal `[/^\/api(\/|$)/,/^\/media(\/|$)/]`; 69 `url:` entries. Footprint: repo `package-lock.json` 124 packages (lockfileVersion 3) vs trial 462; repo `node_modules` 110 MB / 80 top-level vs trial 174 MB / 286 (digest: 109 → 173 MB — rounding). Checkout untouched.
Nit: `favicon.svg` is listed twice in the precache manifest (same revision; `includeAssets` and `globPatterns` both match it) — workbox dedupes identical entries, so 68 unique URLs; `includeAssets: ['apple-touch-icon.png']` named a file absent from the trial and was silently ignored. With `globPatterns` covering `svg,png,webmanifest`, `includeAssets` is redundant.

## F7 — platform installability rules — **confirmed**

Fetched 2026-11-04:
- webkit.org/blog/17333 (Safari 26.0): "By default, every website added to the Home Screen opens as a web app." · toggle "Open as Web App" · "There are now zero requirements for 'installability' in Safari." · "Giving users a web app experience simply no longer requires a manifest file."
- developer.chrome.com/blog/update-install-criteria: "As a first step we have removed the requirement to have a service worker that implements the fetch() method for installation from the menu, since version 108 on mobile and 112 on Desktop." · "For now the algorithm that displays the install prompt still requires the presence of a fetch() handler…". The fetched page renders no publication date; whether the prompt rule still holds in late 2026 is unverified (digest flags this).
- web.dev/articles/install-criteria: `short_name` or `name`; `icons` "must include a 192px and a 512px icon"; `start_url`; `display` ∈ fullscreen/standalone/minimal-ui/window-controls-overlay; `prefer_related_applications` absent or false; "Be served over HTTPS"; no service-worker criterion (it also lists engagement heuristics — see omission 6).
- webkit.org/blog/12445 (Safari 15.4): "Safari and iOS use manifest-declared icons when there is no apple-touch-icon defined in the HTML head, and when the manifest file code for declaring the icons either omits the "purpose" key or includes "purpose": "any"." · "Defining icons by using apple-touch-icon takes precedence over manifest-declared icons…".
- MDN "Making PWAs installable": "While not a requirement for a PWA to be installable, many PWAs use service workers…"; "On iOS 16.4 and later, PWAs can be installed from the Share menu in Safari, Chrome, Edge, Firefox, and Orion."
Not verified: the Chrome console deprecation warning for the Apple-only meta (digest cites search results only).

## F8 — standalone-mode behaviours — **confirmed**

Code + execution:
- `config.py:78 session_days: int = 30`; `deps.py:165–172` (slide once per day, re-issue cookie); `.venv/bin/pytest -q backend/tests/integration/test_deps.py` → `4 passed`. Live: `POST /api/auth/register` (`X-WD-Request: 1`) → `201`, `set-cookie: wd_session=…; HttpOnly; Max-Age=2592000; Path=/; SameSite=lax`.
- `SettingsPage.tsx:597–602` `<a … href={exportAccountUrl('csv'|'json')} download>`, `:609` `<input type="file">`; `endpoints.ts:394 exportAccountUrl`; `account.py:201` `Content-Disposition: attachment`. Live: `GET /api/account/export?format=csv` with the cookie and **no** `X-WD-Request` → `200`, `content-disposition: attachment; filename="word-dance-export-20261104.csv"`, `text/csv; charset=utf-8`, `cache-control: no-store`; `format=json` → `attachment; filename="word-dance-export-20261104.json"`; no cookie → `401`. (`deps.py:8`: the CSRF header is required for non-GET only.)
- `StudyPage.tsx:54` `PENDING_GRADES_KEY = 'wd.pendingGrades'`, `:89–105` `flushStoredPending`, `:184–189` localStorage mirror, `:206–212` `speak(currentDisplay, accent)` on card change; `useSpeech.ts:2–3` ("the first user gesture unlocks audio on iOS … because speak() is always triggered from a click/key handler") and `speak()` `:37–44` has no gesture guard → the first card's auto-pronounce does run without a gesture.
- Polling: `TodayPage.tsx:64–65`, `StudyPage.tsx:229–230`, `WordDetailPage.tsx:142–143` gate inline intervals on `document.visibilityState`; `AttentionBadge.tsx:70` uses `usePolling`. One exception: the bounded, gesture-initiated image poll (`WordDetailPage.tsx:172`, `IMAGE_POLL_MAX`) is not gated — immaterial.
External:
- Apple WWDC23 10120 transcript (developer.apple.com/videos/play/wwdc2023/10120/): "Home Screen web apps have a standalone, app-like experience on iOS, with separate cookies and storage from the browser." The cookie-copy sentence is macOS-specific: "Safari copies website cookies when it is added to the Dock." / "From that point on, cookies are separate between Safari and the web app." → the digest's "unqualified" remark is wrong; "one extra login on iPhone" is the expected default (iOS 26 not device-tested). wwdcnotes.com was unreachable (TLS name mismatch, then a redirect stub).
- bugs.webkit.org/show_bug.cgi?id=290847: "File downloads and inline file display in iOS 18.4 Web App lead to navigation-less state", Status **NEW**, Reported 2025-04-01 08:58 PDT, last modified 2025-04-08; versions named in the report: iOS 18 (18.4 in the title) and iOS 16.7.10; the "Open in …" sheet "prohibits further navigation inside the Web App", "The only resolution is to force-close and relaunch the web app"; no comment reports a fix.
Note for R5: `endpoints.ts:391–392` already exposes `exportAccount(format)` (via `requestText`) — the standalone fallback can reuse it instead of a raw `fetch()`.

## F9 — WeChat/QQ WebViews need detection + 「在浏览器打开」 — **unverifiable** (code-level parts confirmed)

- Confirmed: no handling in the repo (grep in F2); `frontend/src/test/setup.ts:31–43` installs the `matchMedia` polyfill (`matches: false`) only when jsdom lacks one, so a component can override `window.matchMedia` per test; UA token `MicroMessenger` confirmed in gist.github.com/Natumsol/1d064cc8735bf7ccdc16 (`ua.match(/MicroMessenger/i)`), cnblogs.com/68xi/p/8552898.html (same idiom) and ua-parser-js (`/micromessenger\/([\w\.]+)/i` → WeChat). The QQ token appears in ua-parser-js as `/\b(qq)\/([\w\.]+)/i` (mapped to "QQBrowser") and `MQQBrowser` separately; neither of the digest's two sources shows a QQ UA.
- Not checkable here: that WeChat/QQ in-app browsers offer no Add-to-Home-Screen or install prompt (needs a device; no vendor statement found). It is consistent with MDN's "On iOS 16.4 and later, PWAs can be installed from the Share menu in Safari, Chrome, Edge, Firefox, and Orion" (browsers, not embedded WebViews).

## F10 — copy constraints and the verified gate baseline — **confirmed**

- `frontend/scripts/check-copy.mjs:30–33` (CJK in `.tsx` only under `i18n/`; forbidden glossary term anywhere); `src/i18n/zh.test.ts:44–53`, `:67–80` (line-for-line equality of the `export const zh = {…} as const;` block with FRONTEND.md); `zh.contract.test.ts:61–83` (same keys, identical values); `docs/FRONTEND.md:204` `## 8. i18n strings`, `:275` `settings:`, `:302` `} as const;`; `zh.ts` `history:` at `:72`, `settings:` at `:74`, block end `:101`.
- Runs in `frontend/`: `npm run lint` → `copy check OK`; `npm run typecheck` → clean (2.2 s wall); `npx vitest run` → `Test Files 39 passed (39)`, **`Tests 295 passed (295)`**, 3.06 s — the `AuthContext.test.tsx:146` case the digest saw fail did not fail here (consistent with "flaky", not a regression); `npm run build -- --outDir …/verify-pwa/dist` → `✓ built in 104ms` (digest 294 ms; timing varies), `dist` 704 KB (`assets/` 696 KB, 65 files), `index-CsasxgTd.js 302.86 kB │ gzip: 99.61 kB`, `favicon.svg` copied to the dist root beside `index.html` (1,026 B). `git status` unchanged afterwards.

## F12 — one snapshot per process; skew channels; install.sh unchanged — **confirmed**

- `backend/wd/config.py:268` `frontend_dist = Path(text("WD_FRONTEND_DIST", …)).expanduser().resolve()` — the symlink is resolved once in `Settings.from_env`; `main.py:229–233,257–260` use that path. `deploy/install.sh:134–139` exactly as cited (`rm -rf`, `mv -T` publish, `ln -sfn` + `mv -T` swap, `ls -1t | tail -n +3 | xargs -r rm -rf --`, after the stop); `docs/DEPLOY.md:20–21`; `test_deploy_files.py:359–365` pins build < stop < unstage < rename < link < swap < prune < migrate < restart (read; not executable here — see omission 4).
- Execution (`verify-pwa/data`: `frontend-releases/A`, `frontend-releases/B` with `<title>word-Dance SNAPSHOT-B</title>`, `frontend -> frontend-releases/A`, `wd serve` on :8027):
  ```
  GET /                                   → <title>word-Dance</title>                (A)
  ln -sfn frontend-releases/B data/frontend ; readlink → frontend-releases/B          (swap while running)
  GET / ; GET /today                       → <title>word-Dance</title>  both          (still A; /index.html ETag unchanged)
  rm -rf frontend-releases/A               → GET / 503 "前端尚未构建…", GET /sw.js 503, GET /api/health 200
  restart wd serve                         → GET / → <title>word-Dance SNAPSHOT-B</title>
  ```
  (A first attempt with BSD `mv -f link.tmp link` was invalid — it moved the temp link *into* the target directory — and was redone with `ln -sfn`.) One process = one snapshot, picked up only at restart; a SW can never observe two snapshots from one process. Skew remains only for a page/app kept open across a deploy and the `index.html`-200 fallback (F4).
- vite-pwa docs quotes verified verbatim: "the plugin will force workbox.clientsClaim and workbox.skipWaiting to true", "Automatic reload is not automatic page reload, you will need to use the following code in your application entry point if you want automatic page reload: registerSW({ immediate: true })", "We strongly recommend you to NOT deactivate the option" (cleanupOutdatedCaches).

---

## Omissions / new findings

1. **`/index.html` literal path is 1-hour cacheable** (`public, max-age=3600`; only `/` and SPA-fallback paths are `no-cache`). A4's no-cache set should include `index.html`: Variant B's `navigateFallback: '/index.html'` and any direct link otherwise get a shell that can lag a deploy by up to an hour (workbox's own precache fetch carries `__WB_REVISION__` and is unaffected). Evidence: curl table in F4.
2. **`FileResponse` never answers 304.** Starlette 1.10.0 keeps conditional-request logic in `StaticFiles` only (`staticfiles.py:191,211–224`); `main.py:257,260` use `FileResponse`. `If-None-Match`/`If-Modified-Since` on `/sw.js` → 200. `no-cache` therefore costs a full body each time (index.html 1,026 B, sw.js 4,470 B) — acceptable, but the digest's "revalidates with 304s" is wrong.
3. **Pruned-while-serving → whole-site 503.** The process keeps serving the snapshot it resolved at startup; `install.sh` keeps only the two newest. Two consecutive `--no-restart` / no-sudo runs delete the snapshot a still-running process is pinned to, after which `/`, `/sw.js`, `/assets/*` answer 503 while `/api/*` keeps working (reproduced by deleting A under the live process). Not SW-specific and install.sh prints a restart WARN, but it qualifies "install.sh itself needs no change": a sentence in DEPLOY.md/ops is warranted.
4. **The install.sh pins are Linux-only.** `.venv/bin/pytest -q backend/tests/unit/test_deploy_files.py` → `19 failed, 13 passed, 1 skipped` on this Mac; the dry-run tests die in preflight (`install.sh:45` asserts python3 ≥ 3.12 — Apple's `python3` is 3.9.6; with a python3.12 shim on PATH they then fail on GNU `df --output=avail`, `install.sh:50`: "need > 2 GB free on /home"). So the `test_deploy_files.py:359–365` pins cited by F10/F12 must be run on the Ubuntu box or CI, never here (matches the memory note that 19 `test_deploy_files.py` tests fail by design on the Mac).
5. **The export fallback is simpler than described, and the iOS login story is firmer.** `GET /api/account/export` needs only the cookie (CSRF header is non-GET only, `deps.py:8`; curl 200 without `X-WD-Request`), and `endpoints.ts:391–392` already has `exportAccount(format)` (`requestText`) — R5 can reuse it. Apple's WWDC23 transcript states iOS Home Screen web apps have "separate cookies and storage from the browser" and limits the cookie copy to the macOS Dock, so open question 1 should default to "one extra login expected" rather than "unknown".
6. **Chrome's install prompt also has engagement heuristics** (web.dev install-criteria: at least one click/tap on the page, ≥30 s viewing, app not already installed) that F7 omits; together with the fetch-handler rule this means Variant B's 「安装」 button must still handle `beforeinstallprompt` never firing (manual instructions path).

Minor nits folded into the sections above: duplicate `favicon.svg` precache entry / non-existent `includeAssets` file in the trial config (F6); `qlmanage` 109 px not 64 px (F5); the un-gated bounded image poll (F8).

## Scratch artefacts (all under `…/scratchpad/quick/verify-pwa/`)
`dist/` (plain build), `dist-sw/` (Variant B rebuild), `icons/` (sips outputs, `ql/`), `data/` (throwaway `WD_DATA_DIR` with `frontend-releases/B` left; A deleted during the prune test), `serve.log`, `trial-rebuild.log`, `jar.txt`/`reg.json`/`export.csv` (throwaway account `verifier` in the throwaway DB only), `pybin/` (python3 → 3.12 shim used for omission 4).
