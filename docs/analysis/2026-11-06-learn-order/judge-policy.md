# Judge — ordering policy: frequency-purist vs pedagogy-first · 2026-11-06

Inputs: `FACTS.md`; `policy-frequency-purist.md` (+ `sim-frequency-purist/`); `policy-pedagogy-first.md` (+ `sim-pedagogy-first/`);
the read-only live copy (`…/scratchpad/deploy/precheck/word-dance.db`, `mode=ro&immutable=1`, 9,618 words, schema 13).
Judge simulation: `sim-judge/judge.py` → `sim-judge/judge_results.txt` (run with `/Users/sqin/word-dance/.venv/bin/python -I judge.py`,
≈ 20 s). Every number below comes from that run unless marked "doc" (quoted from a proposal and re-verified). Nothing in the
repository or the live data directory was touched.

## 0 Verdict

**Winner: `frequency-purist`, 42 : 39**, on condition of the must-fix list in §4 — three of whose items are pedagogy-first ideas.

| criterion | frequency-purist | pedagogy-first |
|---|---|---|
| (a) outcome for a 小学生 (first 30 / 100 / 300 cards) | **5** | **8** |
| (b) outcome for a 初中生 incl. the 381 上海词组 | **6** | **8** |
| (c) no regression for adults (cet4 / cet6) | **7** | **6** |
| (d) determinism and explainability | **9** | **6** |
| (e) rule-set size and maintenance | **9** | **4** |
| (f) robustness to missing data | **6** | **7** |
| **sum** | **42** | **39** |

Pedagogy-first wins both learner-outcome criteria by a clear margin; the purist wins adults, explainability and rule-set size and
is within one point on robustness. The deciding fact is *why* each loses. The purist's learner gap comes from three specific,
measured defects — the month `may` swallowed by the modal list (小学 card 577 while the other months sit at 217–285), `is`/`am`
as the last 小学 cards (600 / 595, garbage BNC 24648), and eight adverbs/particles among the first 30 cards (`not up so out now
how then also`) — each of which pedagogy-first fixes with a rule that costs 19 lemmas and no number. Pedagogy-first's deficits on
(c)–(e) are structural: five windows, four cap constants, five band midpoints, eight sub-keys (29 numeric tunables, 54 curated
lemmas, nine rules), and they cannot be removed without turning it into the purist. Purist + the three grafts, measured in §3:
小学 first 30 = 0 grammar words and 2 adverbs, months 241–252 and weekdays 340–346 in calendar order, `be am are is` 523–526;
初中 词组 11 in the first 50, 42 in the first 200; CET-4 first-100 overlap with today 90/100 — with a two-sentence explanation
and 16 + 19 lemmas as the only constants.

## 1 What was verified

* Both proposals' scripts re-run from their directories; outputs match their documents (`results.txt`, `results.md`).
* `judge.py` re-implements purist R1–R5 independently (the proposal's script executes at import time, so it was not imported)
  and reproduces the proposal bit for bit: xs first 60, all 12 probe positions (`monday 350 january 258 wednesday 372 colour 207
  schoolbag 492 is 600 the 521 hello 598 one 8 first 25 not 2 very 37`), zk-new first 30, `look after` 294. The pedagogy module is
  imported unchanged; its 12 probes and `look after` 231 match its document. Both keys are shuffle-invariant; the purist key is a
  total order; pedagogy has 9,222 distinct integer keys for 9,618 rows, made total by the `lemma` tie-break as its §4 says.
* Yardstick: "function word" in every table below is the neutral FACTS §2 definition (`dominant_pos ∈ FUNCTION_POS` or lemma in the
  24-form AUX list or `inherit:` in sources). Under it the interjection `yes` and the month `may` count as function words — the two
  footnotes in §2(a) are those.
* The `_STAGE_DISTANCE` emulation uses SQLite's rule that NULL sorts first in ASC order (the C10 trap in §2(f) was wrong in a first
  draft of the script and is corrected).

