# 核验：配图流水线事实文件（facts/images-pipeline.md）

核验者 slug：`verify-images-pipeline`。被核验文件：`docs/analysis/2026-11-05-stages-regions-images/facts/images-pipeline.md`（作者：另一名代理，主题 images-pipeline，类型：读代码）。基线：`/Users/sqin/word-dance` @ `75df534c48628adc84e67d8f83553641600aee8f`（main），核验日期 2026-11-05。默认立场：怀疑；每条独立重开文件、重跑 SQL、重访 URL。

## 范围与方法

- 重新打开并逐行核对的代码：`backend/wd/images/{handler,select,service,store,fetch,quota,sanitize_svg,card_svg}.py`、`backend/wd/images/providers/{base,wikimedia,openverse,pixabay,pexels}.py`、`backend/wd/ai/{svg,content,budget}.py`、`backend/wd/ai/prompts/{svg_system,content_system}.txt`、`backend/wd/ai/schemas/svg_v1.json`、`backend/wd/config.py`、`backend/wd/interfaces.py`、`backend/wd/schemas.py`、`backend/wd/routers/{words,admin_ops,admin_reports,media}.py`、`backend/wd/main.py`、`backend/wd/migrations/0001_init.sql`、`backend/wd/jobs/{scheduler,worker,queue}.py`、`backend/wd/services/bank.py`、`frontend/src/components/study/{WordImage,StudyCard}.tsx`、`frontend/src/components/study/study.css`、`frontend/src/styles/tokens.css`、`frontend/src/pages/{StudyPage,WordDetailPage,AdminPage}.tsx`、`frontend/src/api/{endpoints,types}.ts`、`frontend/src/i18n/zh.ts`；测试 `backend/tests/unit/test_select.py`、`backend/tests/integration/test_images.py`；fixtures `wikimedia_search.json`、`openverse_search.json`；文档 `docs/CLAUDE_INTEGRATION.md`、`docs/DESIGN.md`、`docs/ops.md`、`docs/DEPLOY.md`、`ATTRIBUTION.md`。全库 grep：`fetch_for_word`、`enqueue_image`、`enqueue_fetch`、`"fetch_image"`、`adminRefetchImage`、`onImageRefresh|onImageFlag`、`images/generations`、`PREFETCH_PRIORITY`、`IMAGE_REFRESH_DAILY_CAP`。
- 线上只读副本 `…/scratchpad/live-copy.db`（`sqlite3 -readonly`，只查不改）：`word_images`、`words`、`jobs`、`ai_calls`、`content_reports`、`system_events`、`provider_state`、`provider_usage`、`user_settings`、`word_contents`、`user_words`、`push_items`/`push_batches`。
- 复用作者下载（只用 `sed`/`grep` 读）：`…/scratchpad/images-pipeline/dl-openverse/{restricted_features,rest_framework,image_serializers,field_values,throttle}.py`、`openverse_schema.yaml`、`quickstart.md`。
- 我自己的下载（全部放在 `…/scratchpad/verify-images-pipeline/`，视为不可信数据）：`dl-openverse-headers/`（一次匿名 `GET https://api.openverse.org/v1/images/?q=apple&page_size=1` 的响应头与 1,256 字节 JSON，用 `python3 -I` 解析）；`dl-mediawiki-mime/`（GitHub raw 的 `mime.info`/`MimeMap.php` 返回 14 字节 404 占位，`Defines.php` 12,190 字节但不含 `MEDIATYPE_*`——路径已变，未采用）。
- 网页（均访问 2026-11-05，WebFetch）：mediawiki.org `Help:CirrusSearch`（两段，0–100000 与 100000–117305 字符）、`API:Etiquette`、`API:Imageinfo`、`Help:Extension:WikibaseCirrusSearch`、`Manual:Image_table`；commons.wikimedia.org `Commons:Depicts`、`Commons:Structured_data/Media_search`、`Commons:Reusing_content_outside_Wikimedia`，以及三次 Commons API 只读查询（`titles=File:Example.svg`、`gsrsearch=apple filetype:drawing`、`gsrsearch=haswbstatement:P180=Q89 filetype:bitmap`）；pixabay.com `/api/docs/`、`/service/license-summary/`；pexels.com `/api/documentation/`（`/license/`、`/terms-of-service/`、help.pexels.com 两篇均 403）；docs.bigmodel.cn `cogview-3-flash`、`cogview-4`、`glm-image`、图像生成 API 参考；help.aliyun.com `wan2-2-t2i-flash`、`text-to-image-v2-api-reference`；developers.openai.com `/api/docs/deprecations`（platform.openai.com 301 跳转）；en.wikipedia.org `Picture_superiority_effect`；eurekalert.org 473021。WebSearch：「Pexels License identifiable people bad light」「智谱 GLM-Image 价格」。
- 置信度：高/中/低；「事实」= 直接读到/算到，「推断」= 由事实推出。

---

## 一、逐条核验（保留原编号）

**[头部] 「配图相关代码自 9ab13a5 以来没有任何提交」——确认。**（事实，高）
`git rev-parse HEAD` = `75df534c…`；`git log --oneline 9ab13a5..75df534 -- backend/wd/images backend/wd/ai/svg.py backend/wd/ai/prompts/svg_system.txt frontend/src/components/study/WordImage.tsx docs/DESIGN.md` 输出为空；`git status --porcelain` 对这些路径也为空。

**[images-pipeline-1] 搜索词三来源、不消歧——确认。**（事实，高）
`backend/wd/images/handler.py:134-137`：`if query and query.strip(): keywords = clean_keywords([query], lemma) else: keywords = clean_keywords((content or {}).get("image_keywords") or [], lemma)`；`:37` `MAX_KEYWORDS = 3`；`:78` `return out or [lemma]`。`backend/wd/ai/prompts/content_system.txt:9-10` 的 image_keywords / image_alt_zh 要求与引文一致。live-copy：`have` 的 `image_keywords` = `["holding keys in hand","person holding book","family having dinner"]`，与作者一致。

