# Ordering policy — angle "frequency-purist" · 2026-11-06

Input: `FACTS.md` (same directory) and the live copy `scratchpad/deploy/precheck/word-dance.db` (schema 13, 9,618 words, opened
read-only). Simulation: `sim-frequency-purist/sim_frequency_purist.py`, run with `/Users/sqin/word-dance/.venv/bin/python -I`;
its full output is `sim-frequency-purist/results.txt`. Nothing in the repository or the live data directory was touched.

**Stance.** The learning order *is* the corpus order. The policy deviates from `words.frq` in exactly three places, each one
a correction of something the corpus rank cannot express for a learner, never a pedagogical reordering: (a) a closed class of
function words goes after the content words of the same stage-distance group; (b) a word without a COCA rank takes its BNC
rank; (c) a word with neither is dealt into its stage at an even spacing, ordered among its peers by the rarest word it
contains. Five rules, no tunable constants, one new word list of 16 lemmas that any grammar book confirms.

Outer key unchanged: 筛词 / 每日推荐词 keep `_STAGE_DISTANCE` (DESIGN §6.3 step 4) in front of everything below. The 词库 page
has no stage key and applies the rules to whatever the tab filters. Every stage shown in §2 is one stage-distance group, so
what the simulation prints is literally the sequence a learner of that 主攻阶段 meets.

---

## 1 The rules

Notation: `w` is a `words` row; `dominant_pos` and `FUNCTION_POS` are `wd.images.style.dominant_pos` / `FUNCTION_POS`
(D-images-24: the one sanctioned reader of `pos`; `FUNCTION_POS = {i, c, d, p, a, u, t}`; adverbs `r` deliberately not in it).
"Rank" means the R2 value. "Ranked" / "frequency-less" refer to R2 being non-NULL / NULL.

### R1 — Closed class sorts after the content words of its group

```
closed(w) :=  dominant_pos(w.pos) ∈ FUNCTION_POS                                   -- R1a  67 of the 80 xs cases
           OR w.lemma ∈ CLOSED_LEMMAS                                              -- R1b   9
           OR ' inherit:' occurs in ' ' || COALESCE(w.sources, '') || ' '          -- R1c   4
CLOSED_LEMMAS := ARTICLES {a, an, the} ∪ PRIMARY_AUX {be, do, have}
               ∪ MODALS {can, could, will, would, shall, should, may, might, must, ought}      -- 16 lemmas
```

SQL twin (with `dominant_pos` registered as a deterministic UDF or materialised in a column `dominant_pos`):
`(dominant_pos(w.pos) IN ('i','c','d','p','a','u','t') OR w.lemma IN (…16…) OR instr(' '||COALESCE(w.sources,'')||' ', ' inherit:') > 0)`.

* R1a reuses the project's existing definition of "function word" unchanged. The image pipeline already decides with the same
  gate that these words get a template card and no picture (`skip_image`); the ordering now agrees with the picture gate, so
  there is one notion of function word in the code base and the pupil never gets a picture-less card first.
* R1b exists because ECDICT's `pos` column cannot signal two textbook closed classes: every auxiliary and modal is tagged `v`
  (`be v:100`, `have n:1/v:99`, `can n:2/v:98`), and `an` has no `pos` row at all (fact sheet §2: `an` pos NULL, bnc 30 — without
  R1b it is the **third** 小学 card, variant `an-unlisted` in §2.5). The list is the three articles, the three primary
  auxiliaries and the ten modals; a reviewer can check it against any grammar in a minute. Inflected forms (`am is are does`)
  are *not* listed on purpose: the seed marks them `inherit:<headword>` and R1c catches them, so the list never has to grow
  when the manifest's `inherit_stages` (be → was/were/been/being, have → has/had, do → did/done) is ever imported.
* R1c: inherited forms are grammar of their headword, not vocabulary; their rows carry no `pos` and mostly no rank (`is` has a
  garbage bnc 24648) — demoting them makes the position explicit instead of accidental.
