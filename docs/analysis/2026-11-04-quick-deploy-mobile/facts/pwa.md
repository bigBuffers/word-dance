# PWA slice — making the deployed word-Dance SPA a good home-screen app (iPhone Safari + Android Chrome / domestic browsers)

Date: 2026-11-04 · repo `/Users/sqin/word-dance` @ `9ab13a5` · slice key `pwa` · all paths below are repo-relative unless absolute.

## Summary

- The SPA already has most of the *runtime* properties of a home-screen app: `viewport-fit=cover`, per-scheme `theme-color`, the three `apple-mobile-web-app-*` metas, safe-area tokens, `100dvh` layouts and visibility-gated polling (F1). What is missing is the *installability surface*: no web app manifest, no PNG icons (only `favicon.svg`), no `<link rel=manifest|apple-touch-icon>`, no service worker, no install hint, no WeChat/QQ in-app-browser guidance (F2).
- The current CSP (`default-src 'self'; script-src 'self'; img-src 'self' data:`) already permits a same-origin manifest and service worker; only an *inline* register snippet would be blocked, and `vite-plugin-pwa` emits an external `/registerSW.js` (F3). `Cache-Control: public, max-age=3600` on `/sw.js` is tolerable under the spec's default `updateViaCache: "imports"`, but a one-line `no-cache` in `_mount_spa` removes the doubt; the bigger hazard is that a missing `/assets/*` chunk is answered with `index.html` 200 instead of 404 (F4).
- On this Mac `sips` *does* rasterise SVG (macOS 26, sips-316): a verified five-command recipe produces crisp 192/512/maskable/180 PNGs (~40 KB total) with no new dependency; `qlmanage` is unusable, `rsvg-convert`/`magick` are absent (F5).
- `vite-plugin-pwa@2.0.0` declares Vite `^8` and built cleanly against Vite 8.3.4 in an isolated scratch copy: `sw.js` 4.5 KB + `workbox-*.js` 15 KB, 69 precache entries (550 KiB), `navigateFallbackDenylist` for `/api` and `/media` honoured — at the price of +338 lock-file packages (F6).
- Platform split (verified from vendor sources): iOS 26 has "zero requirements for installability" and opens every Home-Screen site as a web app by default; Chrome ≥108 on Android installs from the menu without a service worker, but the automatic `beforeinstallprompt` still needs a fetch handler (F7). Therefore the **no-SW variant is sufficient for iPhone and for menu-install on Android**; the SW buys only the Android prompt and an instant shell.
- Standalone quirks that need code: iOS home-screen apps run in their own storage partition (one extra login, then the 30-day sliding session keeps them in), `<a download>` exports hit WebKit bug 290847 ("navigation-less state") and need a share/copy fallback, auto-pronounce of the *first* card runs without a gesture (F8). WeChat/QQ in-app browsers must be detected by UA and told to open the system browser (F9).
- Any new copy must be added to `src/i18n/zh.ts` **and** mirrored line-for-line in `docs/FRONTEND.md §8`; tests, typecheck and lint pass today (295 tests; one flaky AuthContext case), build is 294 ms / 704 KB (F10).
- Recommended: Variant A (manifest + icons + links + install hint + export fallback + two backend one-liners) ≈ 8.5–10 h; Variant B (add vite-plugin-pwa) is an optional +4–6 h for Android.

## Findings

### F1 — What already exists (both platforms)
- **Claim.** The shell is already "standalone-ready" at runtime: iOS metas, per-scheme theme colour, cover viewport, safe-area tokens, dynamic-viewport layouts, visibility-gated polling and a chunk-failure error boundary.
- **Evidence.**
  - `frontend/index.html:5–13`: `viewport-fit=cover`, `color-scheme light dark`, `theme-color #ffffff` (light) / `#121620` (dark), `apple-mobile-web-app-capable=yes`, `apple-mobile-web-app-status-bar-style=default`, `apple-mobile-web-app-title=word-Dance`; `:14` only `<link rel="icon" href="/favicon.svg">`.
  - `frontend/src/styles/tokens.css:55–57` (`--safe-top/--safe-bottom = env(safe-area-inset-*)`, `--tabbar-h`); `global.css:23,29` (`min-height: 100dvh`), `.page` bottom padding includes `--safe-bottom + --tabbar-h` (`global.css:150`); `AppLayout.css:120` (`.tabbar { padding-bottom: var(--safe-bottom) }`), `:26` (TopNav `padding-top: var(--safe-top)`); `StudyPage.css:5` / `ScreenRunPage.css:5` (`calc(100dvh - var(--safe-top))`).
  - `frontend/src/hooks/usePolling.ts:31–33,72–75,101–106` pauses while `document.visibilityState === 'hidden'` and resumes on `visibilitychange`; `AppLayout.tsx:99–102` re-checks the today badge on visibility.
  - `frontend/src/App.tsx:13–38`: `AppErrorBoundary` treats `/import|fetch|chunk|module/` errors as "network" and offers a reload (`zh.common.retry`).
  - `frontend/src/hooks/useSpeech.ts:2–3,37–44`: `speak()` is designed to run from click/key handlers (iOS audio unlock).
- **Implication.** Nothing in CSS/layout needs to change for standalone display; the work is additive (static files + one component + two backend lines).
- **Confidence.** high.

### F2 — The gap table
- **Claim.** Everything on the installability surface is missing; the prior slice agrees ("no service worker, no manifest and no offline data").
- **Evidence.** `ls frontend/public/` → only `favicon.svg` (248 B, 64×64 viewBox, rounded rect `rx=14`, white "W"); `grep` for `manifest|serviceWorker|apple-touch-icon|MicroMessenger|beforeinstallprompt|display-mode` over `frontend/src` and `index.html` → no hits; `docs/analysis/2026-11-03-public-launch/facts/frontend-parity.md:5`.

