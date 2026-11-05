# S5b `images-fetch-chain` 实现评审（对抗式）

评审对象：工作区里 S5b 的 18 个文件（基线 `main @ 75df534`，S5a 已交付 `style.py`、`select.keyword_tokens/is_blocked` 三分黑名单、store 四列）——`backend/wd/images/{select,handler,service,__init__}.py`、`backend/wd/images/providers/{base,wikimedia,openverse,pixabay,pexels}.py`、`backend/wd/interfaces.py`、`backend/wd/jobs/scheduler.py`、`backend/wd/cli.py`、`docs/DEPLOY.md`（§9 CLI 行）、`backend/tests/unit/{test_select,test_providers,test_scheduler,test_cli}.py`、`backend/tests/integration/test_images.py`。规格：PLAN §1 R-15/R-16、§5.1 C5–C8、§5.3、§6 S5；`design/images/SYNTHESIS.md` §3.3.1–3.3.4、§4.1 C5–C8、§5.1/§5.2、D-images-9/10/11/12/13。

评审过程没有修改任何仓库文件：5 处突变试验都是「cp 备份 → 写坏 → 跑目标测试 → cp 恢复 → `cmp` 逐字节核对」，四个被改过的文件（`select.py`、`service.py`、`wikimedia.py`、`handler.py`）结束时与备份 `cmp` 相同。`git diff | shasum` 在开始/结束时不同（`2960c333…` → `5f8c2ec3…`），**差异全部在 S3 的 `data/seed/ATTRIBUTION.md`/`data/seed/DIFF.md`**（`overrides_applied 23 → 22`，并行切片在我评审期间写入），S5b 的任何文件 hunks 未变；`git status --short` 的集合相同。排练只用 `$SCRATCH/s5b-review/rehearsal/`（从 `$SCRATCH/s5a-rehearsal/word-dance.db` `VACUUM INTO` 出来的私有拷贝，`schema_migrations` 1/8/9/10/11/12/13、`word_images` 27 列、18 个 `failed` 词）；没有启动 `wd serve`、没有 kill 进程、没有联网。

## 0 结论

**通过，但有 1 条 major 必须在合入前修**（F-1：功能词门对**已有在用图片**的词把 `image_state` 覆盖成 `failed`，线上词 `despite` 正是这种情况；一行修复 + 一条测试）。其余 3 条 minor（空 kid 链回落到整条链、Pixabay `vector/*` 类型不命中 `STYLE_TARGET`、文档串/日志字段细节）。实现与 PLAN §5.1 C5–C8 逐条对得上：三分黑名单 + 查询 token 豁免、功能词门不发请求不入队 SVG、管理员 `query` 被丢弃 → `query_ignored` 日志 + `detail` 前缀 + API 仍 202、副词不搜裸 lemma、五个打分信号且 `test_score_table` 的 hunks 为 0、重试四常量/三函数/`payload.retry`/`TickResult.image_retries`/`image_retry` 事件/`wd images-retry`、Commons `filetype:drawing`/`thumbmime`/`maxlag=5`→503、Openverse `page_size=10`/`category=illustration`、Pixabay `image_type`、Pexels 透传且不进 kid 轮、`PREWARM_SKIP_PROVIDERS`、默认链形状只多三项（由测试全字典断言）。验收三条命令全部通过（245 passed；dry-run 16 词、无功能词；`fetch-image of --no-svg` → `skipped / function word: card only`）。5 个人工突变全部被新测试抓住；没有发现断言被削弱（`test_keywords_come_from_content_with_blocklist_and_shape_filter` 按 SYNTHESIS §5.1 把夹具词改为 `apple`，原断言保留并新增 lemma 豁免测试）。实现者自报的 5 处偏离都成立且可接受（见 §4）。

## 1 验收命令复跑

