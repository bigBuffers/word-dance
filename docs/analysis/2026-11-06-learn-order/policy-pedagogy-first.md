# Ordering policy — angle "pedagogy-first" (a Shanghai 小学 / 初中 English teacher's view)

Author: Claude (subagent), 2026-11-06. Input: `FACTS.md` (this directory) and the read-only live copy
`scratchpad/deploy/precheck/word-dance.db` (schema 13, seed 24f3b949, 9,618 words). Scripts and raw results:
`scratchpad/order/sim-pedagogy-first/{policy.py, simulate.py, positions.py, probe2.py, results.md, results.json}`.
Nothing in the repository was modified.

## 0 What a teacher wants, and what the columns can give

A Shanghai primary teacher introduces vocabulary by **topic and picturability**: greetings, classroom objects, colours,
numbers 1–10, family, animals, food, body — nouns and adjectives first, a handful of imperative verbs, grammar words only
inside sentence patterns ("I am…", "Where is…?"), months/weekdays as one lesson each, phrases only once their words are
known. A junior-school (初中) teacher wants the 上海词组 (词组 list, 中考 material) interleaved from day one, grammar
words (although / unless / whether) in the second half, and never a card for "oh".

The columns cannot encode "picturable" or "topic". What they *can* encode, deterministically:

| teacher's wish | computable proxy | column(s) |
|---|---|---|
| no grammar words in the first lessons | word class from the dominant ECDICT pos + a small auxiliary list | `pos` (via `dominant_pos`), `lemma`, `sources` (`inherit:*`) |
| everyday words first | COCA rank, BNC rank as fallback | `frq`, `bnc` |
| distrust a rank that contradicts the dictionaries ("favourite" rank 22274) | Collins band / Oxford 3000 as a cap | `collins`, `oxford` |
| months, weekdays as one lesson | constant calendar sets anchored at the set's median rank | `lemma` |
| am / is / are right after be | inherited forms glued to their head | `sources` (`inherit:be`), `exchange` |
| phrases after their words, spread through the course | component ranks via lemma look-up, even "slots" | `lemma`, `kind` |
| geography / holidays are a topic set, not graded vocabulary | proper-noun pool | `kind` |
| same rule must not hurt adults | all pools are relative to the stage's own rank distribution | `stage_min` |

Everything below is a pure function of the `words` table (plus code constants of the same kind as the existing
`FUNCTION_POS` / `AUX`). The result for the live data: a 小学生's first 100 cards contain **zero** grammar words
(today: 28 of the first 30 — all but `say` and `not`), months sit together at cards 241–252, weekdays at 378–384,
`the` is card 266 and `is` card 273 (right after `be am are`), `hello` moves from 435 to 171; a 初中生 meets a 词组
in every fifth card (11 of the first 50, 46 of the first 200; today the first 词组 is card 1501); a 四级 adult's first
card is `federal`, not `oh` (`oh` → 485).

## 1 The rules

Notation: `eff` = effective rank (smaller = easier); `key` = integer sort key (`eff × 100 + sub`); a *stage group* is
the set of words with the same `stage_min` (1 … 5, NULL = 课标外). Per-row rules are SQL-expressible; the cross-row
rules (quantiles, medians, component look-ups, set anchors) need one pass in Python over the table — they are what
makes the key a **recomputed derived value**, not an `ORDER BY` expression (see §5 and the sibling angles).

### R1 Effective rank: `frq` → `bnc` → NULL, with Collins/Oxford soft caps