* Demotion is **binary** (closed words after all content words of the same group, frequency order kept inside each class).
  No multiplier, no offset: a constant would be a pedagogical judgement the purist cannot defend.

Outcome bought — pupils: the first 30 小学 cards (词库「小学」页签, onboarding 筛词, 每日推荐词) are 30 content words instead of
28 function words out of 30 (`the be and of a in to have it i that …`). A 6–11-year-old cannot give a meaningful 认识 / 不认识
verdict on `the` or `of`, and meets those words in every example sentence anyway. Adults: `oh` (u:100) stops being the first
CET-4 推荐词; 8 / 21 / 11 words of gk-new / cet4-new / cet6-new move to the end of their stage (listed in §2.6) — the adult still
meets `despite`, `whereas`, `via` after the content words of the same stage, not never.

Cost side, stated plainly (every word of this list is demoted *because the adult corpus says so*): `like` (c:4/i:68/j:2/n:2/r:2/v:22 —
喜欢 is 22 %) sits at xs position 566; `have`/`do`/`be` at 528–537; `hello hi goodbye` (u) at 597–599, `yes` 587; `front` (i:38/j:33/n:25)
592; `half`, `near`, `behind`, `whose`, `where`, `when`, `much`, `over`, `about` in the closed block. No per-word exception is made
(that would be pedagogy); §6 lists the two knobs (`u`, `have/do`) the product owner may still turn.

### R2 — Rank: COCA first, BNC second

```
rank(w) := frq  if frq > 0  else  bnc  if bnc > 0  else  NULL
SQL:      COALESCE(NULLIF(w.frq, 0), NULLIF(w.bnc, 0))
```

BNC rank is on the same scale (fact sheet: well 100/84, only 101/70, very 105/80, good 110/73; `color` frq 697 vs `colour` bnc 642)
and is the only other corpus rank the seed carries. It fires for 225 words: xs 19 (`colour` 642, the 9 months and 7 weekdays
that have no COCA rank, `an`, `is`), zk-new 50 (British spellings and proper nouns: `london` 248, `centre` 327, `programme` 360,
`britain`, `england`, `europe`, `realise`, `theatre` …), gk-new 20, cet4-new 18, cet6-new 91, 课标外 27.

Outcome bought — pupils: `colour` moves from 574 to 207, `january` 582 → 258, `monday` 585 → 350, `wednesday` 600 → 372 — the
附表 months and weekdays sit in the middle of 小学 where their BNC frequency puts them, instead of forming the last 30 cards.
Cost: the BNC's British bias is imported with it (`london` is the 51st 初中 card, `centre` the 94th); `is` keeps its nonsensical
24648 but is closed (R1c) so it lands last of 小学 either way.

### R3 — Frequency-less words are dealt evenly into their stage, ordered by their rarest word

For each group `G = (stage_min, closed)` (the NULL stage 课标外 is a group too):

```
ranked   := rows of G with rank ≠ NULL, sorted by (rank, lemma)                      n_r = len(ranked)
unranked := rows of G with rank = NULL, sorted by (token_rank IS NULL, token_rank, lemma)   n_u = len(unranked)
token_rank(w) := max over tokens t of lemma.replace('-', ' ').split() of rank(headword(t)), ignoring tokens that do
                 not resolve or have no rank; headword(t) = words.lemma = t, else the single word a word_forms row
                 `form = t` points at (ambiguous forms are skipped — the resolution of DESIGN §5.2 step 2)
for k, w in enumerate(unranked, 1):
    host         = ranked[ceil((k - 0.5) * n_r / n_u) - 1]
    w.rank       = host.rank          # the dealt rank
    w.rank_dealt = 1                  # sorts right after its host (R5)
```

