# Evidence for `docs/QUICK_DEPLOY_AND_MOBILE.md` (collected 2026-11-04)

Question answered: how to deploy word-Dance quickly for a circle of ≤ 10 invited friends on mainland-China phones, and how to plan iOS and Android apps for them. Anthropic policy / model-licensing / domestic-model replacement questions were explicitly deferred by the owner and are not analysed here; only technical facts about the `claude -p` runner are recorded.

Pipeline: 10 research slices (5 code, 5 web) → one adversarial verifier per slice (code slices verified by execution on throwaway instances and a read-only copy of the live DB; web slices re-checked against primary sources) → 3 independent plans → 3 judges (owner effort, friends' experience, engineering correctness) → synthesis in the main document. Code slices cite `file:line` at `main @ 9ab13a5`; web slices cite URL + access date.

## facts/ — research digests (English)

| File | Scope | Claims verified → confirmed / corrected / unverifiable |
|---|---|---|
| `facts/deploy.md` | fresh Ubuntu 24.04 VPS runbook with `deploy/install.sh`, Mac data migration, Cloudflare-Tunnel variant | 10 → 9 / 1 / 0 |
| `facts/security.md` | what protects a ≤ 10-friend circle today, lockout/throttle arithmetic, AI budget and prewarm costs | 10 → 8 / 2 / 0 |
| `facts/pwa.md` | home-screen installability gaps and the exact manifest/icon/cache-header patch | 10 → 7 / 2 / 1 |
| `facts/capacitor.md` | Capacitor modes against this backend; remote-shell step list | 10 → 6 / 4 / 0 |
| `facts/reminders.md` | daily-reminder channels per phone platform; webhook defects | 10 → 8 / 2 / 0 |
| `facts/hosting.md` | regions, prices, ICP/DNS/domain facts, Cloudflare Tunnel and Tailscale reachability | 10 → 6 / 4 / 0 |
| `facts/ios.md` | Apple enrolment, TestFlight paths, Xcode, iOS home-screen behaviour | 10 → 8 / 2 / 0 |
| `facts/android.md` | sideload vs stores, Google developer verification, HarmonyOS NEXT, WebView TTS, Web Push | 10 → 6 / 4 / 0 |
| `facts/captool.md` | Capacitor 8.6/9 requirements, local notifications, CVE pin, toolchain sizes | 10 → 9 / 1 / 0 |
| `facts/clivps.md` | Claude CLI on a Linux VPS: install, credential wiring, `--bare`, classifier gaps | 9 → 9 / 0 / 0 |

Totals: 99 load-bearing claims checked — 76 confirmed, 22 corrected (none reversed the slice's conclusion), 1 unverifiable, 0 refuted.

## verify/ — adversarial verification reports

One per slice (`verify/<slice>.md`): verdict per claim with the commands run or sources read, plus "omissions / new findings" (e.g. the Enterprise login's fail-closed managed-settings failures in the live ledger, the registration throttle counting failed invite attempts, `sqlite3` needing `.timeout` for the unlock statement, Server酱³ answering HTTP 200 on error, Capacitor's origin-exact Android bridge, CVE-2026-103922, Lighthouse's once-per-instance IP swap, DNSPod's 600 s TTL floor).

## Plans and judgements

- `design-D1-fast.md` — "fastest credible path" (zero code before the first invite; pilots on day 2).
- `design-D2-solid.md` — "solid small-circle service in a week" (same architecture plus the cheap verified patches, watch cron, drills).
- `design-D3-apps.md` — "apps on purpose" (web circle + Capacitor remote shell for iOS/Android in parallel; the app spec the synthesis adopts as a gated phase).
- `judge-J1-owner.md`, `judge-J2-friends.md`, `judge-J3-eng.md` — scores (D1 47/48/44, D2 44/49/45, D3 38/43/40 out of 60), factual errors found in the plans (all corrected in the main document), grafts and blind spots.

Scratch artefacts (throwaway instances, probes, built `pwa-dist`, `live-copy.db`) stayed under the session scratchpad and were not archived.