```
raw  = frq if frq > 0 else (bnc if bnc > 0 else NULL)            -- 0 counts as unknown, as everywhere in the code base
cap_c = {5: 1500, 4: 3000, 3: 6000}[collins]  (none for 0–2);  cap_ox = 5000 if oxford = 1
soft(raw, cap) = raw if raw <= cap else cap + (raw - cap) / 20   -- integer division; keeps order, compresses the tail
eff  = MIN(raw, soft(raw, cap_c), soft(raw, cap_ox))              -- the tighter cap wins; NULL stays NULL
```
SQL (per row): `WITH r AS (SELECT id, CASE WHEN COALESCE(frq,0)>0 THEN frq WHEN COALESCE(bnc,0)>0 THEN bnc END raw FROM words) SELECT MIN(r.raw, CASE WHEN w.collins=5 AND r.raw>1500 THEN 1500+(r.raw-1500)/20 ELSE r.raw END, CASE WHEN w.collins=4 AND r.raw>3000 THEN 3000+(r.raw-3000)/20 ELSE r.raw END, CASE WHEN w.collins=3 AND r.raw>6000 THEN 6000+(r.raw-6000)/20 ELSE r.raw END, CASE WHEN w.oxford=1 AND r.raw>5000 THEN 5000+(r.raw-5000)/20 ELSE r.raw END) …`

Why: COCA is American; the Shanghai lists are British-spelled. `favourite` 22274 → 3963, `grey` 37508 → 3300,
`further` 11239 → 1986, `queen` 43081 → 5004, `labour`, `honour`, `favour`, `defence`, `licence`, `cheque` all move
out of the tail; the ordinals `thirteenth … ninetieth` (collins 4) compress from 13966–41516 to 4100–4925 so they
stop being the hardest 小学 words. 467 words move (xs 54, zk 105, gk 77, cet4 127, cet6 94, 课标外 10), every one
of the top 40 movers is a spelling variant, a mis-tagged month, a numeral or a Collins-5 word (list in
`results.md` → "cap movers"). The `bnc` fallback rescues 19 of the 30 rank-less xs words (12 months, 7 weekdays,
`colour` 642, `an` 30) and 50 zk words (`centre` 327, `programme` 360, `realise` 1018 …).

Pupil outcome: `colour` is card 191 instead of 571+; `favourite` 526 instead of 590. Adult outcome: `grey` 1397
instead of 1943 of zk-new; `harbour` (cet4) 1274 instead of ~1720.

### R2 Word class (precedence: set > glued > closed > interj > adverb > proper > content)

```
set     : lemma ∈ MONTHS ∪ WEEKDAYS                                         (19 words, all xs)
glued   : sources contains 'inherit:X' and a row with lemma X exists         (am are is → be; does → do)
closed  : dominant_pos(pos) ∈ {i, c, d, p, a, t}  OR  lemma ∈ AUX ∪ {'an'}   (FUNCTION_POS minus u, plus the auxiliary list)
interj  : dominant_pos(pos) = 'u'                                            (hello hi yes goodbye · oh · yeah alas hurrah)
adverb  : dominant_pos(pos) = 'r'                                            (not up so out now how then also here well very …)
proper  : kind = 'proper_noun'                                               (london britain christmas american soviet jesus …)
content : everything else — n v j m, NULL or label-shaped pos ('v./n.'), phrases, abbreviations
```
`dominant_pos` is `wd.images.style.dominant_pos` (D-images-24: largest share, not first token — so `one` p:31/m:64 is
a numeral, `answer`, `light`, `part`, `half`, `all` keep their dominant class). AUX = be am is are was were been being do
does did done have has had can could will would shall should may might must ought; `an` is added because ECDICT gives it
no pos at all (bnc 30 would otherwise make it the 2nd card, between `say` and `go`). `may` and `march`/`august` are mis-tagged by ECDICT
(v:100 / n:37-v:63 / j:100) — the set rule outranks the pos, which is exactly what the curriculum means by them.

Live class sizes — xs: content 468, closed 71, adverb 31, interj 4, proper 3, set 19, glued 4 · zk-new: content 1741,
closed 78, adverb 92, proper 38 · gk-new: 1207 / 8 / 36 / 4 · cet4-new: 1588 / 20 / 99 / 18, interj 1 · cet6-new:
3699 / 8 / 124 / 16, interj 3 · 课标外: 198 / 1 / 8 / 25, interj 6.

### R3 Content words with a rank: `key = eff × 100`

The spine of the order. For xs this is 459 words from `say` (19) to `maths`; for zk-new 1,343 words from `other` (75).

### R4 Pools and windows — the interleave

Every non-content class of a stage group is a **pool**, ordered within itself, and dealt into evenly spaced *slots*
of the stage's content rank distribution:

```
C   = sorted eff of the stage's ranked content words        (N = |C|; xs 459, zk 1343, gk 1201, cet4 1572, cet6 3645)
Q(q) = C[ floor(q × N) ]  clamped to [0, N-1]               (the stage's quantile function)
member j of K in pool P (0-based)  →  synthetic rank = Q( lo_P + (j + 0.5) × (hi_P − lo_P) / K )
key = synthetic × 100 + sub_P
```
| pool | window `[lo, hi)` | order inside the pool | sub | why |
|---|---|---|---|---|
| unknown (no frq, no bnc; 381 zk 词组, mr./p.e./schoolbag …) | 0.00 – 1.00 | component rank (R7), then collins ↓, oxford ↓, lemma | 40 | 词组 from day one, easiest first, proportional everywhere |
| interj | 0.10 – 0.50 | eff, lemma | 50 | greetings are first-unit material but never the first card; adults meet `oh` once, mid-list |
| proper | 0.25 – 1.00 | eff (NULL last), lemma | 55 | geography/holidays are a topic set; removes the BNC British bias (`london` bnc 248) |
| adverb | 0.25 – 1.00 | eff, lemma | 60 | learnt inside patterns ("very good"); `not` is the first adverb, at card 126 |
| closed | 0.50 – 1.00 | eff, lemma | 80 | grammar words only after the pupil has ~260 content words; `the` first of them |

The sub-key puts, at an equal synthetic rank, the content word first, then phrase, interjection, proper noun, adverb,
grammar word. The slots are spaced by *count*, so a pool with 71 members (xs closed) lands one grammar word every
4–5 cards from card 266 on, and a pool with 20 members (cet4 closed) one every 40 cards from card 857 — the adult
never notices the rule, the pupil gets a clean first 260 cards. Compared with an additive offset (`eff + median`),
the slot mechanism avoids the lump that offsets create when the pool's own ranks are compressed (71 xs function
words with frq 1–100 would all land within 60 ranks of each other: variant "offset" below has 36 of them between
cards 274 and 319).

### R5 Calendar sets: one lesson, calendar order

```
anchor = median_low( eff of members present in the stage )      months 964 (xs) · weekdays 1679
key    = anchor × 100 + ordinal                                  january = 1 … december = 12; monday = 1 … sunday = 7
```
Months land at cards 241–252, weekdays at 378–384 — the only non-column ordering in the policy (calendar order), and
the only intentional run of rank-less words (7, the weekdays). The median anchor is robust to `may` (119) and
`august` (22206 → 3960).

### R6 Glued inherited forms

`inherit:X` → `key = key(X) − key(X) mod 100 + 81 + j` (j = index among X's forms sorted by lemma): `be` 270 →
`am` 271, `are` 272, `is` 273; `do` 341 → `does` 342. The paradigm appears as one mini-lesson, wherever the head
lands (heads are AUX, so inside the closed window). Only the `inherit:*` token is trusted; `exchange_json["0"]` is
NOT used as a head pointer (live data: `also → conjurer`, `of → have`, `some → an`, `does → doe`, `evening → even`).

### R7 Unknown-pool order: component rank

```
tokens  = lemma split on space / hyphen / slash; drop placeholders (sb. sth. one's oneself …); strip 's
rank(t) = eff of the row with lemma t; a token with no row → the stage median (xs 1051, zk 1733)
component_rank(phrase) = MAX over tokens          -- "the hardest word in the phrase"
single-token unknown → BAND_MID[collins] = {5: 350, 4: 1200, 3: 2500, 2: 5000, 1: 10000}, NULL for collins 0
```
So `have to` (8), `go in for` (35), `go on`, `get on`, `get to`, `in all`, `get up` … come first; `the pacific ocean`
(pacific 26607 → 1911), `beijing opera` (1744), `kung fu` (both tokens missing → median → 1427) late. Because the
pool is still dealt into even slots (R4), the hardest-word order decides *which* phrase comes next, not *how many*
phrases a window gets: 11 in the first 50, 46 in the first 200, 18–23 per 100 cards throughout zk-new.

### R8 Stage grouping

Within a learner's list the existing `_STAGE_DISTANCE` stays, with `stage_min IS NULL → distance 11` (beyond every
stage) instead of SQL NULL — this closes the WORD_LIBRARY_CURATION C10 trap (a hand-inserted row with stage flags
but NULL `stage_min` sorted FIRST for everyone). The 词库 全部 tab orders by `COALESCE(stage_min, 6)` first (§3).