If `n_r = 0` the rows keep rank NULL (R4). The dealt rank is a *position*, not a frequency claim: with no information about a
word's frequency the only placement that claims nothing is the uniform one, and the learner's exposure to the frequency-less
words then equals their share of the stage (one every 3.9 ranked words in 初中新增, one every 53.5 in 小学). The rarest-word
order among the dealt words is the one corpus signal a phrase does carry (ECDICT has `frq = 0` for *all* 2,044,859 multi-word
rows, verified): it puts `have to`, `go on`, `get up`, `look at` before `the pacific ocean`, `lunar calendar`, `kung fu`.

It fires for 533 words: zk-new 399 (381 上海词组 + `t-shirt`, `x-ray`, `e-mail`, `twenty-one`…), xs 11 (`physical education`,
`ice cream`, `email`, `mr.`, `mrs.`, `ms.`, `p.e.`, `ping-pong`, `schoolbag`, and `are`/`does` inside the closed block), gk-new 6,
cet4-new 17, cet6-new 54, 课标外 46. 445 of the 448 multi-token lemmas resolve a token (`ping-pong`, `kung fu`, `wi-fi` do not);
`word_forms` change the ordering token of 26 lemmas (`be located` → `locate` instead of `be`, `be made of` → `make`, `so-called`
→ `call`, `according to` → `accord`) — without them the first six 初中 phrases are `be located / be made of / be located in /
according to / be connected to / be supposed to` because only their function words resolve (variant `deal-noforms`).

Outcome bought — 初中 learners: a 词组 appears about every fourth card from the first day (11 of the first 50, 43 of the first
200, flat across the ten deciles: 41 42 42 41 41 41 42 33 40 18) instead of a wall of 399 frequency-less items at positions
1474–1872 that a 15-words-a-day learner reaches after ~100 days (today: 449 in a row from position 1501). Pupils: `physical
education` 30, `ice cream` 88, `mr.` 203, `schoolbag` 492 (today 595). Two rejected alternatives are measured in §2.5: using the
rarest word's rank *as* the phrase's rank (phrase wall at the top: 56 of the first 60 初中 items are phrases, CET-4 opens with
`well-known upside-down so-called father-in-law`) and alphabetical dealing (`a bit, a bit of, a couple of, a kind of …` first).

### R4 — A word with no rank at all sorts after every ranked word of its class

`(rank IS NULL) ASC` in the ORDER BY. After R3 no live seed word is in this state; it is the degradation path for words created
at runtime before the next recompute (§5) and for a group with no ranked word to deal into.

### R5 — Tie-break: native before dealt, then lemma

Full key, ascending: `(closed, rank IS NULL, rank, rank_dealt, lemma)`. `lemma` is UNIQUE, so the order is total. `rank_dealt`
before `lemma` guarantees a dealt word never precedes the word whose rank it borrowed (`cream` before `ice cream` would be a
coincidence of the alphabet; `use` before `physical education` is the rule).

Packed single-integer form for a stored column: `learn_key = closed * 10000000 + COALESCE(rank, 999999) * 10 + rank_dealt`
(max rank in the seed 46,049 → 460,491 < 10,000,000), then `ORDER BY {_STAGE_DISTANCE}, w.learn_key, w.lemma`. R1, R2, R4 and R5
are per-row and expressible in plain SQL (R1a through a UDF or a stored dominant pos); R3 needs the group counts `n_r`, `n_u`, so
it is a recompute step (window functions would also do it) — which mechanism carries the result is the other angles' question.

---

## 2 Simulation (live copy, read-only)

`sim_frequency_purist.py` loads all 9,618 rows, applies R1–R5 per variant, and sorts each scope by the key. Every row is public,
valid and unmerged today, so the 筛词 visibility predicates do not change any count. Baseline = today's
`ORDER BY (frq IS NULL OR frq = 0), frq, lemma`.

### 2.1 First 60 lemmas per stage (policy)

**xs 小学 (600; 80 closed)**
say not go get make know up one time year so think people take out see come now how then two want way look first also new day use
physical·education man find here give well tell very back good woman child work down call world school try last ask too feel three
never family put old keep student why let
— last 12: yes behind whose half near front am beside hi hello goodbye is