| 命令 | 结果 |
|---|---|
| `.venv/bin/python -m pytest -q backend/tests/unit/test_select.py …test_providers.py …test_scheduler.py …test_cli.py …test_style.py …test_sanitize_svg.py backend/tests/integration/test_images.py backend/tests/unit/test_docs_contract.py -k "not test_deploy_files and not test_defaults_without_environment"` | **`245 passed in 3.47s`**，exit 0 |
| `WD_DATA_DIR=$M WD_SMOKE_MOCK_HTTP=1 WD_DEV=1 .venv/bin/wd images-retry --dry-run`（私有拷贝；shell 里 `env -u HTTP_PROXY -u HTTPS_PROXY`） | `would requeue 16 failed-image word(s) being studied (limit 50; >= 6 h …, <= 3 …, function words excluded)`，列表 `consumer critical directly effective global investment mission option original professional property recall release senate species threat`；18 个 failed 词里排除了 `of`（`i:100`，功能词门）与 `employee`（不在学）——与 PLAN §5.3「≤ 17、无功能词」一致。`directly`（`r:100`）在列：副词不在门内，按 D-images-9 允许重试（但不搜裸 lemma） |
| `WD_DATA_DIR=$M WD_SMOKE_MOCK_HTTP=1 WD_DEV=1 .venv/bin/wd fetch-image of --no-svg` | `word: of (id 1235) / status: skipped / detail: function word: card only`，**exit 0**；`of` 行 `image_state failed`、`active_image_id NULL`；无 provider 请求（mock 未被调用） |
| 实现者留下的全量日志 `$SCRATCH/s5b-full-tests.log`（未复跑，3.5 min） | `4 failed, 1835 passed, 3 skipped, 34 deselected`：失败的 `test_failover_flow / test_backup / test_failover / test_runner` 都是 `system_events` 里多了 `'migration'` 事件（S1 的 0011 写 `kind='migration'`），不属于 S5b、与 S5b 改动无关 |

## 2 发现（按严重度）

### F-1 major — 功能词门对已有在用图片的词把 `image_state` 覆盖成 `failed`，与在用图片矛盾且永不自愈

- 位置：`backend/wd/images/handler.py:236-241`（`if not explicit and style.skip_image(word): store.set_image_state(conn, word_id, STATUS_FAILED, now=now); return FetchOutcome(STATUS_SKIPPED, …)`）。
- 证据：线上副本里 **`despite`（`i:100`）的 `active_image_id = 7`（`claude_svg`，`status active`），`image_state = 'ready'`**。在私有拷贝上 `wd fetch-image despite --no-svg`（等价于用户点 换一张 `request_refresh`：无 `provider`/`query` → 不是 explicit）→ `status: skipped`，之后 `image_state = 'failed'` 而 `active_image_id` 仍为 7、`service.image_meta(...)['kind'] == 'svg'`。同一函数的链尾（`handler.py:289`）明确维护 `STATUS_READY if has_active else STATUS_FAILED`，门没有。
- 后果：`words` 进入「failed + 有在用图」的矛盾态；`diag.py:271` 的 `SUM(image_state = 'ready')` 少计；夜间 `retry_failed_studied` 对功能词跳过，所以这个状态不会自愈；`content.py:259-264`（内容重生成）看到非 `ready` 会再排一次 fetch → 门 → 再 `failed`（无请求，但状态仍错）。规格 SYNTHESIS §3.3.1 第 3 步确实写的是直接置 `failed`——规格漏了「已有在用图」的情形；PLAN C5 的意图「模板卡」隐含没有在用图。
- 修法：门内先 `has_active = service.active_image_row(conn, word_id) is not None`，`set_image_state(..., STATUS_READY if has_active else STATUS_FAILED)`，`detail` 在有图时加 `(current image kept)`（与链尾一致）；`test_images.py` 加一条：功能词 + 在用 SVG + `request_refresh` → `image_state` 仍 `ready`、图未变、`mock_http.calls == []`。

### F-2 minor — kid 轮的 provider 集合为空时回落成整条链（实现者已自报、未改）