**[images-pipeline-2] 关键词形状规则、第 4 个关键词永不被搜、管理员 query 静默回退——确认，附两点补充。**（事实，高）
`handler.py:38` `KEYWORD_RE = re.compile(r"^[A-Za-z][A-Za-z ,'-]{1,40}$")`；`backend/wd/ai/content.py:60-61` `KEYWORDS_MAX = 4` + 同一正则；`backend/wd/schemas.py:1351` `query: str | None = Field(default=None, max_length=100)`。补充 1（事实）：线上 49 条 active 内容的关键词个数分布 `SELECT json_array_length(json_extract(content_json,'$.image_keywords')), COUNT(*) FROM word_contents WHERE status='active' GROUP BY 1` → 1 个：2、2 个：8、3 个：39——**今天没有任何内容带第 4 个关键词**，所以「第 4 个永不被搜」在代码上成立、在线上数据上暂无影响。补充 2（事实）：`[lemma]` 回退本身**不过**形状规则与黑名单（`handler.py:78`、`content.py:183-184` 直接 `keywords = [lemma]`），见 [9] 的修正。

**[images-pipeline-3] 每关键词 × 每 provider 各搜一次、最多试 3 个候选、第一个可用即激活——确认，附补充。**（事实，高）
`handler.py:35-36`、`:156-196`（`:182` `for best in select.rank(cands, kw, excluded, used_refs=used_refs)[:CANDIDATES_PER_SEARCH]`，`:187` `return FetchOutcome(STATUS_READY, …)`）。补充：默认 provider 链只有两家（`backend/wd/config.py:157` `image_providers: tuple[str, ...] = ("wikimedia", "openverse")`，`:355` `text("WD_IMAGE_PROVIDERS", "wikimedia,openverse")`；Pixabay/Pexels 仅在给了 key 时追加，`:364-369`），所以默认最坏情况是 3 × 2 = 6 次搜索，「12 次」要同时配置两把 key。

**[images-pipeline-4] Wikimedia 请求参数、限流、CirrusSearch 关键字——修正（一处引文出处错误，其余确认）。**（事实，高）
代码全部确认：`providers/wikimedia.py:40-51`（`"gsrsearch": f"{query} filetype:bitmap"`、`"gsrlimit": max(1, min(int(limit), 50))`、`"iiurlwidth": THUMB_WIDTH`）、`:27` `THUMB_WIDTH = 800`、`:81-83` 只取 `thumburl`；`base.py:223-250` `RateGate`；`config.py:161-162`；`quota.py:26` `WIKIMEDIA_COOLDOWN_S = 15 * 60`；`params()` 里没有 `maxlag`。API:Etiquette（https://www.mediawiki.org/wiki/API:Etiquette ，访问 2026-11-05）确有「There is no hard speed limit on read requests, but be considerate and try not to take a site down.」与「API requests to Wikimedia wikis must include a meaningful User-Agent header」。CirrusSearch（https://www.mediawiki.org/wiki/Help:CirrusSearch ）确有「The following types currently exist: UNKNOWN, BITMAP, DRAWING, AUDIO, VIDEO, MULTIMEDIA, OFFICE, TEXT, EXECUTABLE, ARCHIVE, 3D」以及 `filemime:{MIMEtype}`、`filew/fileh`、`fileres`、`filebits`、`filesize`。**但该页全文（两段 WebFetch 覆盖全部 117,305 字符）不含「SVG」「svg」「vector」字样，并没有「说明 SVG 归为 drawing」**。SVG 属于 DRAWING 这一事实本身成立，证据是 Commons API 实测：`action=query&titles=File:Example.svg&prop=imageinfo&iiprop=url|mime|thumbmime|mediatype|size&iiurlwidth=800`（访问 2026-11-05）→ `mediatype: "DRAWING"`、`mime: "image/svg+xml"`、`thumbmime: "image/png"`。结论：事实正确，出处应改为 Commons API / `API:Imageinfo` 而非 CirrusSearch 帮助页。

**[images-pipeline-5] Openverse 参数、本地限额、可用过滤项、匿名翻页深度、限流默认值——确认，并把「生产匿名值未公开」补成实测数字。**（事实，高）
`providers/openverse.py:41-42`、`:65-72`、`:89-90`；`config.py:163-164`（15/160）；`quota.py:27`；`handler.py:158-159`。下载源码核对：`image_serializers.py:41-55` 定义 `category`/`aspect_ratio`/`size`；`field_values.py:10-26` 三组枚举与作者一致；`restricted_features.py:54-62` `anonymous=20, authenticated=50, privileged=240`，`:64-73` `anonymous=12 * MAX_PAGE_SIZE.anonymous`（= 240）；`rest_framework.py:10-11` `THROTTLE_ANON_BURST … default="5/hour"`、`THROTTLE_ANON_SUSTAINED … default="100/day"`，`:35-36` `"oauth2_client_credentials_sustained": "10000/day"`、`"oauth2_client_credentials_burst": "100/min"`；`openverse_schema.yaml:3150-3166` 确有「Openverse endpoints are rate limited. Anonymous requests should be sufficient for most users.」与「the Terms of Service … disallow scraping under all circumstances.」，且无数字。补充（事实，高）：我在 2026-11-05 14:18 UTC 经本机代理发了**一次**匿名请求 `GET https://api.openverse.org/v1/images/?q=apple&page_size=1`，响应头为 `x-ratelimit-limit-anon_burst: 20/min`、`x-ratelimit-limit-anon_sustained: 200/day`（可用 19 / 199），正文 `page_count: 240`。即 `docs/DESIGN.md:546` 的「20/min burst, 200/day」就是当前生产匿名限额，不只是「项目自测值」；项目的 15/分、160/日在其之下。作者「未解决的问题 3」据此可关闭。