**zk-new 初中新增 (stage_min 2; 1,949; 77 closed)**
just other have·to more thing only even go·in·for life still need state go·on become high really get·on most leave mean group
get·on·with seem country problem start get·to american part case have·got·to company system program government in·all number point
believe hold be·made·of happen large area national be·made·up·of fact different business get·up london side provide service
from·time·to·time important away power yet in·time
— last 12: towards plenty addition plus shall mine yours hers ours till theirs minus

**gk-new 高中新增 (1,255; 8 closed)**
issue political guy policy economic rate drug leader military tax site court image data source evidence billion opportunity
administration campaign current involve defense security seek author represent agency movement concern series significant factor
decade scene career thus treatment approach organisation fund occur individual identify determine indicate region election sex
professor financial crime authority sort strategy indeed claim remove legal cell

**cet4-new 四级新增 (1,726; 21 closed)**
federal simply republican congress stock media particularly growth analysis democratic executive entire religious management
statement employee production sexual agent consumer shot senate relation effective troop investigation researcher argument
possibility generally define soviet presence reader christian willing understanding contribute protection additional highly
associate critic intelligence connection learning hell relatively democracy colleague well-known writing expression reading
increasingly married emotional supreme poll teaching

**cet6-new 六级新增 (3,850; 11 closed)**
environmental democrat cultural attorney participant concerned involved voter assessment presidential regional analyst currently
investor hearing jesus catholic aids producer regime perception opposition judgment christ specifically abortion sector fishing
curriculum assistance asset proceeding creation deeply funding therapy well-off existing planning cop participation album coalition
negotiation investigator suicide enforcement marketing congressional involvement championship spending evaluation equally deficit
ally confront peer designer immigration

### 2.2 Probe positions

| word | scope | today | policy | how |
|---|---|---|---|---|
| monday | xs | 585 | 350 | R2 bnc 1679 |
| january | xs | 582 | 258 | R2 bnc 984 |
| wednesday | xs | 600 | 372 | R2 bnc 1980 |
| colour | xs | 574 | 207 | R2 bnc 642 |
| schoolbag | xs | 595 | 492 | R3 dealt (no token; alphabetical among the unresolvable, after `ping-pong`) |
| is | xs | 581 | 600 | R1c + bnc 24648: last of 小学 |
| the | xs | 1 | 521 | R1a: first of the closed block |
| hello | xs | 435 | 598 | R1a (u:97) |
| one | xs | 44 | 8 | content (m:64) |
| first | xs | 73 | 25 | content (m:96) |
| not | xs | 26 | 2 | content (r:99); adverbs are not in FUNCTION_POS |
| very | xs | 88 | 37 | content (r:92) |
| a lot of | — | — | — | not in `words` (verified) |
| look after | zk-new | 1755 | 294 | R3 dealt after `nearly`; ordered among the dealt by its rarest token `after` 120 (`look` is 85) |

In 词库 全部: monday 1599, january 891, colour 550, schoolbag 6562, is 9616, the 9415, hello 9572, one 8, first 29, not 2, very 43,
look after 506, have to 21, get up 152, ice cream 131, mr. 529.

### 2.3 Required counts

| metric | xs | zk-new | gk-new | cet4-new | cet6-new | 全部 |
|---|---|---|---|---|---|---|
| closed-class words in the first 30 — today | 28 | 12 | 1 | 1 | 1 | 28 |
| closed-class words in the first 30 — policy | **0** | **0** | **0** | **0** | **0** | **0** |
| phrases in first 50 / 200 — today | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 |
| phrases in first 50 / 200 — policy | 1/2 (of 2) | **11/43** (of 381) | 0/1 (of 4) | 0/0 (of 0) | 0/0 (of 2) | 3/18 (of 395) |
| longest run of consecutive frequency-less words — today | 30 (@571) | 449 (@1501) | 26 (@1230) | 35 (@1692) | 145 (@3706) | 758 (@8861) |
| longest run — policy | **2** (april june @217) | **3** (chopstick cpc tcm @1864) | 2 | 2 | 3 | 3 |
| words with no rank at all after R3 | 0 | 0 | 0 | 0 | 0 | 0 |