- 位置：`handler.py:136-145 search_rounds` + `providers/__init__.py build_chain` 的 `names or cfg.image_providers`。复现：`image_providers=("pexels",)`、`image_kid_stages=("xs",)` → `search_rounds == (("kid", ()), ("neutral", ("pexels",)))`，`build_chain(cfg, ()) == ['pexels']` → Pexels 被以 `style="kid"` 多搜一轮（它忽略 style，结果与 neutral 轮重复，白花一次 keyed 配额）。
- 修法：`fetch_for_word` 的轮次循环里 `if not names: continue`（或 `search_rounds` 过滤掉空轮）。只在 `WD_IMAGE_KID_STAGES` 非空且链只有 Pexels 时触发，默认关。

### F-3 minor — `STYLE_TARGET["kid"]` 的 `vector` 对 Pixabay 真实 `type` 值不命中

- 位置：`select.py:38 STYLE_TARGET`、`:108 media_category`。Pixabay API 的 hit `type` 对矢量图返回 `vector/svg` / `vector/ai`（文档口径；本机无网未能复核），`media_category` 原样小写后既不在 kid 目标也不在 neutral 目标 → 0 分而不是 +1。规格 D-images-12 本身写的是 `vector`，所以是规格级的遗漏；`media_category` 取 `value.split("/")[0]` 即可覆盖，`test_score_provider_category_matches_the_round_target` 加一例 `type: "vector/svg"`。

### F-4 minor — 文档串与日志字段

- `backend/wd/images/providers/__init__.py:3` 仍写 `search(query, limit)`（不在 S5b 清单，实现者已列为请求）。
- `scheduler.py:376` 的 `extra={"event": "image_retry", "word_ids": word_ids}`：`logging_setup.EXTRA_FIELDS` 没有 `word_ids`，JsonFormatter 会丢掉它——journal 里只剩「requeued N」，看不到是哪些词；把 id 放进消息文本，或（S6/S7）把 `word_ids` 加进 `EXTRA_FIELDS`。
- `handler.py:449 cmd_images_retry` 打印 lemma 按 `ORDER BY id`，不是 sweep 的 `updated_at, id` 顺序（`--limit` 截断时看到的顺序与实际入队顺序不一致，纯展示）。
- `select.is_blocked` 的豁免以 `NON_PHOTO_RE` 的 `group(1)` 为单位，多词条目 `coat of arms` 永远无法经 `keyword_tokens` 豁免（`test_non_photo_words_are_allowed_when_they_are_query_tokens` 明确钉住了这个行为）；只影响 lemma 恰为 `coat of arms` 的情形，记录即可。

## 3 规格逐条核查（PLAN §5.1 C5–C8 ↔ 代码/测试）