**[images-pipeline-6] Pixabay 参数与官方文档——确认。**（事实，高）
`providers/pixabay.py:30-39`（`image_type: "photo"`、`safesearch: "true"`、`per_page: max(3, min(int(limit), 200))`、`min_width: 400`、`lang: "en"`）、`:54` `largeImageURL` 优先；`quota.py:33` `PIXABAY_LIMITS = (60, 3000)`。官方文档（https://pixabay.com/api/docs/ ，访问 2026-11-05）：「By default, you can make up to 100 requests per 60 seconds.」「Requests must be cached for 24 hours.」「Permanent hotlinking of images (using Pixabay URLs in your app) is not allowed.」；`image_type` = all/photo/illustration/vector，`orientation` = all/horizontal/vertical，`category` 含 education/animals/food/people 等，`per_page` 3–200，`webformatURL` ≤ 640 px，`largeImageURL` ≤ 1280 px；`lang` 列表含 `zh`。（文档另有一句作者没引，见遗漏 O3。）

**[images-pipeline-7] Pexels 参数与官方文档——确认。**（事实，高）
`providers/pexels.py:29-30`（`per_page: max(1, min(int(limit), 80))`、`orientation: "landscape"`）、`:36` `Authorization` 头、`:46` `src.large` 优先、`:54` `title` 取 `alt`、`:64` `tags=[]`；`quota.py:34` `PEXELS_LIMITS = (20, 600)`。官方文档（https://www.pexels.com/api/documentation/ ，访问 2026-11-05）：「By default, the API is rate-limited to 200 requests per hour and 20,000 requests per month.」；`orientation` landscape/portrait/square；`size` large(24MP)/medium(12MP)/small(4MP)；`locale` 含 `zh-TW`、`zh-CN`；`per_page` 「Max: 80」；`src.large` 「W 940px × H 650px (DPR 1)」，另有 `large2x`（DPR 2）、`landscape` 1200×627。

**[images-pipeline-8] 配额/冷却持久化与状态码规则——确认。**（事实，高）
`quota.py:37-47` `limits_for`、`:75-89` `check`、`:96-110` `record`（失败也计数：`handler.py:167`、`:176`）、`:113-121` `cooldown_seconds`；`handler.py:39` `COOLDOWN_STATUSES = (429, 500, 502, 503, 504)`，`:168` `if e.status is None or e.status in COOLDOWN_STATUSES`。

**[images-pipeline-9] 硬拒绝与黑名单——规则部分确认；「副作用」段修正。**（事实，高）
规则确认：`select.py:20-24` 正则与作者逐字一致；`:54-77` `reject_reason`（mature/sensitivity/restrictions/license/mime/size/aspect/blocklist/excluded）。**修正**：作者说「词条 weapon、gun、blood、map、text、document 等连 lemma 都不能作为关键词……等于这些词永远拿不到照片」。实际：(a) 黑名单只过滤传入的 `values`，回退值 `[lemma]` **不经过**黑名单（`handler.py:71` 过滤 `kw`，`:78` `return out or [lemma]`；`content.py:176` 过滤、`:183-184` `if not keywords: keywords = [lemma]`），所以 `weapon` 这个 lemma 会被原样搜索；(b) 正则是整词匹配 `\bweapon\b`，Commons 分类 `Weapons`、标题 `weapons` 不命中；(c) 线上 `weapon` 的内容关键词是 `["medieval swords display","museum armor","airport security scanner"]`（live-copy `word_contents`），没有一个被黑名单挡掉，其 `fetch_image` 任务 77 的结果与其余 48 个任务一样是 `no acceptable photo from any provider`，之后 SVG 任务 87 成功——这张 SVG 不是黑名单造成的。`SELECT … WHERE image_keywords LIKE '%weapon%' OR … '%map%' …` 在 49 条内容里零命中。正确说法：黑名单会丢掉 Claude 给的含这些整词的短语，并拒掉标题/标签/分类/描述里含该整词（单数、独立成词）的候选；lemma 本身仍会被搜索，复数/合成词形式的候选可通过。库中 lemma `blood/chart/cover/document/flag/graph/gun/logo/map/poster/scan/sex/text` 现均为 `image_state='none'`，尚无实证。

**[images-pipeline-10] 7 个打分信号与 election 复算——确认。**（事实，高）
`select.py:80-101` `score`、`:104-128` `rank`（`scored.sort(key=lambda t: (-t[0], t[1]))` 同分保序）。`backend/tests/unit/test_select.py:92-119` 的打分表存在，作者引用的断言在 `:100`：`assert select.score(cand(title="x", tags=[], license="CC0", width=600, height=550), "apple") == 3`。election 复算（live `word_images.id=18`：query `ballot box`，title `Urne Ballot box république`，license `CC0`，存储 516×800，score 8.0）：`keyword_tokens("ballot box")` = [ballot, box] 均命中 → +2；`license_family("CC0")` = cc0 → +3；原图宽 ≥ 800 → +1（`iiurlwidth=800` 的缩略图再被 `thumbnail((800,800))` 压成 516×800，说明原宽 ≥ 800）；Assessments +2；516/800 = 0.645 不在 1.2–1.8 → 0；`FILENAME_RE` 不命中 → 合计 8，与存储一致。

**[images-pipeline-11] 缺失信号——确认。**（事实，高；影响为推断，中）
`select.py:72` 的拒绝 haystack 含 `description`/`object_name`，`:83` 的打分 haystack 只有 `title + tags`；`openverse.py:114-119` 的 `extra` 没有 `category`，而 `backend/tests/fixtures/openverse_search.json` 含 `"category"` 字段；裁切算式复算：盒高 0.625W，图高 800/516·W = 1.55W，可见 0.625/1.55 = 0.403 ≈ 40%。