Frequency-less 初中 words per decile under the policy: 46 44 47 43 48 48 47 43 45 38 (today: 0 0 0 0 0 0 0 60 195 194).

### 2.4 Where each rule fires (per `stage_min`)

| stage | n | closed (R1a / R1b / R1c) | COCA | bnc-rescued (R2) | dealt (R3) | dealt without any resolvable token |
|---|---|---|---|---|---|---|
| xs | 600 | 80 (67 / 9 / 4) | 570 | 19 | 11 | are does email mr. mrs. ms. p.e. ping-pong schoolbag |
| zk-new | 1,949 | 77 (72 / 5 / 0) | 1,500 | 50 | 399 | a.m. kung fu mooncake p.m. prc qipao tcm wto |
| gk-new | 1,255 | 8 | 1,229 | 20 | 6 | bce wi-fi |
| cet4-new | 1,726 | 21 | 1,691 | 18 | 17 | a.m b.c. dissatisfy i.e. mechanics outskirt reflexion reservior systematical uptodate |
| cet6-new | 3,850 | 11 | 3,705 | 91 | 54 | 33 (accessary affixation … vitamine) |
| 课标外 | 238 | 7 | 165 | 27 | 46 | 26 |

### 2.5 Variants (one knob each; §4 of `results.txt`)