### R9 Final order and tie-break

`ORDER BY <distance>, learn_key IS NULL, learn_key, lemma, id` — integer key, unique lemma, id as the last guard (§4).

## 2 Simulation (actually run on the live copy)

`cd scratchpad/order/sim-pedagogy-first && /Users/sqin/word-dance/.venv/bin/python -I simulate.py` (≈2 s; opens the
copy with `?mode=ro&immutable=1`; imports `wd.images.style.dominant_pos` from the repo so the pos reader is the
sanctioned one). `positions.py` prints the hand-picked positions quoted below. The run also asserts (a) the keys are
identical when the rows are fed in shuffled order and (b) `(key, lemma)` is unique over all 9,618 rows.

Per-stage medians of the ranked content words (what the windows are relative to): xs 1051 · zk-new 1733 · gk-new
2914 · cet4-new 5092 · cet6-new 8624 · 课标外 12617.

### 2.1 First 60 of each stage (the "new" set of the stage, i.e. `stage_min = s` = distance 0 for its learner)

**xs (600)** — say go get make know one time year think people take see come two want way look first new day use man
find give tell good physical·education woman child work call world school try last ask feel three family put old keep
student let great big begin help talk turn hand show place week hear question play run small move
(then 61–100: night live bring next million home water room write mother yes money story young month lot study book
eye ping-pong job word four kind head black long little house friend father sit hour game stand bad meet car city name)

**zk-new (1,949)** — other thing have·to life need state become go·in·for high leave mean go·on group seem country
get·on problem start part case get·on·with company system program get·to government number point in·all believe
hold happen large get·up area national fact from·time·to·time different business side provide in·time service
important power on·time line end lose so·that member pay law include and·so·on continue set community think·about

**gk-new (1,255)** — issue political guy policy economic rate drug leader military tax site court image data source
evidence billion opportunity administration campaign current involve defense security seek author represent agency
movement concern series significant factor decade scene career treatment approach organisation fund occur individual
identify determine indicate region election sex professor financial crime authority sort strategy claim remove legal
cell establish trial

**cet4-new (1,726)** — federal republican congress stock media growth analysis democratic executive entire religious
management statement employee production sexual agent consumer shot senate relation effective troop investigation
researcher argument possibility define presence reader willing understanding contribute protection additional
associate critic intelligence connection learning hell democracy colleague writing expression reading married
father-in-law emotional supreme poll teaching trail code jury prime regulation revenue appearance obvious

**cet6-new (3,850)** — environmental democrat cultural attorney participant concerned involved voter assessment
presidential regional analyst investor hearing catholic aids producer regime perception opposition judgment abortion
sector fishing curriculum assistance asset proceeding creation funding therapy existing planning cop well-off
participation album coalition negotiation investigator suicide enforcement marketing congressional involvement
championship spending evaluation deficit ally confront peer designer immigration supporter retirement buck diversity
respondent historian

### 2.2 Requested positions

| word | stage | today (frq order) | FACTS §2 candidate | **this policy** |
|---|---|---|---|---|
| monday | xs | 585 | 226 | **378** (weekdays 378–384 in calendar order) |
| january | xs | 582 | 223 | **241** (months 241–252) |
| wednesday | xs | 600 | — | **380** |
| colour | xs | 574 | 216 | **191** |
| schoolbag | xs | 595 | 236 | **565** (unknown pool, 9th of 9 — collins 0, no components) |
| is | xs | 581 | 593 | **273** (be 270 · am 271 · are 272 · is 273) |
| the | xs | 1 | 521 | **266** (first grammar word) |
| hello | xs | 435 | 598 | **171** (yes 174→71 · hi 427→119 · hello 171 · goodbye 523→224) |
| one | xs | 44 | 7 | **6** |
| first | xs | 73 | 24 | **18** |
| not | xs | 26 | 1 | **126** (first adverb) |
| very | xs | 88 | 35 | **265** |
| a lot of | — | not in the database (no row) | — | — |
| look after | zk-new | 1755 (NULL-frq block starts at 1501) | 687+ | **231** |