**[images-pipeline-12] 下载与归一化——确认。**（事实，高）
`fetch.py:38` `Image.MAX_IMAGE_PIXELS = 40_000_000`、`:40-43`（`JPEG_QUALITY = 82`、`ALLOWED_FORMATS = ("JPEG", "PNG", "WEBP")`）、`:124-156` `validate_url`（https、无凭据、非 IP 字面量、端口 443）、`:194-237` `safe_download`（≤ 3 跳、`image/*`、字节上限、魔数）、`:241-268` `normalise_image`（`exif_transpose`、白底合成、`:264-265` `thumbnail((max_edge, max_edge), LANCZOS)`、`:267` 渐进式 JPEG q82）；`config.py:525-526`；`sanitize_svg.py:23` `MAX_BYTES = 60_000`。

**[images-pipeline-13] 存储与 CHECK 约束——确认。**（事实，高）
`store.py:41-65` `write_bytes`（`ext not in ("jpg", "svg")` 拒绝、`mkstemp` + `os.replace`、0600、同 sha 复用）、`:76-120` `activate`（先 `superseded` 再插 `active`）；`0001_init.sql:248`（provider CHECK 五值）、`:265`（mime 两值）、`:267`（status 三值）、`:272` 部分唯一索引；`schemas.py:46` `ImageProviderName`、`frontend/src/api/types.ts:84`、`service.py:241-242` 的 provider 列表。

**[images-pipeline-14] alt_zh 来源与不显示——确认。**（事实，高）
`handler.py:131-133`（`[:200]`）、`content.py:62` `ALT_MAX = 60`、`store.py:166`、`service.py:39`/`:78`；`WordImage.tsx:46` `const altText = alt?.trim() || image.alt_zh || '';`，`:57` `alt={altText}`，`figcaption`（`:67-76`）只放 caption；`StudyCard.tsx:306` `alt={content?.image_alt_zh ?? null}`。

**[images-pipeline-15] 显示尺寸、裁切、只在背面、按钮只在详情页——确认。**（事实，高；DPR 换算为算式，高）
`study.css:435-442`（`aspect-ratio: 16 / 10`）、`:456-463`（`object-fit: cover`）、`:465-467`（`--flat` → `contain`）；`tokens.css:54` `--content-max: 720px`；`StudyCard.tsx:171`/`:206` 正面无 `WordImage`，`:297-308` 背面渲染；`StudyPage.tsx:635,695` 只传 `showImage`；`grep -rn "onImageRefresh\|onImageFlag" frontend/src` 除 `StudyCard.tsx` 外无结果；`WordDetailPage.tsx:198` `refreshWordImage`、`:209` `reportWord(... reason: 'irrelevant_image')`。1440/800 = 1.8、1170/800 = 1.46 复算一致。

**[images-pipeline-16] 署名字段与题注——确认。**（事实，高）
`store.py:68-73` `attribution_line`、`:125`/`:139`（Openverse 用 `extra["attribution"]`）；`service.py:57-69`；`WordImage.tsx:26-33` `imageCaption`、`:69-75`；`zh.ts:54`；fixture 中确有「…Carriagehouse2011 is licensed under CC BY 2.0. To view a copy of this license, visit https://creativecommons.org/licenses/by/2.0/.」。

**[images-pipeline-17] 媒体路由与模板卡——确认。**（事实，高）
`media.py:26` `IMAGE_PATH_RE`、`:27` `SVG_CSP`、`:28-29` 缓存头、`:38-48`、`:51-57`；`card_svg.py:20` `WIDTH, HEIGHT = 800, 500`、`:21` `LRU_SIZE = 2000`。

**[images-pipeline-18] SVG 提示词与用户提示拼装——确认。**（事实，高）
`svg_system.txt:1` 全文与引文一致（含「3–5 harmonious colours, large shapes; the English word in a <text> at the bottom (font-size 40 …)」「do not draw people's faces in detail」「at most 8000 characters」）；`svg.py:32-33` `CONCEPT_MAX = 60`、`MEANING_MAX = 60`，`:40-52` `build_user_prompt`/`prompt_for`；`svg_v1.json` `required: ["svg","alt_zh"]`。

**[images-pipeline-19] SVG 触发规则——确认。**（事实，高）
`handler.py:102-103` `_svg_allowed`、`:201-205`（`has_active` → 保留原图并置 `ready`）；`service.py:223-234` `word_is_studied`；`svg.py:102-107`、`:126-130` 两次 `photo_active` 检查；`handler.py:139-146` `svg:<id>:req`；`test_images.py:247` `test_refresh_with_an_active_photo_never_falls_back_to_svg`。

**[images-pipeline-20] SVG 成本——确认（数字全部重算一致）。**（事实，高；外推为推断，中）
`SELECT COUNT(*), ROUND(SUM(cost_usd),4), ROUND(SUM(cost_usd)/COUNT(*),5), ROUND(AVG(output_tokens)), ROUND(AVG(duration_ms)), GROUP_CONCAT(DISTINCT model_used) FROM ai_calls WHERE kind='svg'` → `34|0.4207|0.01237|829|7931|claude-sonnet-5-5`（`provider` 全为 `claude`，单次 0.00937–0.01687）。`config.py:120` `ai_timeout_svg_sec: int = 120`、`:124` `ai_budget_svg: float = 0.10`、`:129` `ai_svg_daily_budget_usd: float = 0.50`、`:61` `FALLBACK_TASK_KINDS = ("content", "lookup", "consolidate")`；`docs/CLAUDE_INTEGRATION.md:407`（「an SVG card $0.028」）、`:416`；`budget.py:272-276`。0.50/0.01237 = 40.4；9,162 × 0.01237 = $113.3；9,162 × 0.028 = $256.5；9,162/40 = 229 天。

**[images-pipeline-21] SVG 质量门与 4 次拒绝——确认。**（事实，高）
`sanitize_svg.py:23-25`、`:65-79` `_parse`（`DET.fromstring(... forbid_dtd=True, forbid_entities=True, forbid_external=True)` → `SvgRejected(f"not well-formed XML: {e}")`）、`:169-181` `clean`；`svg.py:134-142`。live `jobs`：45 election（column 226）、88 employee（224）、97 property（402）、136 have（410）；4/34 = 11.76%；这 4 次合计 `cost_usd` $0.0491（均 $0.0123）。