## 2 Scores with evidence

### (a) 小学生 — xs, 600 words · purist 5, pedagogy 8

| metric | today | frequency-purist | pedagogy-first |
|---|---|---|---|
| grammar words in first 30 / 100 / 300 | 28 / 57 / 70 | **0 / 0 / 0** | 0 / 1¹ / 16² |
| adverbs & particles in first 30 / 100 / 300 | 1 / 13 / 26 | **8 / 21 / 28** | **0 / 0 / 13** |
| first 30 | the be and of a in to have it i that for you he with on do say this they at but we his from not by she or what | say **not** go get make know **up** one time year **so** think people take **out** see come **now how then** two want way look first **also** new day use physical education | say go get make know one time year think people take see come two want way look first new day use man find give tell good physical education woman child work |
| months (12) | may 97, the rest 478–596 | scattered 217–577: april 217 june 218 july 240 october 251 september 256 january 258 november 271 december 272 february 285 **march 427 august 512 may 577** | **241–252, calendar order** |
| weekdays (7) | 579–600 | scattered 260–388 (sunday 260 saturday 282 friday 344 monday 350 wednesday 372 thursday 385 tuesday 388) | **378–384, calendar order** |
| numbers one…ten / first second third / hundred thousand million | 44…337 / 73 216 253 / 267 274 148 | 8 21 52 103 123 161 225 226 281 238 / 25 153 187 / 201 210 86 | 6 14 38 83 101 141 209 210 279 222 / 18 131 168 / 184 195 65 |
| be am are is · do does | 2 341 573 581 · 17 576 | 522 **595** 541 **600** · 537 581 (`are`, `does` dealt into the closed block at arbitrary spots) | **270 271 272 273 · 341 342** (glued) |
| hello hi yes goodbye | 435 427 174 523 | 598 597 589 599 | 171 119 71 224 |
| like (喜欢; ECDICT i:68) | 63 | 567 | 483 |
| colour schoolbag mr. email ice cream | 574 595 586 577 580 | 207 492 203 145 88 | 191 565 262 193 134 |
| concrete nouns cat dog apple book pen red blue mother | 409 291 451 162 482 260 302 155 | 357 228 400 99 431 194 239 92 | 401 212 459 78 517 177 223 70 |
| first function word / first adverb at card | 1 / 26 | 521 / 2 | 71 (`yes`) / 126 |
| longest run of frq-NULL cards | 30 | 2 | 7 (the weekday block, by design) |