Further positions (policy): xs — mother 70, book 78, father 91, teacher 129, red 177, dog 212, blue 223, tv 208,
mr. 262, i 309, you 322, he 327, in 291, on 336, cat 401, apple 459, pen 517, under 571, bye 579. zk-new — centre 72,
programme 93, would like 99, better 149, because of 183, be good at 213, uk 239, such as 375, american 456 (first
proper noun), london 493, britain 531, would 950, could 975, although 1346, unless 1704, grey 1397, queen 1643. cet4-new
— oh 485, simply 405, via 991, whereas 1081, whilst 1347. cet6-new — yeah 618, alas 1121, versus 2023.

### 2.3 Required counts

| metric | xs | zk-new | gk-new | cet4-new | cet6-new |
|---|---|---|---|---|---|
| closed-class words in the first 30 (policy class closed+glued) | **0** | **0** | **0** | **0** | **0** |
| … with the FACTS §2 definition (dominant ∈ FUNCTION_POS or AUX or inherit) | 0 | 0 | 0 | 0 | 0 |
| adverbs + interjections in the first 30 | 0 | 0 | 0 | 0 | 0 |
| first grammar word at card | 266 (`the`) | 921 (`as`) | 659 (`former`) | 857 (`due`) | 2023 (`versus`) |
| first adverb at card | 126 (`not`) | 444 | 316 | 405 | 939 |
| first interjection at card | 71 (`yes`) | — | — | 485 (`oh`) | 618 (`yeah`) |
| phrases in the first 50 / 200 | 1 / 2 (of 2) | **11 / 46** (of 381) | 0 / 1 (of 4) | 0 / 0 (of 0) | 0 / 0 (of 2) |
| zk-new phrases per 100 cards | | 23 23 22 23 22 21 20 20 21 19 20 19 13 19 20 18 18 18 18 4 | | | |
| longest run of consecutive frq-NULL words | **7** (weekdays 378–384, by design) | **2** (`centre go out`, 72–73) | 1 | 1 | 3 (`knowhow commercialise urbanise`, 3823–3825) |
| closed pool positions min / median / max | 266 / 438 / 599 | 921 / 1440 / 1944 | 659 / 978 / 1217 | 857 / 1303 / 1705 | 2023 / 2997 / 3729 |
| adverb pool positions min / median / max | 126 / 348 / 593 | 444 / 1181 / 1942 | 316 / 791 / 1243 | 405 / 1052 / 1720 | 939 / 2400 / 3839 |

Composition (dominant pos / class) — **xs**: first 30 = 16 v · 8 n · 3 m · 2 j · 1 phrase, all content; first 100 =
40 n · 38 v · 12 j · 8 m · 1 interj (`yes`) · 1 NULL-pos phrase (`physical education`), no grammar word; first 300 = 259 content +
12 months + 13 adverbs + 4 interjections + 8 grammar words + 3 glued forms + 1 proper noun. **zk-new**: first 30 = 23
words + 7 词组 (14 n · 7 v · 2 j · 7 NULL-pos phrases); first 100 = 77 + 23 词组; first 300 = 231 + 68 词组 + 1
abbreviation, no adverb, no grammar word. **cet4-new** first 30 = 23 n · 6 j · 1 v; **cet6-new** first 30 = 21 n ·
7 j · 2 NULL-pos.

### 2.4 The xs course as a teacher would read it