**[images-pipeline-22] 换一张——确认。**（事实，高）
`routers/words.py:31` `FETCH_IMAGE_PRIORITY_USER = 10`、`:285-301`；`backend/wd/services/bank.py:64` `IMAGE_REFRESH_DAILY_CAP = 20`；`service.py:83-94` `exclude_for`、`:117-136` `_fold_into_live`、`:139-152` `_enqueue_followup`（`image:<id>:r<n>`）、`:155-183`、`:205-211`。

**[images-pipeline-23] 举报即全局替换、exclude 并入、used_refs 只扣分——确认。**（事实，高）
`words.py:259-281`（`:278-280` `if body.target == "image" and word.get("active_image_id") is not None: images.reject_active_image(...)`）；`service.py:186-202`（`system_events('image_rejected')`）；`handler.py:153`、`:94-99`；`select.py:98-100` `points -= 2`；`WordDetailPage.tsx:209`；`admin_reports.py:88`；`AdminPage.tsx:999-1001`（`refetch_image: true`）。

**[images-pipeline-24] 管理员重抓与无 UI 调用——确认。**（事实，高）
`admin_ops.py:33` `REFETCH_PRIORITY = 10`、`:413-427`；`schemas.py:1349-1351`；`service.py:214-220`；`handler.py:139-146`、`:349-356`（CLI 参数 `--provider`、`--query`、`--priority`、`--no-svg`）；`grep -rn adminRefetchImage frontend/src` 只命中 `frontend/src/api/endpoints.ts:539`。

**[images-pipeline-25] 只有两类入队点、无自动重试——确认，附一点补充。**（事实，高）
`content.py:253-261` `enqueue_image`、`:347` 调用点；`grep -rn "enqueue_fetch\|\"fetch_image\"" backend/wd` 仅 `content.py:259`、`images/service.py:148,152,179`、`jobs/queue.py:34`、`jobs/registry.py:35`、`schemas.py:1258`；`jobs/scheduler.py:244-295` 的 `prefetch` 只入队 `generate_content`。补充：`content.py:347` 在**每次**内容落地（含 `force` 重生成、管理员「重新生成」）都会调用 `enqueue_image`，条件只是 `image_state != 'ready'`——所以 `failed` 的词在内容被重生成时会再抓一次图；这不是「被学习触发」，作者结论仍成立。

**[images-pipeline-26] 线上库统计——确认。**（事实，高）
重跑作者 SQL 得到完全相同结果：`claude_svg|active|30||800x500|800x500|1407`、`wikimedia|active|1|8.0|516x800|516x800|95117`；`image_state`：failed 18 / none 9113 / ready 31；active 内容 49 = 31 + 18。

**[images-pipeline-27] 零举报零换图——确认。**（事实，高）
`content_reports` 0 行；`system_events`：`claude_auth 14`、`claude_unavailable 2`、`seed_imported 1`；`user_settings` → `2|2`。

**[images-pipeline-28] 照片命中率 0、election 来自 CLI、15 个预取词的成因——确认。**（事实 + 推断，高）
`SELECT priority, COUNT(*), SUM(result_json LIKE '%svg_job_id%') FROM jobs WHERE type='fetch_image' GROUP BY 1` → `20|19|19`、`30|30|15`；`json_extract(result_json,'$.status')` 49 个全为 `failed`；`generate_svg` 34 = 30 `image_id` + 4 `rejected`。priority 30 的来源确认：`backend/wd/jobs/scheduler.py:55` `PREFETCH_PRIORITY = 30`，`:365` 「03:30 WD_TZ once per day」。CLI 归因确认：`fetch_for_word` 的调用点只有 `handler.py:226`（任务）与 `:276`（CLI）；election 任务 30 失败于 07:53:08Z、SVG 45 被拒于 07:53:15Z，而照片 `created_at = 2026-11-02T08:13:44Z` = `provider_state.wikimedia.last_ok_at`，07:55–08:30 之间没有任何 jobs 行。15 个无 SVG 的词：任务 118–132 创建于 `2026-11-03T19:31Z`（= 11-04 03:31 Asia/Shanghai），`user_words.state` 为 known/learning，首个批次 `local_date` 为 2026-11-04（抓图之后才建），与「抓图时不在开放批次」一致；现均在 2026-11-05 的未完成批次中。

**[images-pipeline-29] provider 健康与「绝大多数任务根本没拿到候选（网络）」——事实确认，归因修正为「对 18/49 个任务未证实」。**（事实，高；归因，中）
`provider_state`、`provider_usage` 与作者一致（wikimedia 日计数 11-02 34、11-03 2、11-05 1；openverse 1/2/1）。**支持**作者的部分：11-03 的 30 个任务只产生 2 + 2 次请求——冷却中的 provider 在 `handler.py:160-163` 被跳过且不计数——所以至少 26 个任务连一次 provider 调用都没有；11-05 的 1 个任务两家各失败一次后进入冷却。**不支持**的部分：11-02 的 18 个任务在 07:48–07:53 五分钟内产生了最多 33 次 Wikimedia 请求（34 − CLI 至少 1 次）≈ 1.8 次/任务。若 Wikimedia 返回过 429/5xx 或网络错误，`quota.cooldown`（`handler.py:168-169`，默认 15 分钟，或 ops.md 记录的 `retry-after: 52`）会让后续任务全部跳过，不可能出现 33 次；因此 11-02 Wikimedia 是**在应答**的——要么 HTTP 200 但没有可接受/可下载的候选（选图或下载环节失败），要么是不触发冷却的 4xx/非 JSON 响应（`handler.py:171-173` `mark_error`）。两者都与 20 分钟后 CLI 成功兼容，仅凭 DB 无法区分。正确说法：「49 个任务中 ≥ 27 个没有发出任何 provider 请求（冷却跳过）；11-02 的 18 个任务 Wikimedia 有应答，失败原因未知，需看 journal 中 `event` 为 `provider_cooldown`/`provider_error`/`provider_skipped` 的日志（`handler.py:162,170,173,178`；`docs/ops.md:17-23`）」。由此，「打分/黑名单规则在线上几乎没被检验过」仍是合理推断但未被证明。