| 规格 | 代码 | 测试 |
|---|---|---|
| C5 `UNSAFE_RE`/`NON_PHOTO_RE`/`KID_UNSAFE_RE` 词表逐词、删 `BLOCKLIST_RE`、`is_blocked(text, *, allow, style)`、`keyword_tokens -> frozenset` | `select.py:32-34,55-71`；`grep BLOCKLIST_RE backend scripts` 只剩 `test_select.py` 的 `not hasattr` 断言；`content.py:68-71 _is_blocked(keyword, lemma)` 已用新签名；`wd` 内再无旧签名调用 | `test_blocklist_splits_into_unsafe_non_photo_and_kid_unsafe`、`test_non_photo_words_are_allowed_when_they_are_query_tokens`、`test_kid_style_rejects_kid_unsafe_words`、`test_reject_reason_honours_the_query_token_exemption_and_the_kid_list` |
| C5 `clean_keywords(values, lemma, *, allow_lemma) -> (kept, dropped)`，lemma token 豁免 | `handler.py:80-101` | `test_keywords_come_from_content_with_blocklist_and_shape_filter`（夹具词 → `apple`，原断言保留）、`test_lemma_token_is_exempt_from_the_non_photo_blocklist`（`chart` 保留 "bar chart"；`gun` 的 "toy gun" 仍丢） |
| C5 SELECT 加 `kind, pos, stage_min`；功能词门（无 provider/query）→ `failed` + `skipped "function word: card only"`，不发请求不入队 SVG | `handler.py:224-241` | `test_function_word_without_admin_override_gets_the_card_and_no_provider_call`（5 种 pos、`mock_http.calls == []`、无 svg job、CLI 输出）；**见 F-1** |
| C5 管理员 `query` 被丢 → `query_ignored` 日志 + `detail` 前缀，API 仍 202 | `handler.py:247-254`、`_with_prefix` | `test_admin_query_dropped_by_shape_rule_is_reported`（`caplog` 事件、`detail` 四种形态；`admin_refetch` 路径即 API.md 69 的入队，路由未改所以仍 202） |
| C5 副词无可用关键词不搜裸 lemma | `handler.py:256,267-281`（`allow_lemma=style.allows_bare_lemma(word)`，空则跳过轮次直达 SVG/卡判定） | `test_adverb_without_content_keywords_skips_the_bare_lemma_search`（`very`/`why` 无请求、SVG 仍入队；`fast` 有关键词照搜；`ice cream` 无 pos 仍搜裸 lemma） |
| C6 五信号 + `MIN_SCORE=1` + `test_score_table` 不变 + Openverse `extra["category"]` | `select.py:118-165`；`openverse.py:126` | 五条各一测试 + `test_rank_orders_by_the_new_signals_too`；`git diff -U0 test_select.py | grep -c test_score_table` = 0 |
| C7 四常量、`retry_due`/`retry_if_failed`/`retry_failed_studied`、`enqueue_fetch(retry=True)`、导出 | `service.py:36-41,255-346`；`__init__.py` 导出两函数（+四常量） | `test_failed_word_is_retried_when_marked_unfamiliar_after_six_hours`（1 h 不、6 h 是、live 任务阻断、功能词不、从未抓过立即）、`test_retry_is_capped_at_three_per_thirty_days`（第 4 次拒、换一张不计数、31 天后清零）、`test_nightly_retry_requeues_only_studied_failed_words_within_limit`（bank new/learning、开放批次、known/未学/功能词排除、`limit`、`dry_run`） |
| C7 `scheduler.maintenance` 在 `prefetch` 之后、`TickResult.image_retries`、tick 打印 | `scheduler.py:366-400,544-547` | `test_maintenance_requeues_failed_image_words_being_studied`（`image_retries == 1`、`priority 30`、`payload {"word_id","retry":true}`、`image_retry` 事件、`images_enabled=False` 不排） |
| C7 CLI `images-retry [--limit N] [--dry-run]` + `COMMAND_OWNERS` + DEPLOY §9 | `handler.py:437-460,477-480`；`cli.py:54`；`DEPLOY.md:420` | `test_images_retry_is_owned_and_registered_by_the_images_handler`、`test_cli_images_retry_dry_run_lists_candidates` |
| C8 接口 `search(query, limit, *, style="neutral")`；Commons `drawing`/`thumbmime`/`maxlag=5`/200-体 maxlag → 503 + Retry-After or 30、`get_json_with_headers`、`mime = thumbmime or mime`；Openverse 删 `PAGE_SIZE`、`page_size=max(1,min(limit,20))`、kid `category=illustration`；Pixabay `image_type`；Pexels 透传 | `interfaces.py:77`；`wikimedia.py:34-73,114`；`base.py:100-128`；`openverse.py:31-49,126`；`pixabay.py:24,34-49`；`pexels.py:34` | `test_wikimedia_request_shape_and_user_agent`、`test_wikimedia_maxlag_body_becomes_a_503_provider_error`、`test_wikimedia_kid_style_uses_drawing_and_thumbmime_as_candidate_mime`、`test_openverse_page_size_follows_limit_and_category_for_kid`、`test_pixabay_image_type_follows_style`、`test_pexels_request_and_parse`、`test_every_provider_implements_the_style_keyword`；集成 `test_wikimedia_maxlag_body_puts_commons_in_cooldown_and_the_chain_moves_on`（`cooldown_until +7s` / 无头 `+30s`） |
| C8 handler 两轮 `((kid, chain−pexels), (neutral, chain))` 仅当 kid 且无管理员 provider；`PREWARM_SKIP_PROVIDERS` 于 ≥ 90；neutral 轮不加 `category`/`orientation`；默认链形状只多三项 | `handler.py:52-55,136-145,169-171,267-281` | `test_kid_stage_word_tries_drawing_then_bitmap`（两轮顺序、Pexels 不在 kid 轮、显式 provider 单轮、默认配置无 kid 轮）、`test_prewarm_priority_skips_openverse_pixabay_and_pexels`、`test_default_chain_shape_is_unchanged_except_thumbmime_maxlag_page_size`（Commons/Openverse 参数全字典） |
| R-16 不做 `bank.py`/`batches.py` 即时挂点 | `git diff` 未触及两文件的 images 调用（S2 并行改的是阶段默认） | — |