| variant | xs first cards | zk-new phrases 50/200 | zk-new longest frq-less run | notable positions |
|---|---|---|---|---|
| **policy** | say not go get make … | 11/43 | 3 | have to 3, get up 50, look at 172, look after 294, kung fu 1843 |
| no-R3 (NULL last, after R1/R2) | same | 0/0 | 399 | a bit 1474, have to 1641, look after 1698 — the wall, moved from the end to just before the closed block |
| R3-absolute (rejected: rarest word's rank = phrase rank) | same | 47/140 | 27 | zk-new opens `have to go in for go on get on get on with …` (56 phrases in the first 60); cet4-new opens `well-known upside-down so-called father-in-law` |
| deal-alpha (dealing, alphabetical) | … use **email** | 10/42 | 3 | a bit 3, have to 787, look after 1054 |
| deal-noforms | same | 11/43 | 3 | first phrases `be located, be made of, be located in, according to …`; well-known 151 instead of 51 |
| u-content (interjections content) | same | 11/43 | 3 | hello 385, yes 111, hi 376, goodbye 476; **oh is the first cet4-new card again** |
| aux-minimal (list without have/do) | **have do** say not go … | 11/43 | 3 | have 1, do 2 |
| an-unlisted (no articles in the list) | say not **an** go … | 11/43 | 3 | an 3 |
| data-mr (builder patch mr. 191 / mrs. 932) | same | 11/43 | 3 | mr. 72 (from 203); mrs. 260 |

### 2.6 The adult closed blocks (what R1 moves to the end for adults)

gk-new: former despite beyond beneath prior alongside behalf aboard · cet4-new: oh due regarding unlike via latter whereas
concerning provided spite whoever underneath whatsoever conjunction oneself amongst accordance lest whichever owing whilst ·
cet6-new: yeah versus amid atop considering alas amidst irrespective inasmuch hurrah nought.

### 2.7 The 小学 closed block (positions 521–600, policy order)

the be and of a in to have it i that for you he with on do this they at but we his from an by she or what their can who her all my
about will there when which them some me him your like its our these because no many those any us may after should over between
much where every before must under yes behind whose half near front am beside hi hello goodbye are(dealt) does(dealt) is — `are`
and `does` are dealt into the closed block by R3 (positions 541, after `at`, and 581, after `over`, in the run), `is` is last by its bnc.

---

## 3 What the 词库 "全部 / 词频" tab starts with

全部 (9,618 words, default sort, no stage key) under the policy:

say not go get make know up one time year so think people take out just see come now other have·to how then two more want way look
first also new day use physical·education man find here thing give well only tell very even go·in·for back good woman life child
work down call world school still try last ask need

(small = 小学 word, `just/other/more/thing/only/even/life/still/need` and the three phrases are 初中新增.) `the be and of a` are at
9415–9419, `like` 9467, `hello` 9572, `is` 9616 — the 204 closed-class words of the whole seed are pages 189–193 of 50. Today the tab
starts `the be and of a in to have it i` and ends with 758 frequency-less words in a block. The 初中 tab (`stage_zk = 1`, 2,549
words) starts identically to 全部 up to `well` and has `the` at 2393, `is` at 2549.

The `difficulty` sort (`COALESCE(difficulty + 1, stage_min, 6)` then the frq tail) keeps its first key and takes the same tail
(`closed, rank IS NULL, rank, rank_dealt, lemma`), so a 难度 page is ordered inside each difficulty band exactly like 词频.

Label: the sort value stays `freq` / 词频 (zh.ts and the FRONTEND §8 mirror unchanged); API.md §20 and DESIGN §3.2 describe the new
ORDER BY. Whether to add a fourth, raw-frq sort is §6 item 5.

---

## 4 Tie-break and determinism

* The key is a pure function of the `words` table (and `word_forms` for R3's ordering token). No clock, no user, no randomness,
  no `id`: two databases with the same seed content produce the same order, which is what `kv.seed_version` already promises
  for content. `dominant_pos` and the three lists are constants of the code.
* Total order: `lemma` is UNIQUE, so `(closed, rank IS NULL, rank, rank_dealt, lemma)` never ties. The simulation asserts that all
  9,618 keys are distinct, that sorting a shuffled copy of the rows gives the same sequence, and that a second recompute yields
  identical keys. 161 `(closed, rank, rank_dealt)` collisions exist (BNC values coinciding with COCA values across stages, e.g.
  `an` bnc 30 and `by` frq 30) and are all broken by `lemma`.
* `rank_dealt` before `lemma` (R5) keeps "the host word, then the word dealt after it" regardless of spelling; without it `a bit`
  would precede `bit`.
* Stability under seed changes: R1 and R2 are per-row, so adding or removing a word never moves another word. R3 is per group:
  adding one word to a stage shifts the hosts of the dealt words of that stage by at most one slot; a stage's dealt sequence
  must therefore be recomputed on every seed import (the natural hook is `seed.import_seed`, which already rewrites every row's
  dictionary fields and sets `kv.seed_version`). The simulation's `recompute` of all 9,618 rows is a single pass over the table.

---

## 5 How the rule degrades

* **Claude-label `pos` (`'v./n.'`, `'abbr.'`).** `dominant_pos` returns `None` for a label, so R1a does not fire and the word is
  content — the same degradation the image gate already has (D-images-24: "the gate then does not fire and the word is treated
  like any content word"). R1b/R1c still apply by lemma and sources, so a Claude-labelled `an` or `is` would still be closed.
  Live seed: 0 label-shaped `pos`; every seed `pos` is a share distribution or NULL (NULL → content, which is right for the 30 xs
  words with NULL pos: months, weekdays, `colour`, `schoolbag` …).
* **Runtime-created words with no `frq`.** An ECDICT-resolved word (`_resolve_ecdict`) carries ECDICT `frq`/`bnc` → R2 applies at
  once. A provisional word (`_create_provisional`, `_word_defaults`: frq NULL, bnc NULL, stage flags 0, stage_min NULL) has no rank
  → R4: it sorts after every ranked word of its class in 词库 全部 and is never a 筛词 / 推荐 candidate (no stage flag), which is
  the right place for a word the user reaches through 我的生词库. If a later Claude lookup fills `frq` (services/words.py
  `lookup_apply`), R2 applies from that moment — with a stored key, the per-row part (R1, R2) must be recomputed in that write
  path; R3 is not needed for it (the 课标外 group's dealing may wait for the next seed import).
* **`frq = 0`.** The seed never stores 0, but the code treats 0 as unknown; `NULLIF(frq, 0)` keeps that contract.
* **A stage with no ranked word** (not in the seed; possible in a tiny test fixture): nothing to deal into, the words stay R4 —
  alphabetical after the ranked words of their class — and the order is still total.
* **`sources` without the `inherit:` token** for an inflected form (a hand-inserted row): R1c misses it; R1a/R1b still apply by
  pos/lemma. Combined with the WORD_LIBRARY_CURATION §1.6 warning (a row with stage flags but NULL `stage_min` sorts first for every
  user by stage distance), the admin rule stays "set `stage_*`, `stage_min` and the dictionary fields together, then recompute".
* **Mini seed (62 records).** Groups are tiny (`n_u ≈ n_r` for some), so dealt positions there must be computed by the same
  function, not hand-pinned: `test_vocab_default_is_everything_sorted_by_frequency` (first lemma `be`), `test_next_order_and_remaining`
  (`absorption / axe / ought to`, `go / person / better`) and `test_build_batch_*` will need recomputed expectations.

---

## 6 Open choices left to the product owner (each with the recommendation)

1. **`have` and `do` in CLOSED_LEMMAS.** Textbook primary auxiliaries, but also 有 / 做. Without them they are 小学 cards 1 and 2
   (variant `aux-minimal`). *Recommend: keep them in* — the list stays the one any grammar confirms, and the pupil sees 有 in the
   example sentences of card 1 onward.
2. **Interjections (`u`) as closed class.** Keeping FUNCTION_POS intact puts `hello hi goodbye` at 597–599 and `yes` at 587;
   removing `u` brings them to 376–476 / 111 but makes `oh` the first CET-4 word again (variant `u-content`). *Recommend: keep `u`
   closed* — these are 第一课 words every pupil already knows, so a late card costs nothing, and the image gate needs the same set.
3. **`like` (and other prepositions with a content sense: `front`, `near`, `behind`).** The adult corpus says `like` is 68 %
   preposition; the pupil's `like` is 喜欢. *Recommend: accept* — no per-word exceptions in a purist policy; if the pilot shows
   pupils missing 喜欢, revisit as a data question (an ECDICT share override), not as an ordering rule.
4. **Binary demotion vs a scaled one.** *Recommend: binary*; every multiplier is an invented constant.
5. **词库 sort naming.** Redefine `freq`'s ORDER BY and keep the label 词频 (one contract untouched: `VocabSort`, zh.ts, FRONTEND §8),
   or add a fourth `learn`/`raw` sort. *Recommend: redefine `freq`* and document in API.md §20; offer a raw-frq sort only if a
   tester asks for it.
6. **Dealing granularity.** Fixed by the policy at `(stage_min, closed)`; the choice is whether 课标外 words (stage_min NULL) are
   dealt too (46 of 238) or stay NULL-last. *Recommend: deal them* — same rule everywhere, and they only ever appear in 全部.
7. **`word_forms` in token resolution.** 26 lemmas get a sensible ordering token (`be made of` → `make`); the cost is one more
   table read at recompute. *Recommend: keep.*
8. **Companion data patches (outside the policy).** The dotted titles have no ECDICT frequency because `aliases.tsv` deliberately
   keeps `mr.` on the dotted row (the undotted `Mr` row has a wrong computing-term meaning); a builder-side frequency-only
   override (new `frq` field in `overrides.tsv`, currently translation|word|phonetic|definition|drop) would give `mr.` 191 and
   `mrs.` 932 → 小学 positions 72 and 260 (variant `data-mr`). `Ms` (ECDICT `MS` = Microsoft / multiple sclerosis), `PE` (phase
   encoding, frq 25507), `email`, `schoolbag`, `ping-pong`, `p.e.` have no usable source. *Recommend: do `mr.`/`mrs.` only, after
   the policy ships; the policy does not depend on it.*
9. **Which lists follow the learning order.** 筛词, 每日推荐词 (`_SCREEN_ORDER`), 词库 default and `difficulty` tails, and admin
   预生成 (`prewarm.candidates` exists to pre-generate what learners meet first, so it must use the same order or it spends Claude
   calls on `the of and`). Lookup prefix suggestions (`routers/words.py:106`) are search ranking, not a learning order.
   *Recommend: all four learning lists follow the policy; lookup suggestions keep raw `frq`.*
10. **Phrases made only of function words** (`have to`, `in all`, `because of`, `in front of`, `ought to`). They are content under
    the policy (R1 is per lemma; `kind` is never read) and `have to` is the third 初中 card. *Recommend: leave as content*; a
    token-based closed test for phrases would be a sixth rule for 17 lemmas.
11. **Recompute trigger and invariant.** *Recommend:* recompute inside `import_seed` (every seed import rewrites the rows anyway) and
    add a `wd check db` invariant: every public word with a `stage_min` has a non-NULL rank, and `rank_dealt = 1` only where
    `frq` and `bnc` are both NULL/0.

---

## 7 What changes in lockstep (for the implementer) and the risks

Code sites: `vocab.py _ORDER` (freq + difficulty tails), `screen.py` and `batches.py _SCREEN_ORDER` (two identical copies — one
constant), `prewarm.py candidates`; the `dominant_pos` UDF or stored column; the 16-lemma list next to `FUNCTION_POS` (import it,
do not copy it — if the image gate and the order ever need to diverge, that is the moment for a second constant, not before).
Docs: API.md §20, DESIGN §3.2 ("0/null frequency = unknown (sorted last)" row) and §6.3 step 4, FRONTEND §4, WORD_LIBRARY_CURATION
§1.6 核验 C10, CLAUDE_INTEGRATION:303 ("by frequency"), the release note §9 open item. Tests that pin today's order: integration
`test_vocab.py::test_vocab_default_is_everything_sorted_by_frequency` and `::test_vocab_sort_alpha_and_difficulty`,
`test_screen.py::test_next_order_and_remaining` and `::test_next_auto_for_a_primary_school_learner_orders_by_stage_distance`,
unit `test_batches.py::test_build_batch_caps_ordering_and_counts` / `::test_build_batch_cold_start_puts_screens_first`,
`test_docs_contract.py`; the `full_seed` tests should pin the §2.3 counts (0 closed in the first 30 of every stage; 初中 phrases
in the first 200 ≥ 30; longest frequency-less run ≤ 5) rather than lemmas.

Risks:
* The ECDICT shares are adult-corpus facts; `like` 喜欢, `hello`, `yes` in the 小学 tail are the visible cost and the first thing a
  pilot parent will ask about.
* BNC's British bias enters 初中 through R2 (`london` 51, `centre` 94, `programme`, `britain`, `england`, `europe` in the first 200).
* Dealt positions are an even-spacing artefact, not frequency: `physical education` at 30 and `schoolbag` at 492 are where the
  dealing and the alphabet put them; nobody should read them as "physical education is more frequent than schoolbag".
* R3 is a group computation, so it cannot live in a plain ORDER BY: it needs a recompute on every seed import (or a window CTE),
  and runtime-created words sit at R4 until then.
* The policy's correctness rests on two things staying as they are: the `inherit:` tokens in `sources` and `FUNCTION_POS` being
  identical to the image gate's; both deserve a pinning test.
* `an` is closed only through the 16-lemma list (ECDICT has no `pos` for it); dropping the articles from the list makes it the
  third 小学 card.
* The mini seed's tiny groups make hand-pinned lemma expectations brittle; compute expected orders with the same function.