**[images-pipeline-31] 抓手 2 的前提「Commons 会把 SVG 光栅化为 PNG 缩略图，filetype:drawing 可能几乎零改动即可用」——前半确认、后半推翻性修正（已实测）。**（事实，高）
Commons API 实测（访问 2026-11-05）：`generator=search&gsrsearch=apple filetype:drawing&gsrnamespace=6&gsrlimit=3&prop=imageinfo&iiprop=url|mime|thumbmime|mediatype&iiurlwidth=800` 返回 `File:Apple-icon.svg`、`File:Apple fruit icon.svg`、`File:Apple structure.svg`，每个都是 `mediatype DRAWING`、`mime image/svg+xml`、`thumbmime image/png`、`thumburl` 以 `.png` 结尾。而现有代码 `wikimedia.py:97` `mime = info.get("mime") or …` 取的是原文件 MIME `image/svg+xml`，`select.py:65-66` 会以 `"mime"` 拒绝——**不是零改动**；最小改动是 `iiprop` 加 `thumbmime` 并用它作为候选 `mime`（API:Imageinfo，https://www.mediawiki.org/wiki/API:Imageinfo ，访问 2026-11-05：「thumbmime: Adds MIME type of the image thumbnail (requires url and param iiurlwidth).」）。作者「未解决的问题 2」据此关闭。

**[images-pipeline-36] 「每次失败白花 ≈ $0.012」——确认。**（事实，高）
4 个 `rejected` 任务 `result_json.cost_usd` 合计 $0.0491，均 $0.0123。

**[images-pipeline-37] 生成式图片模型——国内两家确认；OpenAI 子句修正；模型清单有遗漏。**（事实，高/中）
确认：CogView-3-Flash 页（https://docs.bigmodel.cn/cn/guide/models/free/cogview-3-flash ，访问 2026-11-05）「CogView-3-Flash 是智谱推出的免费图像生成模型」，尺寸七档与作者一致，限流指向需登录的 rate-limits 页；CogView-4 页「0.06 元 / 次」，并发 V0 5 / V1 10 / V2 15 / V3 20；图像生成 API 参考：`POST /paas/v4/images/generations`、`data[].url`、「图片的临时链接有效期为 30 天，请及时转存图片」、`content_filter`（level 0–3）。百炼 `wan2.2-t2i-flash` 页（https://help.aliyun.com/zh/model-studio/wan2-2-t2i-flash ）「图片生成 0.14 每张」「RPM 120」；文生图 V2 参考：`POST …/api/v1/services/aigc/text2image/image-synthesis` + `X-DashScope-Async: enable`、`GET …/api/v1/tasks/{task_id}`、「链接有效期为 24 小时」、prompt ≤ 500 字、边长 512–1440、`n` 1–4。算式复核：9,162 × 0.06 = ¥549.72；× 0.14 = ¥1,282.68。代码事实确认：`base.py:184-200` 对 `generated` 返回 `LICENSE_OTHER`；`0001_init.sql:511` `kind IN ('content','lookup','consolidate','svg','probe')`；`grep -rn "images/generations" backend/wd` 无结果。**修正 1**：OpenAI 官方弃用页（https://developers.openai.com/api/docs/deprecations ，访问 2026-11-05）**没有** `gpt-image-1` 的退役条目；列出的是 `dall-e-2`/`dall-e-3` → 2026-05-12 停用，以及 `gpt-image-1-mini`、`gpt-image-1.5`、`chatgpt-image-latest` → 2026-12-01 停用（替代 `gpt-image-2.5-sunburst/-flare`）。第三方「2026-10-23 退役」说法与一手来源不符，应删除或改写。**修正 2**：同一智谱接口接受的模型为 `glm-image`、`cogview-4-250304`、`cogview-4`、`cogview-3-flash`；作者漏了 `glm-image`（见遗漏 O4）。

**[images-pipeline-42] 许可白名单与署名义务——确认。**（事实，高）
`base.py:184-205`（`nc`/`nd` → other；cc0/public domain/pd/pdm/cc zero → cc0；pixabay/pexels → permissive；by-sa；by）；`ATTRIBUTION.md:36` 「CC BY-SA images additionally remain under CC BY-SA」；Commons 复用页（访问 2026-11-05）「may not have a strict legal requirement of attribution (depending on the jurisdiction of content reuse), but attribution is recommended to give correct provenance.」

**[images-pipeline-43] Pixabay/Pexels 条款——Pixabay 确认；Pexels 许可原文无法核验（一手页面 403）。**（事实/中）
Pixabay 许可摘要（https://pixabay.com/service/license-summary/ ，访问 2026-11-05）：「Use Content without having to attribute the author (although giving credit is always appreciated by our community!)」「Modify or adapt Content into new works」「You cannot sell or distribute Content (either in digital or physical form) on a Standalone basis」「You cannot use Content in any immoral or illegal way, especially Content which features recognisable people」。Pexels：`https://www.pexels.com/license/`、`/terms-of-service/`、`help.pexels.com/hc/en-us/articles/360042295174` 与 `360042332714` 对 WebFetch 均 HTTP 403；能核的一手只有 API 文档「Whenever you are doing an API request make sure to show a prominent link to Pexels.」「Always credit our photographers when possible (e.g. 'Photo by John Doe on Pexels').」；二手（WebSearch 摘要、python-pexels guidelines）与作者转述一致（免费商用、无需署名、可识别真人不得负面呈现）。