¹ `yes` (interjection). ² 11 grammar words at cards 266–300 (`the be am are is and of a in to have`, pedagogy's 50 % window by design) +
4 interjections + `may` (month). Both policies leave concreteness to COCA (cat 357–401, pen 431–517, apple 400–459): no column encodes it.

Reading: the purist clears the grammar words completely but the pupil's first 30 cards still contain 8 particles, the calendar is
scattered over 360 cards with the month `may` demoted as a modal, and `is`/`am` are the two last cards of 小学. Pedagogy's first
100 are clean content, months and weekdays come as one lesson each, `is` follows `be`; its only (a) cost is that grammar words
start at card 266 by design (11 in 266–300) and that `hello`/`yes` come from a window with two tuned numbers.

### (b) 初中生 — zk-new, 1,949 words incl. 381 上海词组 · purist 6, pedagogy 8

| metric | today | frequency-purist | pedagogy-first |
|---|---|---|---|
| first 30: grammar / adverbs / 词组 | 12 / 7 / 0 | 0 / 7 / 6 | 0 / 0 / 7 |
| 词组 in first 50 / 200 | 0 / 0 | **11 / 43** | **11 / 46** |
| 词组 per 100 cards | 0 ×15, then 87 88 87 85 34 | 21 22 21 21 21 22 21 21 21 21 21 22 21 21 20 14 20 22 8 0 | 23 23 22 23 22 21 20 20 21 19 20 19 13 19 20 18 18 18 18 4 |
| first 12 词组 | a bit (card 1501) … | have to · go in for · go on · get on · get on with · get to · have got to · in all · be made of · be made up of · get up · from time to time | have to · go in for · go on · get on · get on with · get to · in all · get up · from time to time · in time · on time · so that |
| as if would could although unless whether since during without | 1 2 3 6 127 627 98 62 45 52 | **1873 1874 1875 1877 1905 1932 1900 1894 1890 1891** (all 78 grammar words at 1873–1949) | 921 935 950 975 1346 1704 1280 1201 1148 1160 |
| just only even still really | 5 11 12 15 21 | 1 6 7 10 16 | 444 476 491 507 521 |
| look after · would like · because of · be good at · such as | 1755 1943 1574 1554 1869 | 294 121 224 271 444 | 231 99 183 213 375 |
| london britain england · centre programme (BNC fallback) | 1754 1582 1624 · 1594 1836 | 51 118 148 · 94 115 | 493 531 568 · 72 93 |
| grey favour honour queen (British spellings, COCA 25k–43k) | 1497 1491 1493 1498 | 1867 1856 1859 1868 | 1397 1556 1790 1643 (Collins/Oxford caps) |
| longest frq-NULL run | 449 | 3 | 2 |
| mean |Δposition| vs today / first-100 overlap | — | 360 / 72 | 361 / 55 |

Reading: on the 词组 the two are equivalent (same rarest-token idea, same 11 in the first 50; the purist resolves `be located →
locate` through `word_forms`, pedagogy treats a missing token as the stage median — both put `have to` third and `go in for`
eighth). The purist's cost for a 初中生 is the binary demotion: `although / unless / whether / since / during / without` — 中考
vocabulary — arrive after 1,870 cards (four months at 15 words a day), and British spellings stay at the very end as today.
Pedagogy puts grammar words from card 921 on, rescues the British spellings, pools the BNC-biased proper nouns (`london` 51 → 493)
but delays `just / only / even / still` to 444+, which is debatable for 初中.

### (c) adults — gk-new / cet4-new / cet6-new · purist 7, pedagogy 6

| stage: mean |Δpos| vs today · words moved > 100 · first-100 overlap · first-300 overlap | frequency-purist | pedagogy-first |
|---|---|---|
| gk-new (1,255) | **16.6 · 24 · 97 · 295** | 40.7 · 91 · 95 · 283 |
| cet4-new (1,726) | **28.7 · 48 · 98 · 293** | 92.4 · 232 · 80 · 256 |
| cet6-new (3,850)³ | **113.4 · 617 · 94 · 291** | 155.2 · 931 · 93 · 282 |
| `oh` (cet4) / `yeah` (cet6) — today 1 / 1 | 1706 / 3840 | 485 / 618 |
| cet4 closed words due regarding unlike via whereas — today 77 114 159 183 218 | **1707 1708 1709 1710 1712** (21 words at 1706–1726) | 857 902 948 991 1081 |
| gk former despite beyond — today 5 38 41 | 1248 1249 1250 | 659 739 818 |
| cet4 adverbs simply particularly generally — today 2 7 30 | 2 7 30 | **405 418 433** (99 adverbs pooled from 25 %) |
| cet6 currently specifically — today 13 25 | 13 25 | **939 962** |
| cet4 biggest movers | oh 1→1706, well-known 1725→51, due 77→1707, regarding 114→1708, upside-down 1720→151, unlike 159→1709, via 183→1710 | father-in-law 1700→48, world-wide 1726→141, up-to-date 1719→235, acre 1693→314, living-room 1703→328, rumour 1715→369, i.e. 1702→424, lord 1683→586 |

³ cet6's "moved > 100" is inflated for every policy by the 145 frequency-less words being spread into 3,850 (each word shifts by up
to ~145); the overlap columns are the fair regression measure.