| Item | Status | Needed for | Notes |
|---|---|---|---|
| `public/manifest.webmanifest` | missing | both (Android install + name/icon/colours; iOS uses it for display/start_url/scope and icons as fallback) | full JSON proposed in §A1 |
| PNG icons 192/512 (`purpose: any`) + maskable 192/512 | missing | Android (Chrome requires 192 and 512), iOS falls back to manifest icons only without `apple-touch-icon` | recipe §A3, verified with `sips` |
| `apple-touch-icon` 180×180 opaque | missing | iPhone (otherwise iOS uses a page screenshot as the icon) | takes precedence over manifest icons on iOS (F7) |
| `<link rel="manifest">`, `<link rel="apple-touch-icon">`, `<meta name="mobile-web-app-capable">` | missing | both | §A2; the Apple-prefixed meta alone triggers a Chrome deprecation warning |
| Service worker | missing | Android only (prompt + instant shell); iOS gains nothing material | two variants in §A5 |
| Install-hint UI | missing | both | `/today` card + 我的 row; §A6 |
| WeChat / QQ in-app detection → 「在浏览器打开」 | missing | both (mainland sharing happens in WeChat) | F9, §A6 |
| Standalone export fallback (`<a download>`) | missing | iPhone only | F8, WebKit 290847 |
| 404 for unknown `/assets/*`, `no-cache` for `sw.js` | missing (backend) | both | F4, §A4 |

- **Implication.** Ordered by value for a ≤10-friend circle: icons + manifest + links (one hour) give both platforms a real app icon and standalone window; the install hint and WeChat guidance decide whether friends actually find the feature; the SW is optional.
- **Confidence.** high.

### F3 — The CSP already allows a same-origin manifest and service worker; only inline registration is blocked
- **Claim.** No CSP change is required for Variant A or B, provided the SW is registered from an external script.
- **Evidence.**
  - `backend/wd/main.py:93–101`: `SECURITY_HEADERS` CSP = `default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'` — no `worker-src`, `child-src`, `manifest-src`; applied to every response by the middleware (`main.py:168–170`), pinned by `backend/tests/integration/test_health.py:53–54`.
  - MDN `worker-src` (accessed 2026-11-04): "specifies valid sources for Worker, SharedWorker, or ServiceWorker scripts" and "If this directive is absent, the user agent will first look for the child-src directive, then the script-src directive, then finally for the default-src directive" → resolves to `script-src 'self'` → same-origin `/sw.js` allowed.
  - MDN `manifest-src` (accessed 2026-11-04): "If this directive is absent, the user agent will look for the default-src directive" → `'self'` → `/manifest.webmanifest` allowed; icons are `img-src 'self'`.
  - `script-src 'self'` has no `'unsafe-inline'`, so `vite-plugin-pwa`'s `injectRegister: 'inline'` would be blocked; the trial build with `injectRegister: 'script-defer'` emitted `<script id="vite-plugin-pwa:register-sw" src="/registerSW.js" defer>` (external, 134 B) — verified in `…/scratchpad/quick/pwa-dist-sw/index.html`.
  - `Permissions-Policy: camera=(), microphone=(), geolocation=()` (`main.py:100`) does not affect `speechSynthesis` (no microphone).
- **Implication.** Keep `SECURITY_HEADERS` as is (and `test_health.py:53` untouched). If a SW is adopted, use `injectRegister: 'script-defer'` or the `virtual:pwa-register` module imported from `main.tsx` — never inline.
- **Confidence.** high.

### F4 — Cache-Control and MIME for the new root files; the `index.html` fallback for missing `/assets/*` is the real hazard
- **Claim.** `public, max-age=3600` on `/sw.js` is acceptable under the spec default, but a `no-cache` one-liner is cheap insurance; `.webmanifest` gets the right MIME; unknown `/assets/*` paths must become 404s before any SW precaches them.
- **Evidence.**
  - `backend/wd/main.py:252–260`: files under `assets/` → `public, max-age=31536000, immutable`; **every other existing dist file** (so `sw.js`, `registerSW.js`, `workbox-*.js`, `manifest.webmanifest`, icons) → `public, max-age=3600`; `index.html` → `no-cache`; any path that is not a file (including `/assets/<old-hash>.js`) falls through to `index.html` with status 200 (`:258–260`). `/api/*` is `no-store` (`:173–174`). Starlette's `FileResponse` adds `ETag`/`Last-Modified` (`.venv/.../starlette/responses.py:339–344`), so `no-cache` revalidates with 304s.
  - Service Workers spec, Update algorithm (w3c.github.io/ServiceWorker, accessed 2026-11-04): "If registration's update via cache mode is not 'all', or the force bypass cache flag is set, or registration is stale, set request's cache mode to 'no-cache'"; `RegistrationOptions`: `updateViaCache = "imports"` (default). MDN `register()`: under `'imports'` "the main script will always be updated from the network". web.dev service-worker-lifecycle: "Most browsers, including Chrome 68 and later, default to ignoring caching headers when checking for updates of the registered service worker script" and update checks run on "A navigation to an in-scope page" or functional events "unless there's been an update check within the previous 24 hours". Safari's handling was **not** verified here.
  - MIME: `.venv/bin/python -I -c "import mimetypes; mimetypes.init(files=[]); …"` → `manifest.webmanifest` = `application/manifest+json`, `sw.js` = `text/javascript` from Python 3.12's built-in table (no OS files needed, so Linux behaves the same); `X-Content-Type-Options: nosniff` is satisfied for the SW script.
  - Pinned behaviour: `backend/tests/integration/test_health.py:185–203` asserts `/` → `no-cache`, `/assets/app-abc123.js` → immutable, `/today` → SPA fallback; nothing pins the 1 h branch.
  - Hazard: a deploy restart during a client's SW install (69 fetches) can answer an old hashed name with `index.html` **200**; workbox precache stores 200s, so HTML would be cached under a `.js` URL until the next SW update. Today the same fallback turns a stale lazy chunk into a MIME error that the boundary catches (F1).