**[images-pipeline-46] Wikimedia 日限额为自设、官方无硬日配额、未传 maxlag、天数算式——确认。**（事实 + 算式，高）
`config.py:162`、`:528` `integer("WD_WIKIMEDIA_DAILY_LIMIT", 2000, 0, 1_000_000)`；`quota.py:39-40`；API:Etiquette「If your task is not interactive, i.e. a user is not waiting for the result, you should use the maxlag parameter.」；9,162/2000 = 4.6 天、27,486/2000 = 13.7 天。

**[images-pipeline-47] 预热不走 Openverse/不画 SVG、IoWorker 单线程——确认。**（事实，高）
`handler.py:158-159`、`:102-103`；`backend/wd/jobs/worker.py:11` 「IoWorker (io-1) drains fetch_image / send_email / send_webhook one job at a time」，`:359-362`。

**[第二部分导语] 学习科学引文——确认。**（事实，高；用于推断的置信度仍为中/低）
Wikipedia `Picture_superiority_effect`（访问 2026-11-05）四句引文逐句在页；EurekAlert 473021（访问 2026-11-05）：Zoe Flack 与 Jessica Horst，Infant and Child Development，2017，三岁儿童，发布 30-Jun-2017，「children who were read stories with only one illustration at a time learned twice as many words as children who were read stories with two or more illustrations」。

---

## 二、作者遗漏的重要事实

**O1. Openverse 的真实匿名限额可直接从响应头读到，且它决定 Openverse 不能当批量来源。**（事实，高）
一次匿名请求（2026-11-05 14:18 UTC）返回 `x-ratelimit-limit-anon_burst: 20/min`、`x-ratelimit-limit-anon_sustained: 200/day`、`page_count: 240`。按项目自限 160/日：9,162 词各搜 1 次需 9,162/160 = 57.3 天，各搜 3 次需 172 天；注册应用 10,000/日（`rest_framework.py:35`）才能把全库压到 1–3 天。影响：抓手 2/4 若以 Openverse 为「插画优先」来源，必须先注册 `WD_OPENVERSE_CLIENT_ID/SECRET`。

**O2. Openverse 每次请求拿 20 条却只用 10 条。**（事实，高）
`openverse.py:28` `PAGE_SIZE = 20`，`:72` `return parse_search(data)[: max(1, int(limit))]`，而 `handler.py:35` `SEARCH_LIMIT = 10`——每个匿名配额单位有一半结果被丢弃。给 Openverse 单独的 limit（或把 `PAGE_SIZE` 降到 10）是零成本改动。

**O3. Pixabay API 文档明文禁止系统性批量下载；Pexels 的月配额使其只能分月跑。**（事实，高；算式，高）
https://pixabay.com/api/docs/ （访问 2026-11-05）：「Systematic mass downloads are not allowed.」——用 Pixabay 为 9,162 词预抓配图与条款冲突，只适合按需（用户正在学的词）抓取。Pexels（https://www.pexels.com/api/documentation/ ）：「Do not abuse the API.」「You may not copy or replicate core functionality of Pexels.」，20,000 次/月、200 次/小时：全库 1 关键词 9,162 次（占月配额 46%，≥ 46 小时），3 关键词 27,486 次 ≈ 1.4 个月。作者的 [46] 只算了 Wikimedia 的天数。

**O4. 智谱同一接口还有 `glm-image`（0.1 元/次），OpenAI 官方弃用表与作者引用的第三方说法不符。**（事实，高/中）
https://docs.bigmodel.cn/cn/guide/models/image-generation/glm-image （访问 2026-11-05）：模型 `glm-image`，「0.1 元 / 次」，推荐尺寸 1280×1280、1568×1056、1728×960 等，自定义 512–2048 px 且为 32 的倍数；全库 9,162 × 0.1 = ¥916.20（介于 CogView-4 ¥549.72 与万相 ¥1,282.68 之间）。OpenAI 一手弃用页见 [37] 修正——`gpt-image-1` 未退役；若要比较境外价格应以 `gpt-image-2`/`gpt-image-2.5-*` 为准（本次未核价格）。

**O5. 作者「未解决的问题 1、2」都能用 Commons API 直接回答（且 2 的答案改变抓手 2 的代价）。**（事实，高）
(a) `generator=search&gsrsearch=haswbstatement:P180=Q89 filetype:bitmap&gsrnamespace=6&gsrlimit=3`（访问 2026-11-05）正常返回 3 个 `BITMAP` 文件（`File:Red Apple.jpg`、`File:Tree with red apples in Barkedal 4.jpg`、`File:Santa Maria de Huerta Almacen.jpg`），无 warning——结构化数据 depicts 检索在 `generator=search` 下可用；Commons:Depicts（https://commons.wikimedia.org/wiki/Commons:Depicts ）也写明「Depicts statements can be searched using the keyword haswbstatement. For example … haswbstatement:P180=Q146.」。注意第一条命中是修道院仓库照片，说明 depicts 检索返回「含有」而非「典型」的图，相关性打分仍不可省。(b) SVG 的 `thumbmime` 为 `image/png`、`mime` 为 `image/svg+xml`（见 [31]）：抓手 2 需要改 `wikimedia.py:48` 的 `iiprop` 与 `:97` 的 `mime` 取值，不是零改动。

**O6. 现有 SVG 与模板卡都把英文单词画/印在图上，不能直接当「正面回忆提示」用。**（事实，高）
`svg_system.txt:1` 要求「the English word in a <text> at the bottom (font-size 40 …)」；模板卡 `card_svg.py` 渲染词头、音标、释义、例句（`:82-121`）。抓手 11(a)「正面显示图作为图→词检索练习」对现有 30 张 SVG 和所有模板卡都会直接泄露答案，必须先改提示词并重画（旧卡不会自动重画，见作者 [36]）。