Reading: the purist is a near no-op for adults (CET-4: 98 of today's first 100 unchanged, `oh` gone) with one real, extreme cost —
about 40 genuine words (`due via whereas regarding unlike despite former beyond prior …`) are the very last cards of their stage.
Pedagogy is gentler on those (second half) but reorders ~230 CET-4 words nobody asked to move: high-frequency adverbs an adult
should learn early (`simply particularly generally currently specifically`) go to 405–962, proper nouns to 435+, 127 words move by
the caps. Both are mild regressions; the purist's touches fewer words and is the easier one to defend ("grammar words last").

### (d) determinism and explainability · purist 9, pedagogy 6

Both are pure functions of the `words` table (purist also reads `word_forms`), shuffle-invariant, clock- and id-free; both need a
recompute on seed import (§7). The difference is the parent sentence. Purist: *"Words come in the order of how common they are
in English (COCA, BNC where COCA has none); grammar words come after all the content words of the stage. Words with no frequency
data — the 上海词组, abbreviations — are spread evenly through the stage, easiest word first."* Every position follows from one of
five rules. Pedagogy's two sentences would have to carry five windows (10–50 %, 25–100 %, 50–100 % …), the Collins/Oxford soft caps
("favourite's COCA rank is compressed 20:1 beyond 3,000 because Collins gives it four stars"), set anchors, glue and eight sub-keys;
"why is `very` card 265 and `not` card 126?" is answerable only with the quantile-slot formula. Pedagogy's determinism is fine;
its explainability costs the three points.

### (e) rule-set size and maintenance · purist 9, pedagogy 4

| | frequency-purist | pedagogy-first |
|---|---|---|
| rules | 5 | 9 |
| numeric tunables | **0** (the dealing formula is fixed) | **29** (3 Collins caps, Oxford cap, compression 20, 5 band midpoints, 10 window bounds, 8 sub-keys, null distance) |
| curated lemma lists | **16** (3 articles, 3 primary auxiliaries, 10 modals; inflected forms via `inherit:`) | **54** (26 closed lemmas incl. inflected forms, 19 calendar, 9 placeholders) |
| extra columns / tables read | `word_forms` (R3 ordering token, 26 lemmas affected) | `collins`, `oxford`, `kind` |
| things a test must pin | FUNCTION_POS identity with the image gate, `inherit:` tokens, 16 lemmas | the same + 29 numbers + 54 lemmas + window semantics |
| what a future change costs | edit one rule, recompute | retune windows whose effect depends on every other pool's size |

Pedagogy's own §6 #8 ("expose the five cap numbers as module constants pinned by a test") is the maintenance bill in one line.

### (f) robustness to missing data · purist 6, pedagogy 7

| experiment (judge_results §7) | frequency-purist | pedagogy-first |
|---|---|---|
| E1 BNC NULL everywhere | months **scattered 51–578** by even dealing (april 51, december 91, may 578); first 30 still clean | months one block at 496–507 (anchor falls back to the stage median); first 30 clean |
| E2 10 % of frq set NULL — mean |Δ| of the untouched words' relative order, xs / zk / cet4 | **0.42 / 4.18 / 0.55** | 1.08 / 5.23 / 2.09 (quantile slots shift) |
| E3 20 % of rows with label-shaped pos (`v./n.`) | `but or her` enter the first 12 小学 cards | identical failure (`but or her`) |
| E3b every pos label-shaped | collapses to today's order minus 16 lemmas | collapses to today's order minus 26 lemmas |
| E4 runtime words (NULL frq/bnc/stage_min, label pos) | last of their class (R4) until the next recompute; no error | distance 11, NULL key last; no error |
| E4 C10 trap: stage_xs = 1 with stage_min NULL | **sorts FIRST in every 小学 筛词 / 推荐词 list (card 1 of 601) — unchanged from today** | sorts last (601 of 601) via STAGE_NULL_DISTANCE 11 |
| garbage BNC (`is` 24648) | `is` = last 小学 card | glued to `be` (273) |
| mis-tagged pos (`may` v:100, `march` v, `august` j, `am` r:100) | `may` into the closed block (577), march 427, august 512 | absorbed by the set and glue rules |
| E5 62-row fixture | total order, no error | total order, no error |
| E6 a stage with no ranked word | alphabetical | calendar words first, months and weekdays interleaved by ordinal (`january monday february tuesday …`) — harmless quirk |

Both fail identically when `pos` loses its share shape (the runtime writers in `services/words.py` can do that — M5). The purist is
the more stable under frequency loss; pedagogy absorbs more of the *existing* data defects (garbage BNC, mis-tagged months, NULL
`stage_min`). One point to pedagogy.

## 3 Why the purist wins although pedagogy wins (a) and (b)

1. The sums are 42 : 39 unweighted; with (a) counted twice — the owner's stated reason for the change — 47 : 47. The tie is broken by
   the nature of the gaps, not their size: the purist's (a)/(b) defects are three named, local faults; pedagogy's (c)–(e) deficits
   are its architecture.
2. The grafts were measured on the purist base (judge_results §6, variant `sets + glue + adverbs-even`):

| metric | purist | purist + grafts (M1–M3) | pedagogy |
|---|---|---|---|
| xs first 30 | say not go get make know up one time year so think people take out … | say go get make know one time year **not** think people take see come two want way look first new day use man find **up** give tell good physical education woman | say go get make know one time year think people take see come two want way look first new day use man find give tell good physical education woman child work |
| xs grammar / adverbs in first 30 · 100 · 300 | 0/8 · 0/21 · 0/28 | 0/2 · 0/6 · 1⁴/18 | 0/0 · 1/0 · 16/13 |
| months · weekdays | 217–577 · 260–388 | **241–252 · 340–346** | 241–252 · 378–384 |
| be am are is · do does | 522 595 541 600 · 537 581 | **523 524 525 526 · 541 542** | 270–273 · 341 342 |
| not very here too | 2 37 33 50 | 9 171 138 220 | 126 265 228 315 |
| zk 词组 first 50 / 200 · just only even still | 11/43 · 1 6 7 10 | 11/42 · 11 52 72 93 | 11/46 · 444 476 491 507 |
| cet4 mean |Δ| · first-100 overlap · simply particularly | 28.7 · 98 · 2 7 | 43.6 · 90 · 10 27 | 92.4 · 80 · 405 418 |
| numeric tunables · curated lemmas | 0 · 16 | **0 · 35** | 29 · 54 |

⁴ `may`, inside the month block, counted by the FACTS yardstick.

3. The remaining differences after the grafts are deliberate knobs, not defects: binary demotion of grammar words (purist: last of
   the stage; pedagogy: from 50 %) and interjections (§5 G5). Both are one-line changes on the purist base if a pilot asks for them;
   the reverse — removing pedagogy's windows and caps — is a rewrite.
4. Conventions of the repository (FACTS §3: "seed numbers live in stats.json, never constants in docs"; every behaviour has a test;
   docs ↔ code pinned) favour the design with 0 numeric constants: each of pedagogy's 29 numbers would need a pinning test and a
   docs sentence.

Parent-facing explanation of the winner with the grafts (two sentences, zh-CN for the owner's use): 卡片按英语里的常用程度排序
（COCA 词频，缺的用 BNC 补），语法词——冠词、代词、介词、连词、助动词——排在本阶段所有实义词之后。没有词频的词（上海词组、缩写）和副词按
均匀间隔插入，月份和星期各作为一组按日历顺序出现，am/is/are 紧跟 be。

## 4 must_fix for the winner (ordered by learner impact)

**M1 — Calendar sets (graft of pedagogy R5).** Evidence: 小学 months at 217–577 with `may` 577 (the modal list eats the month) and
`august` 512 / `march` 427 (COCA); weekdays 260–388. Rule: a lemma in MONTHS ∪ WEEKDAYS is never closed (precedence over R1), takes
the median native rank of the set's members present in its group as its rank, and sorts inside the set by calendar ordinal
(sub-key). Fallback when no member has a rank: anchor the block at the group's median rank (E1 shows even dealing would scatter
them 51–578). Expected: months 241–252, weekdays 340–346 (measured). Cost: 19 lemmas, 0 numbers. `wd check db` invariant: every
calendar lemma present and `stage_xs = 1`.

**M2 — Glue inherited forms (graft of pedagogy R6).** Evidence: `is` is the last 小学 card (600, BNC 24648), `am` 595, `are` 541 and
`does` 581 are dealt into the closed block at arbitrary spots. Rule: a row with `inherit:X` whose head X exists takes X's key with a
form ordinal as sub-key (`be → am are is`, `do → does`); BNC/COCA of an inherited row are ignored. Expected 523–526 and 541–542
(measured). Also covers the manifest's future `was/were/been/being/has/had/did/done`. Head absent → fall back to R1 as today.

**M3 — Adverb flood.** Evidence: 8 / 21 / 28 adverbs & particles in the first 30 / 100 / 300 小学 cards (`not up so out now how then
also here well very back down too never`). Rule: a word with dominant pos `r` that is not closed, not a set member and not glued is
dealt evenly into its group's ranked content words with R3's formula, frequency order kept among the adverbs, sub-key after a
frequency-less word dealt to the same host. Expected: `not` 9, `up` 25, `so` 42, `very` 171; 2 / 6 / 18; 初中 `just` 11, `only` 52;
CET-4 `simply` 10, first-100 overlap 90 (measured). Rejected alternative, measured: dealing into the second half only (`not` 250,
`just` 896, `simply` 809, CET-4 overlap 84) — too late for 初中 and adults. No constant; the sentence is "adverbs are spread evenly
through the stage".

**M4 — NULL `stage_min` distance (graft of pedagogy R8).** Evidence: E4 — a hand-inserted row with `stage_xs = 1` and `stage_min`
NULL is card 1 of 601 in every 小学 筛词 / 推荐词 list today and under the purist (SQLite sorts NULL first). Rule: `_STAGE_DISTANCE`
maps NULL to a distance beyond every stage (11 = 2·5 + 1); unify the two identical copies (`screen.py:34`, `batches.py:60`) into one
constant; `wd check db` invariant "any stage flag set ⇒ `stage_min` not NULL"; reword WORD_LIBRARY_CURATION §1.6 核验 C10 to "such a
row sorts last until fixed".

**M5 — Protect the two inputs the rule stands on.** Evidence: E3 — label-shaped `pos` on 20 % of rows puts `but or her` among the
first 12 小学 cards under both policies; `lookup_apply` / consolidation in `services/words.py` can rewrite `pos` with Claude labels.
Do: pin `ORDER` closed set ≡ `wd.images.style.FUNCTION_POS` (import, never copy) and the `inherit:` tokens; add a `wd check db`
invariant "every word with a stage flag has a share-shaped `pos` or NULL", or freeze the closed flag at seed import so later `pos`
rewrites cannot reorder stage words.

**M6 — Stored key, recompute hook, tests.** R3 and M1–M3 are group computations (they need the group's sorted ranked list, not a
per-row expression): the key must be stored and recomputed inside `import_seed` (and at startup when stale — the mechanism angle's
call), with a per-row best-effort (`closed`, native rank, NULL → last in class) for runtime inserts. Pack as `closed·10^7 +
rank·100 + sub` (max 46,049·100 + 99 < 10^7; sub: 0 native, 1 dealt, calendar ordinal, form ordinal, adverb). Rewrite the pinned
tests (`test_vocab`, `test_screen`, `test_batches`, FACTS §3) to compute expectations with the same function; add `full_seed`
assertions on counts, not lemmas: 0 FACTS-closed words in the first 30 of every stage; ≤ 2 adverbs in the 小学 first 30; the 12
months contiguous; 初中 词组 in the first 200 ≥ 40; longest frq-NULL run ≤ 7 (the weekday block).

**M7 — Do not leave 词频 on a list that is no longer frequency (pedagogy §3).** Either rename `zh.vocab.sort.freq` to 学习顺序
(zh.ts + FRONTEND §8 byte mirror + `npm run check:copy`) or add a `learn` sort and make it the default (TS↔Pydantic `VocabSort`
contract, `check_contract.py`, API.md §20). Owner's choice; the rename is the smaller change.

**M8 — Scope of the order.** 筛词, 每日推荐词 (`_SCREEN_ORDER`), 词库 default and `difficulty` tail, and admin 预生成
(`prewarm.candidates`, or Claude calls are spent on `the of and`) follow the key; lookup prefix suggestions keep raw `frq`. Both
proposals agree; make it a stated decision in the implementation plan.

## 5 Grafts from pedagogy-first

| graft | verdict | measured effect on the purist base |
|---|---|---|
| G1 calendar sets (R5) | **adopt → M1** | months 241–252, weekdays 340–346 |
| G2 glued inherited forms (R6) | **adopt → M2** | be am are is 523–526, do does 541–542 |
| G3 adverb pool (R4, window 25–100 %) | **adopt as even dealing → M3** (no window constant) | adverbs in first 30/100: 8/21 → 2/6; 初中 `just` 11; CET-4 overlap 90 |
| G4 `STAGE_NULL_DISTANCE` (R8) | **adopt → M4** | C10 row card 1 → card 601 |
| G5 interjections out of the closed class, dealt evenly | **adopt, optional knob** | `yes` 64, `hi` 191, `hello` 329, `goodbye` 463 (from 589–599); CET-4 `oh` 854, CET-6 `yeah` 642 `alas` 1922 `hurrah` 3202; CET-4 overlap unchanged (90). Cost: one derived constant `ORDER_CLOSED_POS = FUNCTION_POS − {u}` — the order gate diverges from the image gate, which the purist author reserved for exactly this case. A parent browsing the 词库 小学 tab will otherwise find `hello` as the last word |
| G6 词库 全部 tab ordered by `COALESCE(stage_min, 6)` first, then the key (pedagogy §3) | **adopt** | 全部 starts with the 小学 course instead of mixing `just other more thing` (初中) into the first 30; one extra key on the no-stage query |
| G7 composition tables and "first grammar word at card N" as `full_seed` assertions (pedagogy §2.3 style) | **adopt → M6** | counts, not lemmas, survive seed re-imports |
| G8 Collins/Oxford soft caps (R1) | **reject the caps; fix the data** | caps move 467 words with 5 constants and break the parent sentence. The benefit is real (`grey` 1867 → 1397, `favourite` 590 → 526, `honour favour queen harbour cheque licence`) but it is a spelling-variant problem: a seed-builder rule "a British spelling inherits its American twin's `frq`" (colour←color 697, favourite←favorite, grey←gray, honour←honor, centre←center, programme←program, realise←realize, theatre, labour, defence, licence, cheque …) is deterministic, explainable and constant-free; the ordinals `thirteenth–ninetieth` stay late, which is where the 二级 list's rarest numerals belong |
| G9 proper-noun pool (25–100 %) | **reject** | even dealing of proper nouns moves `london` 44 → 76, `britain` 103 → 124 only; the BNC bias is ~6 words (`london centre programme britain england europe`) — not worth a rule |
| G10 50 % window for grammar words instead of binary demotion | **keep binary; owner's knob for 初中** | pedagogy's own numbers: `the` 266 vs 526 (小学), `would` 950 vs 1875 and `although` 1346 vs 1905 (初中). If 初中 testers report 中考 grammar words arriving too late, deal the closed class into the second half for stages ≥ 初中 (one constant) |
| G11 phrases by direct component rank | both proposals reject it (48 词组 in the first 50, a 37-card frequency-less run) | — |

## 6 Limitations shared by both policies (owner decisions, not policy defects)

* **Concreteness.** `cat` 354–401, `pen` 428–517, `apple` 396–459 under every policy; the first 30 are abstract high-frequency verbs
  and nouns (`say go get make know time year people`). Only a curated 第一课 starter list (pedagogy §6 #5: hello goodbye yes no cat
  dog red blue book pen schoolbag Mr.) can change that — a product decision; pedagogy's advice to wait for the first Grade-3+ pupils'
  feedback is sound.
* **`like` 喜欢** (ECDICT i:68) is card 567 / 483; `front near behind half` likewise. A data fix (pos-share override in the seed
  builder) is the right lever, and it changes the image gate consistently.
* **Rarest-token proxy for 词组.** Idioms made of frequent words come first in both (`go in for` 8, `in all` 29, `get on with` 21);
  spot-check the first 50 初中 词组 by eye before inviting 初中生; a `phrase_rank` override column is the fallback.
* **Late everyday words.** `no` 506/572, `please` 465/546, `ok` 433/514, `bye` 510/579 are COCA artefacts under every policy.
* **`mr.` / `mrs.`** — the builder-side `frq` patch (purist §6 #8: 191 / 932 → cards 72 / 260) after the policy ships.

## 7 Notes for the mechanism decision (mech-*.md)

* Both policies — and the winner with M1–M3 — are group computations: dealing needs the group's sorted ranked list and the word's
  index among the unranked. A query-time UDF fed three per-stage quantiles (mech-query-time) cannot reproduce R3 exactly; the
  stored-key mechanisms (derived column / seed-carried) can. The purist proposal says so itself (§1 R3, §7).
* Inputs of the winner: `lemma`, `pos` via `dominant_pos`, `frq`, `bnc`, `sources` (`inherit:`), `stage_min` and group membership,
  plus **`word_forms`** for R3's ordering token (26 lemmas change token: `be located → locate`, `according to → accord`); `kind` is
  not read (M1 uses lemma lists). The mechanism documents list the inputs without `word_forms` — add it.
* Runtime words: per-row best-effort key at insert (`closed`, native rank; NULL → last in class), full recompute at the next seed
  import or a `wd learn-order` CLI; `lookup_apply` filling `frq` later must refresh the per-row part.
* Key packing `closed·10^7 + rank·100 + sub` keeps one INTEGER column and one `ORDER BY … learn_key, lemma` tail.

## 8 Reproduction

```
cd /private/tmp/claude-501/-Users-sqin-word-dance/0be1d882-e939-4b1e-8c2e-b69435664161/scratchpad/order/sim-judge
/Users/sqin/word-dance/.venv/bin/python -I judge.py          # → judge_results.txt (§0 determinism, §1 cross-check, §2–§5 criteria,
                                                             #   §6/§6b grafts one at a time, §7 robustness E1–E6, §8 rule-set size)
cd ../sim-pedagogy-first && /Users/sqin/word-dance/.venv/bin/python -I simulate.py && /Users/sqin/word-dance/.venv/bin/python -I positions.py
cd ../sim-frequency-purist && /Users/sqin/word-dance/.venv/bin/python -I sim_frequency_purist.py
```
`judge.py` imports `sim-pedagogy-first/policy.py` unchanged and re-implements purist R1–R5 (`purist_keys`, grafts as flags
`sets / glue / adverbs-even / adverbs-half / interj-even / proper-even`); `wd` is importable under `-I` through the venv's editable install.
