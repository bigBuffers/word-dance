# Live facts from the owner's Mac deployment (read-only queries, 2026-11-04)

Data dir: /Users/sqin/word-dance-data (service running, worker lease live).

## .env (non-secret keys)
WD_AI_ENABLED=1, WD_AI_MODEL=sonnet, WD_ECDICT_DB_PATH="" (ECDICT not installed), WD_SEED_PATH="" (repo default),
WD_REGISTRATION_MODE=invite, WD_IMAGES_ENABLED=1, budgets at defaults (3/day, 40/month, prewarm 1/day, svg 0.5/day, 60 calls/h).

## Library tables
| table | count | notes |
|---|---|---|
| words | 9,162 | all source=seed, is_public=1, is_valid_english=1; 0 user-created |
| word_forms | 14,132 | |
| word_contents | 48 | 48 distinct words, prompt_version content-v1, model claude-sonnet-5-5, status active |
| word_images | 31 | 30 claude_svg, 1 wikimedia |
| words.content_state | none 9,114 / ready 48 | image_state among ready: ready 31 / failed 17 |
| users / user_words | 1 / 52 | |
| bank_suggestions / content_reports | 6 / 0 | |

## jobs (all done)
generate_content 48, fetch_image 48, generate_svg 33, consolidate_bank 3.

## ai_calls
content: 9 success ($0.279) + 12 auth failures; svg: 33 ($0.408); consolidate: 3 ($0.059); probe: 4 ($0.014).

## kv
seed_version a68127812a43c47ff011828b7894b789ba0fcf69cc8e76f1ec6c2356e81a3336, seed_imported_at 2026-11-02T07:36:59Z,
claude.available=1, claude.flag_tier=1, claude.paused_until 2026-11-03T02:56:20Z (expired), public_url_guess http://10.23.147.103:8000.

## Seed history
data/seed/vocab.jsonl.gz committed once in 99a26e3 (2026-10-14); importer code fa82106; never changed since.