## 4 实现者自报偏离的评估

1. `wd fetch-image` 对 `skipped` 退出 0：接受。`scripts/`、`Makefile`、`deploy/` 没有任何调用依赖 `fetch-image` 的退出码；PLAN/SYNTHESIS 未规定退出码，门的答案不是失败。
2. `scheduler.retry_failed_images(conn, now, *, cfg)` 包装 + `images_enabled` 门：接受，优于 SYNTHESIS 的内联草图（否则 `enqueue_fetch` 置 `queued` 后 handler `skipped, images disabled` 会让词卡在 `queued`）；`wd images-retry` 同样短路。
3. `clean_keywords` 收满 3 个后继续遍历只为收集 `dropped`：接受，`kept` 结果与旧代码相同。
4. `clean_keywords` 不传 `style`：与 SYNTHESIS 签名一致，kid 不安全词在候选层被 `reject_reason(style="kid")` 拒。
5. 空 kid 链回落整条链：见 F-2（minor，默认关）。

## 5 测试质量（突变试验，全部已按字节恢复）

| 突变 | 被抓住的测试 |
|---|---|
| `select.py`：`PEOPLE_RE` 扣分不再限于 kid | `test_score_people_words_cost_two_only_in_the_kid_style`、`test_rank_orders_by_the_new_signals_too`（2 failed / 53 passed） |
| `service.py`：`auto_retries_30d < 3` → `<= 3` | `test_retry_is_capped_at_three_per_thirty_days` |
| `wikimedia.py`：maxlag 映射失效 | `test_wikimedia_maxlag_body_becomes_a_503_provider_error`、集成 `test_wikimedia_maxlag_body_puts_commons_in_cooldown_and_the_chain_moves_on` |
| `handler.py`：门不再写 `image_state='failed'` | `test_function_word_without_admin_override_gets_the_card_and_no_provider_call` |
| `handler.py`：Pexels 不再被排除出 kid 轮 | `test_kid_stage_word_tries_drawing_then_bitmap` |

其他观察：`test_cli_images_retry_dry_run_lists_candidates` 的 `"of" not in out.replace("would", "")` 是子串断言，夹具 lemma 换成含 `of` 的词（如 `coffee`）会误红——现在绿，属脆弱而非错误。新测试没有削弱任何既有断言；`test_malformed_candidate_urls_and_provider_crashes_never_kill_the_job` 的 `boom` 签名跟着接口加了 `*, style="neutral"`，语义不变。

## 6 给其他切片 / S7 的提醒

- S7：F-1 修完后重跑 `test_images.py`；全量日志里 4 个 `system_events == ['claude_flag_error']` 类失败来自 0011 的 `migration` 事件（S1），需要在对应测试里过滤 `kind='migration'`。
- S6：`DESIGN.md §9` 伪代码应写入 C5 门的「已有在用图则保留」（F-1 修后的行为）；`ops.md:205` 已含 `wd images-retry --dry-run`。
- `providers/__init__.py:3` 文档串（F-4）归 S5 清单外，交 S7 一并改。