- **Implication.** Add two lines to `_mount_spa` (§A4): `no-cache` for `sw.js`/`registerSW.js`/`manifest.webmanifest`, and `ApiError("not_found")` for any `assets/*` path that is not a file; extend `test_health.py` accordingly. Neither changes the documented contract for `index.html` and `/assets/*`.
- **Confidence.** high for headers/MIME/test pins; medium for the Safari cache behaviour (unverified → hence the one-liner).

### F5 — `sips` rasterises SVG on this Mac; a dependency-free icon recipe is verified
- **Claim.** Contrary to the working assumption, `sips -s format png -z N N file.svg` renders the vector correctly at any size on macOS 26 (sips-316); `qlmanage` is not usable; no other rasteriser is installed.
- **Evidence.** `which`: `rsvg-convert`, `magick`, `convert`, `inkscape`, `cairosvg` → missing; `/usr/bin/sips`, `/usr/bin/qlmanage`, node 22 present. Runs in `…/scratchpad/quick/icons-probe/`: `favicon.svg` → `icon-192.png` 5,257 B, `icon-512.png` 18,347 B, `icon-1024.png` 48,279 B (all "PNG image data, N x N, 8-bit/color RGBA"); viewed: crisp anti-aliased rounded square + W at 192 and 1024 (true vector scaling, not an upscaled 64 px bitmap). A hand-written full-bleed variant (`icon-maskable.svg`, W scaled 0.6 inside a full square) rendered to `icon-maskable-192.png` 2,949 B, `icon-maskable-512.png` 10,939 B, `apple-touch-icon.png` (180) 2,641 B — `transform` honoured. `qlmanage -t -s 512` produced a 512 canvas with the icon drawn at its intrinsic 64 px in the corner (unusable without editing the SVG's width/height). npm registry is reachable (`npm view`): `@resvg/resvg-js` 2.6.2, `sharp` 0.35.5, `@capacitor/assets` 4.0.0, `pwa-asset-generator` 8.1.7 exist as fallbacks for a Linux box.
- **Implication.** Commit ~40 KB of PNGs generated by the five `sips` commands in §A3; no devDependency, no network. The rounded-corner favicon (transparent corners) is right for `purpose: any`; the maskable/apple-touch icons must be the opaque full-bleed variant (iOS paints transparent corners black; Android masks need the 80 % safe zone).
- **Confidence.** high (reproduced; outputs inspected).

### F6 — `vite-plugin-pwa@2.0.0` works with Vite 8.3.4 (verified in a scratch copy) — with a sizeable dependency cost
- **Claim.** Variant B is technically available today; it adds ~20 KB of runtime files and +338 lock-file packages.
- **Evidence.** `npm view vite-plugin-pwa` → `2.0.0`, `peerDependencies.vite: '^3.1.0 || … || ^8.0.0'`, `workbox-build ^7.4.1`. Trial in `…/scratchpad/quick/pwa-sw-trial/` (rsync of `frontend/` without `node_modules`, `npm ci`, `npm i -D vite-plugin-pwa@2.0.0`, config `vite.config.pwa.ts` as in §A5): `vite v8.3.4 … ✓ built in 538ms`, `PWA v2.0.0 mode generateSW precache 69 entries (550.35 KiB)`, files `sw.js` 4,470 B, `workbox-9c191d2f.js` 15,112 B, `registerSW.js` 134 B (`navigator.serviceWorker.register('/sw.js', { scope: '/' })` on `load`); `sw.js` contains `self.skipWaiting(), s.clientsClaim(), s.precacheAndRoute([...])` and the denylist literal `[/^\/api(\/|$)/,/^\/media(\/|$)/]`. Footprint: lock `packages` 124 → 462, `node_modules` top-level 80 → 286 entries, 109 MB → 173 MB (trial `node_modules` deleted afterwards). Output dir 732 KB vs 704 KB today. The checkout was not modified (`package.json`/lock untouched).
- **Implication.** If B is chosen, `deploy/install.sh:72` (`npm ci`) will install the extra packages on the server; `tsconfig.json` `types` needs `"vite-plugin-pwa/client"` only when the `virtual:pwa-register` module is used.
- **Confidence.** high.

### F7 — Installability rules per platform (external facts the code must satisfy)
- **Claim.** iPhone needs no SW at all; Android Chrome installs from the menu without a SW but shows the automatic prompt only with a fetch handler; iOS uses `apple-touch-icon` first and manifest icons second.
- **Evidence.**
  - WebKit blog "WebKit Features in Safari 26.0" (webkit.org/blog/17333, accessed 2026-11-04): "By default, every website added to the Home Screen opens as a web app." … "If the user prefers to add a bookmark for their browser, they can disable 'Open as Web App' when adding to Home Screen." … "There are now zero requirements for 'installability' in Safari."
  - Chrome blog "Revisiting Chrome's installability criteria" (developer.chrome.com/blog/update-install-criteria, accessed 2026-11-04): "we have removed the requirement to have a service worker that implements the fetch() method for installation from the menu, since version 108 on mobile and 112 on Desktop." and "For now the algorithm that displays the install prompt still requires the presence of a fetch() handler". web.dev install-criteria (accessed 2026-11-04): manifest needs `short_name` or `name`, icons "must include a 192px and a 512px icon", `start_url`, `display` ∈ fullscreen/standalone/minimal-ui/window-controls-overlay, `prefer_related_applications` absent or false, "Be served over HTTPS".
  - WebKit blog "New WebKit Features in Safari 15.4" (webkit.org/blog/12445, accessed 2026-11-04): "Safari and iOS use manifest-declared icons when there is no apple-touch-icon defined in the HTML head, and when the manifest file code for declaring the icons either omits the 'purpose' key or includes 'purpose': 'any'." and "Defining icons by using apple-touch-icon takes precedence over manifest-declared icons".
  - Chrome deprecation of the Apple-only meta: search results (developer.chrome.com "Add to Homescreen" archive; GitHub PRs replacing the tag) state Chrome warns when only `apple-mobile-web-app-capable` is present and asks for `mobile-web-app-capable`.
- **Implication.** Variant A fully serves iPhone and Android menu-install; the install hint on Android must show manual instructions unless Variant B is adopted (then `beforeinstallprompt` can drive an 「安装」 button). Domestic Android browsers are the android slice's call. HTTPS is a prerequisite for every install path and for the SW (deployment slice).
- **Confidence.** high for the quoted vendor statements; medium that the Chrome prompt rule is unchanged in late 2026 (the post is from 2023; android slice to re-verify).

### F8 — Standalone-mode quirks that touch existing code
- **Claim.** Four behaviours change or break in a home-screen window; two need code, two are already fine.
- **Evidence.**
  - *Separate storage on iOS* → one extra login. WWDC23 notes (wwdcnotes.com, "What's new in web apps", accessed 2026-11-04): iOS/iPadOS standalone web apps launch "with separate cookies and storage from the browser"; whether Safari copies the session cookie at add-time on iOS 26 is not stated for iOS (the "Safari copies the cookies" sentence is unqualified) → plan for one login. After that the session cookie is `Max-Age` 30 days and slid once per day (`backend/wd/config.py:78` `session_days = 30`; `backend/wd/deps.py:165–172`; `backend/tests/integration/test_deps.py:99` `max-age=2592000`). Per-context localStorage means the grade outbox `wd.pendingGrades` (`StudyPage.tsx:54,89–105,184–189`) and prefs start empty in the app context — harmless. Android Chrome WebAPKs share Chrome's profile, so no extra login is expected there (unverified on domestic browsers).
  - *`<a download>` export*: `SettingsPage.tsx:597–602` uses `<a href="/api/account/export?format=csv|json" download>`; the server answers `Content-Disposition: attachment` (`backend/wd/routers/account.py:201`). WebKit bug 290847 (bugs.webkit.org, accessed 2026-11-04) "File downloads and inline file display in iOS 18.4 Web App lead to navigation-less state", status NEW, reported 2025-04-01: the "Open in…" sheet "prevents further navigation within the app, forcing users to force-close and relaunch". Fallback: when `isStandaloneDisplay()`, `fetch()` the same URL (cookie + `X-WD-Request` are same-origin), build a `File`, and `navigator.share({ files })` when `navigator.canShare?.({ files })`, else copy to clipboard (`zh.common.copy/copied` exist). `<input type="file">` import (`SettingsPage.tsx:609`) has no known standalone issue.
  - *speechSynthesis*: manual 发音 buttons run inside gestures (F1). The auto-pronounce effect (`StudyPage.tsx:206–212`) fires on card change; the first card after a cold launch is not gesture-initiated and may stay silent on iOS until the first tap — pre-existing, identical in Safari, worth a note in the QA checklist, no PWA-specific change.
  - *Polling*: visibility-gated (F1) — an app sent to the background stops polling and resumes on return; nothing to do.
  - *Back navigation*: 返回 controls exist on `StudyPage.tsx:617`, `BatchPage.tsx:75`, `ScreenRunPage.tsx:162`; `WordDetailPage` and `AddWordsPage` rely on browser back/TabBar. iOS standalone windows have no browser chrome; whether the edge-swipe back gesture is available was not verified → device test.
  - *External link*: `WordImage.tsx:70` `target="_blank" rel="noopener noreferrer"` (image source) opens an in-app browser sheet in iOS standalone — acceptable.
- **Implication.** Budget ~2 h for the export fallback (iPhone only) and add the three device checks to `docs/qa-frontend.md`.
- **Confidence.** high for the code facts and the WebKit bug; medium for the cookie-copy behaviour on iOS 26.

### F9 — WeChat / QQ in-app browsers need a detection + 「在浏览器打开」 path
- **Claim.** Links shared in mainland chats open in WeChat's/QQ's WebView, which offers no Add-to-Home-Screen and no install prompt; the hint must detect them from the UA and ask the user to open the system browser.
- **Evidence.** UA contains `MicroMessenger/<ver>` on both iPhone and Android (gist.github.com/Natumsol/1d064cc8735bf7ccdc16; cnblogs.com/68xi/p/8552898.html — accessed 2026-11-04; the idiom `/micromessenger/i.test(navigator.userAgent)`); mobile QQ's UA carries ` QQ/<ver>` (community sources; medium confidence). Nothing in the repo handles either (F2). `display-mode` detection is standard: `matchMedia('(display-mode: standalone)').matches || navigator.standalone === true`; the vitest setup already polyfills `matchMedia` to `matches:false` (`frontend/src/test/setup.ts:31–43`), so the component is testable without extra mocks.
- **Implication.** Put the UA logic in a DOM-free `src/utils/platform.ts` with fixtures in `platform.test.ts`; keep the WeChat card non-dismissible (nothing else works there) and the other channels dismissible for 14 days via `useLocalPref`.
- **Confidence.** medium-high.

### F10 — Constraints new copy/CSS/tests must satisfy, and the verified baseline
- **Claim.** New Chinese strings live only in `zh.ts` and must be mirrored verbatim in FRONTEND.md §8; the current gates pass (with one flaky test); build facts are known.
- **Evidence.**
  - `frontend/scripts/check-copy.mjs:30–33` and `src/i18n/zh.test.ts:44–53`: CJK allowed in `.tsx` only under `src/i18n/`; the glossary term U+5355 U+8BCD U+672C is forbidden everywhere (use 生词库). `zh.test.ts:67–80` requires the `export const zh = {…} as const;` block to match `docs/FRONTEND.md` §8 **line for line** (trimmed, non-empty lines); `zh.contract.test.ts:61–83` evaluates both tables and diffs keys and values. §8 starts at `docs/FRONTEND.md:204`, `settings:` is at `:275`, the block ends at `:302` (`} as const;`). `backend/tests/unit/test_docs_contract.py:262–267` only checks P0 keys exist.
  - `src/styles/css-contracts.test.ts` pins only the searchbox and settings `input[type=time|number]` rules — new CSS for a hint card is unconstrained.
  - Baseline run (this session, `frontend/`): `npm run lint` → `copy check OK`; `npm run typecheck` → clean (3.7 s); `npx vitest run` → 39 files, **294 passed / 1 failed** — `src/auth/AuthContext.test.tsx:146` (`findByText('login-page')` timeout), which passed 3/3 when re-run alone → flaky under the parallel full run, not a regression; `npm run build -- --outDir …/scratchpad/quick/pwa-dist` → `✓ built in 294ms`, dist 704 KB (assets 696 KB; `index-CsasxgTd.js` 302.86 kB / 99.61 kB gzip; `index-CaqBZ0AA.css` 17.7 kB), `public/favicon.svg` copied to the dist root (so `public/manifest.webmanifest`, `public/icons/*`, `public/apple-touch-icon.png` will be too). `vite.config.ts:32–38` (`outDir dist`, `assetsDir assets`, no sourcemaps); `package.json:31–33` (vite ^8.3.4, vitest ^5.0.4).
- **Implication.** Regression scope for this slice: `npm run lint && npm run typecheck && npm test && npm run build` (≈ 15 s wall) plus `pytest backend/tests/integration/test_health.py -k spa` for the backend one-liners; `test_deploy_files.py:359–365` pins `install.sh`'s build/prune commands, so do not touch snapshot retention.
- **Confidence.** high.

### F11 — Manifest design choices
- **Claim.** `start_url: "/today"`, `scope: "/"`, `id: "/"`, `display: "standalone"`, colours from the light tokens, no `orientation`.
- **Evidence / reasoning.** `routes.tsx:76` makes `/` a client-side `Navigate` to `/today`; `/today` is guarded by `RequireAuth` → `/login?next=%2Ftoday` (`AuthContext.tsx:176–179,195–202`) and `RequireOnboarded` → `/welcome` (`:205–210`), so launching at `/today` behaves identically to `/` minus one redirect and keeps the manifest independent of the root alias. `scope` must be `/` because `/login`, `/welcome`, `/settings` and `/api/account/export` all have to stay inside the app window (out-of-scope navigations open browser UI). An explicit `id` keeps the app identity stable if `start_url` ever gains a query. Colours: `--bg #ffffff` (`tokens.css:9`) for `background_color`/`theme_color` matching `index.html:7`; the dark palette (`#121620`, `tokens.css:75,93`) cannot be expressed in a manifest, the per-scheme `<meta theme-color>` already overrides it at runtime. `orientation` omitted: the layout is responsive at 768 px (`AppLayout.tsx:17`), iPad/desktop users should rotate freely, and iOS ignores the member anyway. `lang: "zh-CN"` matches `<html lang>`.
- **Confidence.** high (design).

### F12 — Interplay with the atomic API+SPA release and the two-snapshot retention
- **Claim.** Each `wd serve` process serves exactly one snapshot, so a SW never sees cross-snapshot paths; the only skew channels are an open tab/app across a deploy and the 200-HTML fallback (F4).
- **Evidence.** `deploy/install.sh:134–139`: publish `<sha>.new` → `<sha>`, swap the `frontend` symlink with one `mv -T`, prune to the two newest (`ls -1t | tail -n +3 | xargs -r rm -rf --`), all after the unit is stopped; `main.py:231–233` resolves `WD_FRONTEND_DIST` at startup; `docs/DEPLOY.md:20–21`. `index.html` is `no-cache` today, so a cold launch without a SW always fetches the new hashed names. With Variant B the old shell is served from the precache until the SW update completes (checked on every navigation, F4); `registerType: 'autoUpdate'` forces `skipWaiting`+`clientsClaim` (vite-pwa docs, accessed 2026-11-04: "the plugin will force workbox.clientsClaim and workbox.skipWaiting to true") but "Automatic reload is not automatic page reload, you will need to use … registerSW({ immediate: true })" from `virtual:pwa-register`; `cleanupOutdatedCaches` is on by default ("We strongly recommend you to NOT deactivate the option"). Without the reload, a page that stays open after the new SW claims it loads old chunk names that neither the new precache nor the new snapshot has → `index.html` 200 → MIME error → boundary reload (F1).
- **Implication.** Variant B should use the virtual module with `immediate: true` (reload on `controllerchange`; mid-study reloads are safe because grades are server-acknowledged or in `wd.pendingGrades`), or `registerType: 'prompt'` with a 「有新版本，点击刷新」 toast; and the `/assets/*` 404 fix (F4) should land with it. No change to `install.sh` is needed.
- **Confidence.** high.

## Proposed artefacts (nothing below was applied to the checkout)

### A1 — `frontend/public/manifest.webmanifest` (both)
```json
{
  "id": "/",
  "name": "word-Dance",
  "short_name": "word-Dance",
  "description": "每天几个词，稳稳记住",
  "lang": "zh-CN",
  "dir": "ltr",
  "start_url": "/today",
  "scope": "/",
  "display": "standalone",
  "background_color": "#ffffff",
  "theme_color": "#ffffff",
  "categories": ["education"],
  "prefer_related_applications": false,
  "icons": [
    { "src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png" },
    { "src": "/icons/icon-maskable-192.png", "sizes": "192x192", "type": "image/png", "purpose": "maskable" },
    { "src": "/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable" }
  ],
  "shortcuts": [
    { "name": "开始学习", "url": "/study" },
    { "name": "生词库", "url": "/bank" }
  ]
}
```
Notes: `shortcuts` are Android-only and optional; `description`/`shortcuts` may contain Chinese because `public/` is outside the copy lint's scope (`check-copy.mjs:11` walks `src/`, `zh.test.ts:14` globs `src/**` + `/index.html`). Icons live under `/icons/` on purpose: `/assets/` is immutable-cached (`main.py:253`), while icons should be refreshable (1 h).

### A2 — `frontend/index.html` additions (both; insert after line 13)
```html
    <meta name="mobile-web-app-capable" content="yes" />
    <link rel="manifest" href="/manifest.webmanifest" />
    <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
```
Keep lines 7–8 (per-scheme `theme-color`), 11–13 (Apple metas: still needed for iOS ≤ 25 standalone and the status-bar style) and 14 (`favicon.svg`). Optional: `<link rel="icon" type="image/png" sizes="32x32" href="/icons/icon-32.png">` for engines without SVG favicons (not needed for WeChat's XWeb or current browsers).

### A3 — Icon generation recipe (runs on this Mac, verified; both — the 180 px file is iPhone-critical)
```sh
cd /Users/sqin/word-dance/frontend
mkdir -p public/icons
cat > public/icon-maskable.svg <<'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">
  <rect width="64" height="64" fill="#3b5bdb"/>
  <g transform="translate(12.8 12.8) scale(0.6)">
    <path d="M14 20l6 24h5l5-16 5 16h5l6-24h-5.5l-3.6 16-4.9-16h-4.2l-4.9 16-3.6-16z" fill="#ffffff"/>
  </g>
</svg>
EOF
sips -s format png -z 192 192 public/favicon.svg       --out public/icons/icon-192.png            # 5,257 B
sips -s format png -z 512 512 public/favicon.svg       --out public/icons/icon-512.png            # 18,347 B
sips -s format png -z 192 192 public/icon-maskable.svg --out public/icons/icon-maskable-192.png   # 2,949 B
sips -s format png -z 512 512 public/icon-maskable.svg --out public/icons/icon-maskable-512.png   # 10,939 B
sips -s format png -z 180 180 public/icon-maskable.svg --out public/apple-touch-icon.png          # 2,641 B, opaque
```
Why the second SVG: `favicon.svg` has transparent rounded corners (fine for `purpose: any`); maskable icons need the glyph inside the central 80 % safe zone on an edge-to-edge background, and iOS fills transparent apple-touch-icon pixels with black, so both derive from the full-bleed variant (brand `#3b5bdb` = `--brand`, `tokens.css:14`). Fallbacks if ever needed on Linux: `npx --yes @vite-pwa/assets-generator --preset minimal-2023 public/favicon.svg` (sharp-based, network) or a 10-line node script with `@resvg/resvg-js` 2.6.2. `qlmanage` must not be used (F5).

### A4 — Backend one-liners in `backend/wd/main.py` `_mount_spa` (both; optional for Variant A, required for B)
```python
            if candidate.is_file():
                if path.startswith("assets/"):
                    cache = "public, max-age=31536000, immutable"
                elif path in ("sw.js", "registerSW.js", "manifest.webmanifest"):
                    cache = "no-cache"                      # update checks must see a new SW/manifest at once
                else:
                    cache = "public, max-age=3600"
                return FileResponse(candidate, headers={"Cache-Control": cache})
            if path.startswith("assets/"):                  # a hashed chunk that no longer exists is a 404, never index.html
                raise ApiError("not_found")
```
Add two assertions to `test_health.py::test_spa_serves_built_files_with_cache_policy` (`/assets/missing.js` → 404; `/sw.js` → `no-cache`) and one sentence to `docs/DEPLOY.md` §4's `WD_FRONTEND_DIST` row. Effect on Variant A: stale-chunk failures turn into clean 404s (the boundary already handles them); on Variant B: workbox can never precache HTML under a script URL (F4/F12).

### A5 — Service-worker variants (Android-driven; iPhone gains nothing material)
**Variant A — no service worker (recommended first).** Ship A1–A3 (+A4). Behaviour: iOS 26 opens the site as a web app with our icon/name; iOS ≤ 25 does the same via the existing `apple-mobile-web-app-capable`; Android Chrome ≥ 108 installs from ⋮ → 「添加到主屏幕 / 安装应用」 (manifest only, F7), no `beforeinstallprompt`, Chrome's default offline page when offline; updates are immediate because `index.html` is `no-cache`; zero new dependencies, no interaction with snapshots. Code the install hint so it never depends on `beforeinstallprompt` (show instructions when the event has not fired).

**Variant B — `vite-plugin-pwa` 2.0.0, `generateSW` (verified build, F6).** `frontend/vite.config.ts`:
```ts
import { VitePWA } from 'vite-plugin-pwa';
// plugins: [react(), VitePWA({...})]
VitePWA({
  registerType: 'autoUpdate',            // forces skipWaiting + clientsClaim (vite-pwa docs)
  injectRegister: null,                  // we register from main.tsx (below) — never 'inline' (CSP script-src 'self')
  manifest: false,                       // keep the hand-written public/manifest.webmanifest (A1)
  includeAssets: ['favicon.svg', 'apple-touch-icon.png', 'icons/*.png'],
  workbox: {
    globPatterns: ['**/*.{js,css,html,svg,png,webmanifest}'],
    navigateFallback: '/index.html',
    navigateFallbackDenylist: [/^\/api(\/|$)/, /^\/media(\/|$)/],   // API + cookie-gated images are never answered by the shell
    runtimeCaching: [],                  // no runtime cache: /api stays no-store, /media stays per-user
    cleanupOutdatedCaches: true,
    clientsClaim: true,
    skipWaiting: true,
  },
}),
```
`frontend/src/main.tsx` (+ `"types": ["vite/client", "vite-plugin-pwa/client"]` in `tsconfig.json`):
```ts
import { registerSW } from 'virtual:pwa-register';
registerSW({ immediate: true });        // reload when the new SW takes control (F12); or registerType:'prompt' + a toast
```
Trade-offs: + `beforeinstallprompt` on Android Chrome (fetch handler present) → a real 「安装」 button; + instant shell on cold launch (550 KiB precached) and an in-app error state instead of the browser's offline page; − a one-launch version-skew window after each deploy plus an automatic reload (or a refresh toast); − `+338` lock packages / +64 MB `node_modules` that `install.sh` installs on the server; − `docs/FRONTEND.md`/`DEPLOY.md` must document the SW and the `no-cache` rule; − the `/assets/*` 404 fix (A4) becomes mandatory. iOS: Safari also runs the SW, but nothing above changes the iPhone experience except the precached shell.

### A6 — Install-hint component sketch (both) and the copy to add
`src/utils/platform.ts` (DOM-free, unit-tested with UA fixtures):
```ts
export type InstallChannel = 'standalone' | 'wechat' | 'qq' | 'ios' | 'android' | 'desktop';
export const isWeChat = (ua: string) => /MicroMessenger/i.test(ua);
export const isQQ = (ua: string) => /\bQQ\/\d/i.test(ua) && !isWeChat(ua);
export const isIOS = (ua: string, touchPoints = 0) => /iPhone|iPad|iPod/i.test(ua) || (/Macintosh/i.test(ua) && touchPoints > 1);
export const isAndroid = (ua: string) => /Android/i.test(ua);
export function installChannel(ua: string, standalone: boolean, touchPoints = 0): InstallChannel {
  if (standalone) return 'standalone';
  if (isWeChat(ua)) return 'wechat';
  if (isQQ(ua)) return 'qq';
  if (isIOS(ua, touchPoints)) return 'ios';
  if (isAndroid(ua)) return 'android';
  return 'desktop';
}
export function isStandaloneDisplay(): boolean {
  try {
    return window.matchMedia('(display-mode: standalone)').matches || (navigator as Navigator & { standalone?: boolean }).standalone === true;
  } catch { return false; }
}
```
`src/components/layout/InstallHint.tsx` (rendered by `AppLayout` above `<Outlet/>` only on `/today`, never on bare routes; plus a 「添加到主屏幕」 row in `SettingsPage` 账号 section that opens a `Sheet` with the same text so it stays discoverable after dismissal):
```tsx
export function InstallHint() {
  const channel = installChannel(navigator.userAgent, isStandaloneDisplay(), navigator.maxTouchPoints);
  const [dismissedAt, setDismissedAt] = useLocalPref<number | null>('wd.installHintDismissedAt', null);
  const deferred = useBeforeInstallPrompt();   // Variant B only: keeps the BeforeInstallPromptEvent; null otherwise
  if (channel === 'standalone' || channel === 'desktop') return null;
  if (channel !== 'wechat' && channel !== 'qq' && dismissedAt && Date.now() - dismissedAt < 14 * 86_400_000) return null;
  const line = channel === 'wechat' ? zh.install.wechat : channel === 'qq' ? zh.install.qq : channel === 'ios' ? zh.install.ios : zh.install.android;
  return (
    <section className="card install-hint" role="note" aria-label={zh.install.title}>
      <h2>{zh.install.title}</h2>
      <p className="muted">{zh.install.body}</p>
      <p>{line}</p>
      <div className="row">
        {channel === 'android' && deferred && <Button size="sm" onClick={() => void deferred.prompt()}>{zh.install.androidInstall}</Button>}
        {channel !== 'wechat' && channel !== 'qq' && <Button size="sm" variant="secondary" onClick={() => setDismissedAt(Date.now())}>{zh.install.later}</Button>}
      </div>
    </section>
  );
}
```
Copy to add — **identically** to `src/i18n/zh.ts` (after the `history:` entry, before `settings:` at `:74`) and to `docs/FRONTEND.md` §8 (before `:275`), no CJK in the `.tsx`, no forbidden term:
```ts
  install: { title: '添加到主屏幕', body: '像 App 一样全屏打开，下次从桌面直接进入',
             ios: '点击 Safari 的「分享」按钮（或地址栏旁的「⋯」菜单），选择「添加到主屏幕」',
             android: '在浏览器菜单中选择「添加到主屏幕」或「安装应用」', androidInstall: '安装',
             wechat: '微信内无法添加到主屏幕：点击右上角「⋯」，选择「在浏览器打开」', qq: 'QQ 内无法添加到主屏幕：点击右上角菜单，选择「在浏览器打开」',
             later: '以后再说', updateReady: '有新版本，点击刷新' },
```
Tests: `src/utils/platform.test.ts` (UA fixtures: iPhone Safari, iPhone WeChat, Android Chrome, Android WeChat, mobile QQ, desktop; standalone flag), `src/components/layout/InstallHint.test.tsx` (channel → text; dismissal persists through `localStorage`; hidden when `matchMedia` reports standalone — override `window.matchMedia` per test like `setup.ts:31–43`). `useBeforeInstallPrompt` is a 15-line hook (`window.addEventListener('beforeinstallprompt', e => { e.preventDefault(); set(e) })`).

### A7 — Build-and-check steps actually run in this session
- `cd frontend && npm run build -- --outDir /private/tmp/claude-501/-Users-sqin-word-dance/729429d5-a7a1-4def-84e7-dc3ba571c437/scratchpad/quick/pwa-dist` → `✓ built in 294ms`; 704 KB; root = `index.html` (1,026 B), `favicon.svg`, `assets/` (66 files; largest `index-CsasxgTd.js` 302.86 kB → 99.61 kB gzip).
- `npm run lint` → OK; `npm run typecheck` → OK; `npx vitest run` → 294/295 (the AuthContext case is flaky, passes alone 3/3).
- Scratch trial of Variant B (`…/scratchpad/quick/pwa-sw-trial/`, config kept as `vite.config.pwa.ts`; output `…/scratchpad/quick/pwa-dist-sw/`): see F6. The checkout was never modified; no server was started; no live data touched.
- Icon probe (`…/scratchpad/quick/icons-probe/`): see F5.
- Regression scope for the real change: `npm run lint && npm run typecheck && npm test && npm run build` (frontend) and `.venv/bin/pytest -q backend/tests/integration/test_health.py backend/tests/unit/test_docs_contract.py` (backend one-liners + doc mirrors).

## Recommendations (effort in hours; platform tag)

| # | Item | Platform | Effort |
|---|---|---|---|
| R1 | A1 manifest + A2 `index.html` links/meta | both | 0.5 h |
| R2 | A3 icons via `sips` (+ `icon-maskable.svg` source), commit ≈ 40 KB PNG | both (`apple-touch-icon` is the iPhone-critical piece) | 0.5 h |
| R3 | A4 backend one-liners + `test_health.py` assertions + DEPLOY §4 sentence | both | 1 h |
| R4 | A6 `platform.ts` + `InstallHint` + 我的 row/sheet + `zh.install` copy mirrored in FRONTEND §8 + tests | both (WeChat/QQ guidance is the mainland-critical piece) | 3–4 h |
| R5 | Standalone export fallback (`fetch` → `navigator.share({files})` → clipboard) behind `isStandaloneDisplay()` | iPhone only | 1.5–2 h |
| R6 | Device QA + `docs/qa-frontend.md` rows: iPhone (iOS 26 and one iOS 18 device), domestic Android (Chrome + Huawei/Xiaomi browser), WeChat on both; verify login-once, icon, status bar, export, auto-pronounce first card, back navigation | both | 2 h |
| R7 | Variant B (`vite-plugin-pwa`, `registerSW`, tsconfig types, FRONTEND/DEPLOY docs, re-run R6) | Android mainly | 4–6 h |

Totals: **Variant A (R1–R6) ≈ 8.5–10 h (≈ 1.2 person-days)**; **with Variant B ≈ 12.5–16 h (≈ 2 person-days)**. Suggested order: R2 → R1 → R3 → R4 → R5 → R6, ship, then decide R7 from the android slice's verdict on `beforeinstallprompt`/domestic browsers. Prerequisite from the deployment slice: HTTPS on the public hostname (required for install on Android and for any SW).

## Open questions

1. iOS 26: does Safari copy the `wd_session` cookie into the Home-Screen app at add-time (no extra login) or not (one login)? Vendor text is unqualified for iOS; needs one device test.
2. Does WebKit 290847 (`<a download>` → navigation-less "Open in…" sheet) still reproduce on iOS 26? The bug was NEW as of 2025-04-08; if fixed, R5 can be dropped.
3. Is a back gesture available in iOS standalone windows? `WordDetailPage`/`AddWordsPage` have no 返回 control; if not, add one (≈ 0.5 h).
4. Android slice: does current Chrome still withhold `beforeinstallprompt` without a fetch handler (2023 statement), and do Huawei/Xiaomi/UC/QQ browsers honour the manifest and maskable icons? This decides whether R7 is worth its dependency cost.
5. Safari's HTTP-cache handling for the SW script (`updateViaCache`) was not verified; the `no-cache` one-liner (R3) makes the question moot.
6. Status bar: keep `apple-mobile-web-app-status-bar-style=default` (opaque, follows `theme-color`?) or switch to `black-translucent` with `--safe-top` padding on phone pages (`.page` has none today)? Device test in dark mode.
7. Splash colour for dark-mode users: `background_color #ffffff` (matches light tokens, white flash in dark mode) vs brand `#3b5bdb`; a manifest cannot express both schemes.
8. Is the +338-package footprint of Variant B acceptable for `install.sh`'s `npm ci` on the server, and should `workbox-*.js` be matched into the immutable branch (it is content-hashed)?