Cards 1–30: the 二级 list's most frequent verbs and nouns (say go get make know think take see come want look use
find give tell / time year people way day man woman child) — everyday but *abstract*; the picturable classroom nouns
of Grade 1 (cat pen red) sit at 78 (book) … 517 (pen) because COCA ranks them there. No column encodes concreteness
(§6 #5). Cards 31–100: school family student hand week question home water room mother money story book eye friend
father car city name, first colours (black 86, white 102), numbers to five (four 83, five 101), `yes` at 71. Cards
101–260: girl 124, food 127, teacher 129, boy 132, class 142, red 177, dog 212, blue 223, `hi` (119), `not` (126),
`hello` (171), `goodbye` (224), months (241–252); still no article,
pronoun or preposition. Cards 261–600: grammar words one in every 4–5 cards (`the` 266, `be am are is` 270–273,
`and of a in to have it i that for you he with on do does …`), weekdays (378–384), the rarer numerals, the tail
(hometown astronaut tiger zoo noodle kite panda).

## 3 What the 词库 "全部 / 词频" tab would start with

Today `GET /api/vocab` (stage=all, sort=freq) starts `the be and of a in to have it i that for you he with on do say
this they at but we his from not by she or as`. Under this policy the 全部 tab orders by `COALESCE(stage_min, 6)`
then the key, i.e. the 小学 course first, so it starts exactly like xs: **say go get make know one time year think
people take see come two want way look first new day use man find give tell good physical·education woman child work**
(the key-only order, without the stage grouping, is almost the same list with `other` at 14, `thing` 25 and
`have to` 26 mixed in from zk — the stage grouping is the better reading order and is what a parent browsing the
词库 expects).

Recommendation on the label: keep `sort=freq` ("词频") as the raw dictionary order (`ORDER BY (frq IS NULL OR frq=0),
frq, lemma`, honest to its name) and add `learn` ("学习顺序") as the new **default** of the 词库 page and the only
order used by 筛词 / 每日推荐词 / prewarm. That touches the `VocabSort` union in `schemas.py:503` and
`frontend/src/api/endpoints.ts:133` (pinned by `scripts/check_contract.py`), `zh.vocab.sort` in `zh.ts` with its
byte-for-byte mirror in FRONTEND.md §8, `VocabPage.tsx SORTS`, API.md §20 — all in lockstep. If the owner prefers one
sort, redefine `freq` and rename its copy to 学习顺序; do not leave "词频" on a list that is no longer frequency.

## 4 Tie-break and determinism

* The key is an integer: `eff × 100 + sub`, where every component is a deterministic function of the table —
  `eff` of per-row columns, slots of the stage's sorted content ranks with `floor`, set anchors with `median_low`,
  component ranks of lemma look-ups, glue of the `inherit:*` token. No randomness, no clock, no insertion order
  (verified: shuffled input → identical keys).
* Total order: `(distance, key, lemma, id)`. `lemma` is unique (the seed importer upserts by lemma; verified on the
  copy), so `id` never decides in practice but makes the order total even if a future schema allowed duplicates.
  Equal keys happen only inside a slot (two pool members mapped to the same quantile) or when a content word and a
  pool member share a rank — then `lemma` decides, which is what the existing `, w.lemma` tail already does.
* Equal ranks among content words (e.g. `color` 697 and another frq-697 word) keep today's lemma tie-break.
* The sub-key encodes class precedence at equal rank (content 0 < set 1–19 < unknown 40 < interj 50 < proper 55 <
  adverb 60 < closed 80 < glued 81–89), so the policy never depends on the SQL engine's NULL or collation behaviour.
* Stability under change: a seed re-import with the same content sha256 reproduces every key bit for bit. A new word
  with a rank shifts the stage's quantile function by one position — pool members may move by one slot (a few cards),
  content words never move relative to each other. That is why the key is recomputed as one pass after each import
  (and stored), not evaluated per query: the cross-row inputs must be read from one consistent snapshot.
* 课标外 (`stage_min IS NULL`) and runtime words get `distance 11`; a missing key sorts last within its group
  (`learn_key IS NULL` first in the ORDER BY) — the C10 warning becomes "a hand-inserted row sorts LAST until the key is
  recomputed", which is the safe direction.

## 5 How the rule degrades

* **Claude-label pos (`'v./n.'`, `'abbr.'`)**: `dominant_pos` returns `None` → class *content* (never closed/adverb),
  exactly like the image gate (D-images-24). A Claude-created adverb or pronoun would therefore be treated as a content
  word; acceptable because such words are 课标外 (`stage_min` NULL → distance 11) and only ever reach the 全部 tab
  tail, lookups and the owner's own bank. If a later consolidation rewrites `pos` into a share string, the next
  recompute reclassifies it — no code path depends on the class being stable.
* **Runtime-created words with no frq/bnc** (`_create_provisional`, `_resolve_ecdict` when ECDICT has no rank): R1
  gives NULL → unknown pool of the 课标外 group → slotted across that group (median 12617) at the next recompute; until
  then `learn_key IS NULL` sorts last within distance 11. When a lookup later fills `frq` (services/words.py:284/579/
  593/673) the word gets a real rank at the next recompute. None of this touches stage words.
* **Words with neither rank nor components** (schoolbag, email, mr., mrs., ms., p.e.): collins band midpoint if
  collins > 0, else the end of the unknown pool in (oxford ↓, lemma) order — arbitrary but deterministic; in xs they
  fall at 193 (email, oxford 1), 262, 338, 418, 491, 565. A teacher would put `schoolbag` and `Mr.` in week one; only a
  curated starter list can (§6 #5).
* **Phrases whose tokens are not lemmas** (`according to`, `be made of`, `kung fu`): missing tokens count as the stage
  median → mid-course, never first, never last.
* **Mis-tagged pos**: `am` r:100 (glued, so harmless), `march` v, `august` j, `may` v (set, so harmless), `bye`
  n:54 (content, rank 18387 → 5669 → card 579), `ok` r:100 (adverb, 514). The set and glue rules absorb the four that
  matter for 小学; `bye`/`ok` stay late and are the price of not hand-curating.
* **A stage with an empty pool or an empty content set** (mini seed in tests): `Q` of an empty `C` returns 0, pool
  members get key `sub` only — still deterministic; a test fixture with 62 words produces a stable, if meaningless,
  order.

## 6 Open choices left to the product owner (with recommendation)

1. **Grammar-word window: slots from 50 % (as simulated) vs hard "closed last" vs offset.** Measured: slots → `the`
   266, `is` 273, one grammar word per 4–5 cards to the end; hard-last → `the` 526, `is` 530, grammar words 526–600
   (never reached by a pupil who stops at 500); offset → 36 of 71 grammar words lumped between 274 and 319. **Recommend
   slots from 50 %**: a Grade 3–6 pupil who has ~260 words is making sentences and the cards become "check you know it";
   for adults all three variants are indistinguishable.
2. **Interjections: own window 10–50 % (simulated) vs content vs plain adverb pool.** `hello` → 171 vs 436 (content
   for xs only) vs 566; cet4 `oh` → 485 vs 1 (!) when interjections are content for every stage, as in the FACTS §2
   candidate, vs ≈405 in the adverb pool (it is the lowest-ranked cet4 adverb). **Recommend the own window** — it is the
   only variant that serves both pupils and adults.
3. **Phrase spread: even slots over the whole stage (simulated) vs direct component rank vs slots from 10 %.** Direct
   rank gives 48 phrases in the first 50 and 137 in the first 200 of zk-new, with a 37-long run of rank-less cards —
   rejected. Slots from 10 % would postpone the first 词组 to card ~140. **Recommend 0–100 %**: `have to` as card 3 of
   初中 is right (中考 phrases are day-one material), and 18–23 per 100 cards is proportional to the 381/1949 share.
4. **Proper-noun pool (25–100 %) vs content.** `london` 493 vs 42, `britain` 531 vs 98, `england` 568 vs 123 in zk-new;
   `american` 456. **Recommend the pool**: geography is an appendix topic and the BNC fallback is British-biased.
5. **A curated starter list** (hello goodbye thank-you sorry yes no cat dog red blue book pen schoolbag Mr. …) carried as
   a seed token (`starter`) or an `overrides.tsv` column, placed before everything in xs. It is the *only* way to
   make the first 30 cards look like a Grade 1 textbook unit — the columns cannot express concreteness (first 30 today
   under this policy: say go get make know …). It is outside the "columns only" brief, so it is the owner's call.
   **Recommend: not for the first invited pupils** (they are Grade 3+, the 二级 list by rank is defensible), revisit after
   the first feedback; an alternative lever inside the row is the number of translation lines (polysemy ≈ abstractness),
   also outside the allowed inputs and therefore not used here.
6. **Numerals as sets** (one–ten, eleven–twenty, tens, ordinals) like months. Today's rank order is already small→large
   (one 6, two 14, three 38, four 83, five 101, six 141 …) with one oddity (`million` 65, `hundred` 184, `thousand` 195).
   **Recommend no**: a cardinals block would push `one/two` to ~card 60 for no gain.
7. **Blend `frq` and `bnc`** (geometric mean when both exist) to dampen COCA's US-politics bias: cet4-new would start
   `management analysis media production growth statement stock relation …` instead of `federal republican congress`;
   but `color` (bnc 24372) would fall from card 203 to ~330 in xs and every American spelling pays the same price.
   **Recommend not now** — frq primary as simulated; revisit with a spelling-variant-aware blend.
8. **Cap constants** (Collins 5/4/3 → 1500/3000/6000, Oxford → 5000, compression 20). 467 movers, inspected top 40 all
   plausible. **Recommend as simulated**; expose the five numbers as module constants pinned by a test, not as settings.
9. **Pronouns**: closed (simulated: i 309, you 322, he 327, it 304) vs adverb pool (would start ~126). **Recommend
   closed** — pronoun cards teach nothing a pattern drill does not; 筛词 marks them known in a second.
10. **Which sites follow the order**: 词库 default sort, 筛词 `screen_next`, 推荐词 `_SCREEN_ORDER` (two identical
    `_STAGE_DISTANCE` copies — unify), admin prewarm (`prewarm.candidates`, so content is generated for the cards
    learners meet first). **Recommend all four**; keep lookup prefix suggestions (`routers/words.py:106`) on raw frq —
    that is a search convenience, not a course.
11. **`difficulty` (Claude 1–5, 79 words)**: ignore in the learn key (as simulated) vs cap `eff` when set. **Recommend
    ignore** — too sparse to matter, and the 难度 sort already exists for it.
12. **课标外 words**: keep rank order inside their group (simulated) vs alphabetical. **Recommend rank** (they only
    appear in the 全部 tail and lookups).

## 7 Appendix — constants and reproducibility

| constant | value | where it would live |
|---|---|---|
| CLOSED_POS | `FUNCTION_POS − {u}` = {i c d p a t} | next to `FUNCTION_POS` (images/style.py) or a new `wd/order.py` |
| AUX ∪ {an} | 25 lemmas + `an` | same module (AUX already exists in the FACTS candidate) |
| MONTHS / WEEKDAYS | 12 + 7 lemmas, calendar order | same module; `wd check db` invariant: every member present in xs |
| CAP_COLLINS / CAP_OXFORD / CAP_COMPRESS | {5:1500, 4:3000, 3:6000} / 5000 / 20 | same module |
| BAND_MID | {5:350, 4:1200, 3:2500, 2:5000, 1:10000} | same module |
| WINDOW | unknown 0–1 · interj .1–.5 · proper .25–1 · adverb .25–1 · closed .5–1 | same module |
| SUB | content 0 · set 1–19 · unknown 40 · interj 50 · proper 55 · adverb 60 · closed 80 · glued 81+ | same module |
| STAGE_NULL_DISTANCE | 11 | `_STAGE_DISTANCE` (screen.py / batches.py) |

Per-stage medians and pool sizes are *derived*, never constants: they belong in `data/seed/stats.json` /
`kv.learn_order.stats` after each recompute, as the conventions require.

Re-run: `cd /private/tmp/claude-501/-Users-sqin-word-dance/0be1d882-e939-4b1e-8c2e-b69435664161/scratchpad/order/sim-pedagogy-first && /Users/sqin/word-dance/.venv/bin/python -I simulate.py && /Users/sqin/word-dance/.venv/bin/python -I positions.py`.
`results.md` carries the full xs order (600 positions), the zk-new first 300, the cap-mover list and all variant
numbers; `results.json` the same as data.