**O7. `wd images-prune` 会删掉「没人在学」的词的配图，与「全库预生成」方向相抵。**（事实，高）
`handler.py:298-331` `prune_unused`：删除 `created_at < cutoff` 且不在任何 `new/learning` 生词库、不在近 `cutoff_date` 批次的词的全部 `word_images` 行并重置 `image_state='none'`，再删孤儿文件；`docs/ops.md:202` 与 `docs/DEPLOY.md:437` 把 `wd images-prune --unused-days 365` 列为磁盘不足的标准处置。若决定预生成 9,162 张图，这条运维建议需要同步改掉，否则一年后会被清空。

**O8. 抽象词/功能词的内容关键词质量问题已有线上实例，比作者的 `have` 例子更极端。**（事实，高）
live-copy `word_contents`：`particularly` 的 `image_keywords` = `["one red apple"]`，`region` = `["mountain valley landscape"]`（两条都只剩 1 个关键词）。这直接支持抓手 1(c)/(d)：对副词、介词等词性，`content_system.txt:9` 的「For abstract words choose a concrete scene」会产出与词义无关的可拍场景，搜到的照片不会帮助记忆。

**O9. 「永久 failed」的系统性成因是「一次冷却 → 整批跳过 → 失败不重试」的组合，不只是「抓图时还没被学」。**（事实 + 推断，高）
11-03 的 30 个任务只发出 2 + 2 次 provider 请求（`provider_usage`），其余任务在 `handler.py:160-163` 因 `quota.check` 返回 `cooldown` 而跳过，然后在 `:205` 被置为 `failed`，而 [25] 证明没有重试。抓手 10 若只在「词被学习」时重抓，仍会漏掉这种「provider 当时在冷却」的情形；更稳的触发是「`image_state='failed'` 且上次抓图时任一 provider 处于冷却」或简单的「冷却结束后重跑当日 failed 词」。

**O10.（次要）更高分辨率不必新增 provider。**（事实，高）
Pexels 文档有 `large2x`（DPR 2 的 940×650）与 `landscape`（1200×627）变体，Pixabay `largeImageURL` 为 1280 px；仅 Commons 受 `THUMB_WIDTH = 800`（`wikimedia.py:27`）硬编码限制。抓手 11(c) 的「把 `WD_IMAGE_MAX_EDGE` 提到 1200–1600」对 Pexels 还需把 `pexels.py:46` 的 `src.large` 换成 `large2x`。

---

## 三、联网来源专项核查（一手 / 年份 / 口径）

- **一手性**：mediawiki.org、commons.wikimedia.org、pixabay.com、pexels.com API 文档、docs.bigmodel.cn、help.aliyun.com、developers.openai.com、Openverse 源码与 OpenAPI 文本均为一手。Pexels 许可条款（/license/、/terms-of-service/、help 中心）对抓取器 403，作者与本核验都只能用二手转述——该条应保持「中」置信度。OpenAI `gpt-image-1` 价格/退役引自第三方 pricepertoken.com，且与一手弃用页不符（见 [37]）。Atkinson & Raugh 1975 仅来自搜索摘要，作者已标「低」，本次未另核。
- **年份/是否被取代**：智谱页面不显示更新日期，但同一接口已接受更新的 `glm-image`（2026-01 发布，见 O4）；百炼 `wan2.2-t2i-flash` 页把 `wan2.5-t2i-preview` 列为相邻模型，作者的报价对 wan2.2 仍有效；Openverse 源码取自 main 分支（2026-11-05 下载），生产头部与 DESIGN §9（2026-10 的测量）一致，说明限额近月未变；OpenAI 弃用页显示 `gpt-image-1-mini`/`1.5` 将于 2026-12-01 停用——若后续比较境外生成价格，应以 `gpt-image-2.5-*` 为准。
- **数字口径**：作者文中的 9,162 是 `words` 表行数（词条，含短语/缩写：`words.kind` 有 word/phrase/abbreviation/proper_noun，`0001_init.sql:170`），用它乘单价得到的「全库成本」是词条口径而非「单词」口径；Pixabay/Pexels 的限额口径是「API 请求数」而非「图片数」，与 [46] 的「每词 1–3 次搜索」一致；Openverse 的 `page_size=20` 与项目 `SEARCH_LIMIT=10` 口径不同（见 O2）；`ai_calls.cost_usd` 的 $0.01237 是「每次调用」而非「每张成功 SVG」——按 30 张成功算是 0.4207/30 = $0.01402/张。

---

## 四、未解决的问题

1. 2026-11-02 的 18 个 `fetch_image` 任务为何在 Wikimedia 有应答（≤ 33 次请求、无冷却）的情况下全部失败——是 HTTP 200 但候选被拒/下载失败，还是 4xx/非 JSON 响应？需要线上 journal 中 `provider_error`/`provider_cooldown`/`provider_skipped` 事件（本任务禁止触碰 `/Users/sqin/word-dance-data`）。这决定「打分/黑名单规则是否被检验过」。
2. Pexels 许可原文（一手）仍未能读取；若决定接入 Pexels，需在浏览器中人工核对 https://www.pexels.com/license/ 。
3. 生成式模型对学校词表的内容过滤拒绝率（`weapon`、`sexual`、`blood` 等）仍无数据；智谱 `content_filter` 分级可记录，百炼未核。
4. `haswbstatement:P180=…` 检索到的是「含有该物体」的图而非「典型示意图」（Q89 的首条命中是仓库照片）；需要在样本词上比较 `depicts` 检索与关键词检索的人工评分。
5. 本次为取 Openverse 头部消耗了该出口 IP 当日匿名配额 1/200；若线上实例与本机同出口，当日剩余 199。
6. 「照片 vs 扁平插画」对小学生词汇保持的直接实验证据——与作者一样未找到。

---

**汇总：核验 38 条：确认 32、修正 5（[4]、[9]、[29]、[31]、[37]）、推翻 0、无法核验 1（[43] 的 Pexels 许可部分）。**
