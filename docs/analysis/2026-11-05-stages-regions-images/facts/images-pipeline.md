# 配图流水线：完整事实与「让图更有助于记忆」的抓手（slug: images-pipeline）

基线：仓库 `/Users/sqin/word-dance` @ `75df534`（main），核对日期 2026-11-05。`git log 9ab13a5..75df534 -- backend/wd/images backend/wd/ai/svg.py backend/wd/ai/prompts/svg_system.txt frontend/src/components/study/WordImage.tsx docs/DESIGN.md` 为空：配图相关代码自上一次分析（基线 9ab13a5）以来**没有任何提交**，但下文所有行号都按 75df534 重新核对。

## 范围与方法

- 通读的代码：`backend/wd/images/{__init__,fetch,select,service,store,handler,quota,card_svg,sanitize_svg}.py`、`backend/wd/images/providers/{__init__,base,wikimedia,openverse,pixabay,pexels}.py`、`backend/wd/ai/svg.py`、`backend/wd/ai/prompts/svg_system.txt`、`backend/wd/ai/schemas/svg_v1.json`、`backend/wd/ai/prompts/content_system.txt`、`backend/wd/ai/schemas/content_v1.json`、`backend/wd/ai/content.py`（关键词清洗、`enqueue_image`）、`backend/wd/ai/budget.py`（SVG 子额度）、`backend/wd/config.py`（图片设置）、`backend/wd/interfaces.py`（`Candidate`）、`backend/wd/routers/{words,media,admin_ops,admin_reports}.py`、`backend/wd/schemas.py`、`backend/wd/main.py`（CSP）、`backend/wd/migrations/0001_init.sql`（`word_images` 约束）、`frontend/src/components/study/{WordImage,StudyCard}.tsx`、`frontend/src/components/study/study.css`、`frontend/src/styles/tokens.css`、`frontend/src/pages/{WordDetailPage,StudyPage,AdminPage}.tsx`、`frontend/src/api/{types,endpoints}.ts`、`frontend/src/i18n/zh.ts`。
- 读过的文档：`docs/DESIGN.md` §9（523–553 行）、`docs/CLAUDE_INTEGRATION.md`（§5.5/§6.7/§7 的 SVG 部分）、`docs/API.md`（25/28/29/52/53/69）、`docs/FRONTEND.md`（WordImage 行）、`docs/DEPLOY.md`（图片变量）、`docs/ops.md`（267–278 行）、`ATTRIBUTION.md` §3、`deploy/env.example`；旧分析 `docs/analysis/2026-11-04-library-curation/facts/content-media.txt`（结论 18–25、36 已复核）和 `docs/analysis/2026-11-04-quick-deploy-mobile/facts/capacitor.md`（cookie 门禁的 /media 与 CSP）。
- 测试：`backend/tests/unit/test_select.py`（打分表 92–119 行）、`backend/tests/integration/test_images.py`（34 个用例，117–659 行；关键词用例 535–547 行）、`backend/tests/unit/{test_providers,test_quota,test_fetch_ssrf,test_sanitize_svg,test_card_svg}.py`、`backend/tests/integration/test_media.py`；fixtures `wikimedia_search.json`、`openverse_search.json`。
- 线上只读副本 `/private/tmp/claude-501/-Users-sqin-word-dance/0be1d882-e939-4b1e-8c2e-b69435664161/scratchpad/live-copy.db`，用 `sqlite3` 只查不改（`word_images`、`words.image_state`、`jobs`、`ai_calls`、`content_reports`、`system_events`、`provider_state`、`provider_usage`、`user_settings`、`word_contents`）。
- 网页（均访问 2026-11-05）：mediawiki.org `Help:CirrusSearch`、`API:Etiquette`、`Help:Extension:WikibaseCirrusSearch`；commons.wikimedia.org `Commons:MediaSearch`、`Commons:Reusing_content_outside_Wikimedia`；pixabay.com `/api/docs/`、`/service/license-summary/`；pexels.com `/api/documentation/`（`/license/` 与 help.pexels.com 返回 403，许可条款只能引用 API 文档与搜索摘要）；help.aliyun.com 万相 `wan2-2-t2i-flash` 与文生图 V2 API 参考；docs.bigmodel.cn `cogview-3-flash` 免费模型页、`cogview-4` 页、图像生成 API 参考（`/pricing` 页未渲染）；en.wikipedia.org `Picture_superiority_effect`；eurekalert.org 473021（Flack & Horst 2017）。WebSearch 关键词：「智谱 CogView-4 CogView-3-Flash 图片生成 API 价格 免费」「阿里云百炼 通义万相 wan2.2-t2i 文生图 API 价格 每张」「vocabulary learning pictures … dual coding picture superiority」「OpenAI gpt-image-1 API pricing per image 2026」「Flack Horst Sticking to the story …」「keyword method vocabulary … Atkinson Raugh」「CogView-3-Flash 免费（限 bigmodel.cn）」「Pexels license attribution（限 pexels.com）」。
- 下载（全部视为不可信数据，放在 `…/scratchpad/images-pipeline/dl-openverse/`，只用 `grep`/`sed` 读，不执行）：Openverse 源码 `api/api/serializers/{media_serializers,image_serializers}.py`、`api/api/constants/{field_values,media_types,restricted_features}.py`、`api/conf/settings/rest_framework.py`、`api/api/utils/throttle.py`、`documentation/api/guides/quickstart.md`（raw.githubusercontent.com，WordPress/openverse main）与 `https://api.openverse.org/v1/schema/` 的 OpenAPI 文本（`openverse_schema.yaml`，经本机代理）。

置信度标注：高/中/低；每条标注「事实」或「推断」。

---

## 一、现状事实

### A. 搜索词怎么构造（任务 a）

**[images-pipeline-1]** 搜索词只来自三处，按优先级：管理员 `query` 覆盖 → 当前 active 内容的 `image_keywords`（最多取 3 个）→ 词条 `lemma`。不用译文、不用例句、不做词义消歧。（事实，高）
- `backend/wd/images/handler.py:134-137`：`if query and query.strip(): keywords = clean_keywords([query], lemma) else: keywords = clean_keywords((content or {}).get("image_keywords") or [], lemma)`；`handler.py:37` `MAX_KEYWORDS = 3`；`handler.py:78` `return out or [lemma]`。
- 内容侧的 `image_keywords` 由 Claude 内容生成写入，提示词要求「2–4 short, concrete, photographable English search phrases … that evoke the word's main sense. For abstract words choose a concrete scene ("negotiate" → "handshake across table"). Most literal first.」（`backend/wd/ai/prompts/content_system.txt:9`）；`image_alt_zh` 是「one Chinese sentence (at most 30 characters) describing the ideal picture and how it links to the meaning」（同文件 :10）。
- 所以「消歧」只发生在内容生成那一步（模型挑一个主义项写具体场景）；一旦没有内容（`content_state` 非 ready），就直接搜裸 lemma。线上例子：`have` 的关键词是 `["holding keys in hand","person holding book","family having dinner"]`（live-copy `word_contents`），而无内容时只会搜 `have filetype:bitmap`。

**[images-pipeline-2]** 关键词形状规则：`^[A-Za-z][A-Za-z ,'-]{1,40}$`（2–41 个字符、只允许英文字母/空格/逗号/撇号/连字符），再过黑名单，再小写去重；内容层保留最多 4 个，但抓图只用前 3 个——第 4 个关键词永远不会被搜索。（事实，高）
- `handler.py:38` `KEYWORD_RE = re.compile(r"^[A-Za-z][A-Za-z ,'-]{1,40}$")`，`handler.py:64-78` `clean_keywords`；`backend/wd/ai/content.py:60` `KEYWORDS_MAX = 4`、`:174-183` 同样的形状/黑名单过滤。
- 推论（高）：`POST /api/admin/words/{id}/refetch-image` 的 `query` 在 schema 里允许 100 字符（`backend/wd/schemas.py:1351` `query: str | None = Field(default=None, max_length=100)`），但进入 handler 后仍走 `clean_keywords([query], lemma)`，含中文、数字或超过 41 字符的 query 会被**静默**丢弃并退回 lemma，API 不报错。

**[images-pipeline-3]** 每个关键词按 provider 链顺序各搜一次（`limit=10`），每次搜索最多尝试下载排名前 3 的候选，第一个下载成功的立即激活并结束——即「第一个可用」而非「全局最优」；一个词最坏情况 3 关键词 × 4 provider = 12 次搜索。（事实，高）
- `handler.py:35-36` `SEARCH_LIMIT = 10`、`CANDIDATES_PER_SEARCH = 3`；`handler.py:156-196` 双重 for 循环，`:182` `for best in select.rank(cands, kw, excluded, used_refs=used_refs)[:CANDIDATES_PER_SEARCH]`，`:186-187` 激活后 `return FetchOutcome(STATUS_READY, …)`。

### B. 各 provider 的请求参数与限流（任务 a）

**[images-pipeline-4]** Wikimedia Commons（主 provider）：`action=query&generator=search&gsrsearch=<kw> filetype:bitmap&gsrnamespace=6&gsrlimit=10&prop=imageinfo&iiprop=url|extmetadata|size|mime&iiurlwidth=800&format=json`；只下载 ≤ 800 px 的 `thumburl`；进程级 ≥ 1 s 间隔；自设软上限 2000 次/日；429/503 → 冷却 15 分钟。没有用 `filemime:`、`haswbstatement:`（结构化数据 depicts）、`incategory:`、`fileres:` 等任何其他 CirrusSearch 关键字，`filetype:bitmap` 把 SVG/矢量剪贴画（`filetype:drawing`）全部排除在外。（事实，高）
- `backend/wd/images/providers/wikimedia.py:40-51` `params()`（`"gsrsearch": f"{query} filetype:bitmap"`，`"iiurlwidth": THUMB_WIDTH`），`:27` `THUMB_WIDTH = 800`；`base.py:223-250` `RateGate`；`config.py:161-162` `wikimedia_min_interval_ms: int = 1000`、`wikimedia_daily_limit: int = 2000`；`quota.py:26` `WIKIMEDIA_COOLDOWN_S = 15 * 60`。
- 候选字段：`title`（去 `File:` 与扩展名）、`Artist`（HTML 转文本）、`LicenseShortName|UsageTerms|License`、`Categories` 作为 `tags`、`Assessments`/`Restrictions`/`ImageDescription`/`ObjectName`（`wikimedia.py:90-126`）。
- CirrusSearch 文档（https://www.mediawiki.org/wiki/Help:CirrusSearch ，访问 2026-11-05）：「The following types currently exist: UNKNOWN, BITMAP, DRAWING, AUDIO, VIDEO, MULTIMEDIA, OFFICE, TEXT, EXECUTABLE, ARCHIVE, 3D」，并说明 SVG 归为 drawing；`filemime:{MIMEtype}`、`filew/fileh`、`fileres`、`filebits` 均可用。
- Wikimedia 自身并无「每日限额」：API:Etiquette（https://www.mediawiki.org/wiki/API:Etiquette ，访问 2026-11-05）：「There is no hard speed limit on read requests, but be considerate and try not to take a site down.」「Making your requests in series rather than in parallel … should result in a safe request rate.」且「API requests to Wikimedia wikis must include a meaningful User-Agent header.」（UA 由 `base.py:52-62` 生成：`word-Dance/<ver> (self-hosted vocabulary trainer; +<WD_PUBLIC_URL>; <WD_CONTACT_EMAIL>)`）。

**[images-pipeline-5]** Openverse（次 provider）：`GET https://api.openverse.org/v1/images/?q=<kw>&page_size=20&license_type=commercial&mature=false`；可选 client-credentials bearer；只下载源站 `url`，从不下载 `api.openverse.org` 上的缩略图；本地限额 15/分钟、160/日，429/网络错误 → 冷却 `Retry-After` 或 10 分钟；priority ≥ 90（预热）跳过。没有用 `category`、`aspect_ratio`、`size`、`extension`、`source` 过滤。（事实，高）
- `providers/openverse.py:41-42` `params()`，`:65-72` `search()`，`:89-90` 跳过 API 主机；`config.py:163-164`；`quota.py:27`；`handler.py:158-159`。
- Openverse 实际可用的图片参数（下载源码 `image_serializers.py:38-55`）：`category` ∈ {`digitized_artwork`,`illustration`,`photograph`}，`aspect_ratio` ∈ {`tall`,`wide`,`square`}，`size` ∈ {`small`,`medium`,`large`}（`field_values.py:10-26`）；`media_serializers.py` 另有 `source`/`excluded_source`/`tags`/`title`/`creator`/`license`/`license_type`/`extension`/`mature`/`unstable__include_sensitive_results`（:201-314）。
- 匿名 `page_size` 上限 20、认证 50、特权 240，匿名翻页深度 12×20=240 条（`restricted_features.py:54-73`）。API 描述文本（`openverse_schema.yaml` 3150-3166 行）：「Openverse endpoints are rate limited. Anonymous requests should be sufficient for most users.」「the Terms of Service disallow scraping under all circumstances.」官方描述**不给出匿名数字**；仓库 DESIGN §9 写的「anonymous limits measured 20/min burst, 200/day」是项目自测值（`docs/DESIGN.md:546`）。源码默认值 `THROTTLE_ANON_BURST="5/hour"`、`THROTTLE_ANON_SUSTAINED="100/day"` 是可由环境变量覆盖的开发默认（`rest_framework.py:10-11`），注册应用 client-credentials 为硬编码 `100/min`、`10000/day`（`:35-36`）。（中：生产匿名值未公开）

> **核验修正（INDEX §3 #24，2026-11-05）**：生产匿名限额已实测——一次匿名请求 `GET /v1/images/?q=apple&page_size=1`（2026-11-05 14:18 UTC）的响应头 `x-ratelimit-limit-anon_burst: 20/min`、`x-ratelimit-limit-anon_sustained: 200/day`（`page_count: 240`），即 `docs/DESIGN.md:546` 的 20/min、200/day 就是当前生产匿名限额而不只是项目自测值，项目的 15/分、160/日在其之下，「未解决的问题 3」可关闭；按自限 160/日全库各搜 1 次需 57.3 天，作批量来源必须注册应用（10,000/日），依据 verify/images-pipeline.md [images-pipeline-5]、O1。

**[images-pipeline-6]** Pixabay（需 `WD_PIXABAY_KEY`）：`key, q, image_type=photo, safesearch=true, per_page=max(3,min(limit,200)), min_width=400, lang=en`；下载 `largeImageURL`（1280 px）；本地限额 (60/分钟, 3000/日)。没有用 `orientation`、`category`、`editors_choice`、`colors`、`order`，`image_type` 固定为 photo（因此插画/矢量永远搜不到）。（事实，高）
- `providers/pixabay.py:30-39`、`:54`；`quota.py:33` `PIXABAY_LIMITS = (60, 3000)`。
- 官方文档（https://pixabay.com/api/docs/ ，访问 2026-11-05）：`image_type` 取值 `"all", "photo", "illustration", "vector"`；`orientation` `"all", "horizontal", "vertical"`；`category` 含 `education, animals, food, nature, people, …`；`per_page` 3–200；限流「up to 100 requests per 60 seconds」；「requests must be cached for 24 hours」；「permanent hotlinking of images … is not allowed」（本项目下载后自存，不热链）；返回 `webformatURL` ≤ 640 px、`largeImageURL` ≤ 1280 px。

**[images-pipeline-7]** Pexels（需 `WD_PEXELS_KEY`）：`query, per_page=max(1,min(limit,80)), orientation=landscape`，`Authorization: <key>`；下载 `src.large`（940 px）；本地限额 (20/分钟, 600/日)；候选 `title` 取 `alt`，`tags` 恒为空。没有用 `size`、`color`、`locale`。（事实，高）
- `providers/pexels.py:29-30`、`:46`、`:54`、`:64`；`quota.py:34` `PEXELS_LIMITS = (20, 600)`。
- 官方文档（https://www.pexels.com/api/documentation/ ，访问 2026-11-05）：`orientation` landscape/portrait/square，`size` large(24MP)/medium(12MP)/small(4MP)，`locale` 含 `zh-CN`/`zh-TW`，`per_page` 最大 80；默认限流「200 requests per hour and 20,000 requests per month」；署名指引「Show a prominent link to Pexels」「Always credit our photographers when possible」。

**[images-pipeline-8]** 配额/冷却持久化在 `provider_usage`（分钟/日窗口，UTC）与 `provider_state`；任一 provider 调用失败也计数；状态码 429/500/502/503/504 或网络错误 → 冷却，其他 HTTP 错误只记 `last_error`。（事实，高）
- `quota.py:37-47` `limits_for`、`:75-89` `check`、`:96-110` `record`、`:113-121` `cooldown_seconds`；`handler.py:39` `COOLDOWN_STATUSES = (429, 500, 502, 503, 504)`，`:164-181`。

### C. 候选排序用了什么、缺了什么（任务 b）

**[images-pipeline-9]** 硬拒绝：`mature`、Openverse `unstable__sensitivity` 非空、Commons `Restrictions` 非空、许可不在白名单、MIME 非 jpeg/png/webp、`width<400 or height<300`、宽高比不在 0.6–2.2、标题/标签/分类/描述命中黑名单正则、在 exclude 列表。黑名单：`\b(map|diagram|logo|flag|coat of arms|chart|graph|screenshot|poster|cover|scan|text|document|nude|nudity|sex|porn|gore|blood|weapon|gun|corpse)\b`。（事实，高）
- `backend/wd/images/select.py:20-24`、`:29-37`、`:54-77`。
- 副作用（事实）：黑名单同样过滤 Claude 的 `image_keywords`（`content.py:68-70`、`handler.py:71`），所以词条 `weapon`、`gun`、`blood`、`map`、`text`、`document` 等**连 lemma 都不能作为关键词**——`clean_keywords` 对这些词会退回 `[lemma]`，而 `select.is_blocked` 又会拒掉所有标题含该词的候选，等于这些词永远拿不到照片（线上 `weapon` 的图是 Claude SVG「博物馆展台上交叉陈列的两把古剑」，见 live-copy `word_images.id=24`）。

> **核验修正（INDEX §3 #23，2026-11-05）**：「副作用」段修正——回退值 `[lemma]` 不经过黑名单（`handler.py:71` 只过滤 `kw`，`:78` `return out or [lemma]`；`content.py:176`、`:183-184` 同理），所以 `weapon` 等 lemma 仍会被原样搜索；正则是整词匹配，`Weapons`/`weapons` 不命中；线上 `weapon` 的内容关键词（"medieval swords display"、"museum armor"、"airport security scanner"）没有一个被挡，其 `fetch_image` 任务 77 与其余 48 个一样失败于 "no acceptable photo from any provider"，SVG 不是黑名单造成的；库中 `blood/chart/cover/document/flag/graph/gun/logo/map/poster/scan/sex/text` 均为 `image_state='none'`，尚无实证；规则本身（`select.py:20-24`、`:54-77`）确认，依据 verify/images-pipeline.md [images-pipeline-9]。

**[images-pipeline-10]** 打分只有 7 个信号：关键词 token 命中标题/标签（前缀匹配，每 token +1，封顶 +3）；许可 cc0/pd +3、by +2、Pixabay/Pexels +2、by-sa +1；宽高比 1.2–1.8 +1；宽 ≥ 800 +1；Commons `Assessments` 含 featured/quality/valued +2；文件名式标题（`IMG_`、`DSC`、年份）−1；已被其他词使用 −2；最低分 1，同分保持 provider 顺序。（事实，高）
- `select.py:80-101` `score()`，`:104-128` `rank()`；`backend/tests/unit/test_select.py:92-119` 的打分表逐条验证（例如 `select.score(cand(title="x", … license="CC0", width=600, height=550), "apple") == 3`）。
- 线上唯一一张照片的分数可复算：`election`（live-copy `word_images.id=18`，query `ballot box`，title `Urne Ballot box république`，CC0，原图宽 ≥ 800）：命中 ballot+box = 2，CC0 +3，宽 ≥ 800 +1，`Assessments` +2 → 8，与存储的 `score=8.0` 一致（宽高比 516/800=0.645 不在 1.2–1.8，不加分；但 ≥ 0.6 所以未被硬拒）。

**[images-pipeline-11]** 缺失的信号（事实：代码中不存在；影响为推断，中）：
- 词义相关性只看标题/标签的 token 前缀匹配，不看 `description`（Commons `ImageDescription` 虽然抓到 `extra["description"]`，只用于黑名单，不用于打分，`select.py:72` vs `:83`）；不看 Openverse `category`（fixture 里该字段存在，`openverse.py` 未读取）；没有语义相似度，也不与词义/例句比对。
- 人脸/人物：没有任何人脸检测或人物数量信号（无 OpenCV/ONNX 依赖，`backend` 依赖只有 Pillow、defusedxml、httpx 等，见 `ATTRIBUTION.md` §5）。
- 图中文字：只靠黑名单词（text/poster/document/screenshot），没有 OCR 或「文字含量」估计。
- 宽高比：只有 +1 的偏好和 0.6–2.2 的硬界，竖图（如 election 的 516×800）照样可被选中，然后在前端 16:10 的盒子里被 `object-fit: cover` 裁掉约 60%（算法：盒高 W/1.6=0.625W，图按宽缩放后高 W×800/516=1.55W，可见比例 0.625/1.55≈40%）。
- 画面复杂度/主体单一性：没有任何估计（无边缘密度、颜色数、JPEG 熵等启发式）。
- 儿童适宜性：仅 Openverse `mature=false`、Pixabay `safesearch=true`、Commons `Restrictions`，以及黑名单中的 nude/sex/porn/gore/blood/weapon/gun/corpse。

### D. 存储与展示（任务 c）

**[images-pipeline-12]** 下载与归一化：只允许 https + 443 端口 + 公网 IP（DNS 固定、≤ 3 次重定向逐跳校验）、`Content-Type: image/*`、字节上限 `WD_IMAGE_MAX_BYTES=8_000_000`、魔数 JPEG/PNG/WebP；Pillow `MAX_IMAGE_PIXELS=40_000_000`、`verify()`、`exif_transpose`、透明度合成到白底、长边 ≤ `WD_IMAGE_MAX_EDGE`（默认 800，允许 100–4096）、重编码为渐进式 JPEG q82，去 EXIF/ICC。生成的 SVG 走 `sanitize_svg.clean`，≤ 60 KB。（事实，高）
- `backend/wd/images/fetch.py:40-43`（`JPEG_QUALITY = 82`）、`:124-156` `validate_url`、`:194-237` `safe_download`、`:241-268` `normalise_image`（`:264-265` `img.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)`）；`config.py:159-160`、`:525-526` `image_max_edge=integer("WD_IMAGE_MAX_EDGE", 800, 100, 4096)`；`sanitize_svg.py:23` `MAX_BYTES = 60_000`。
- 注意 Commons 的 `iiurlwidth` 是常量 800（`wikimedia.py:27`），与 `WD_IMAGE_MAX_EDGE` 无关：把 MAX_EDGE 调到 1600 对 Commons 照片无效，只对 Pixabay（1280）、Pexels（940）、Openverse（原图）生效。

**[images-pipeline-13]** 存储：`<DATA_DIR>/images/<2hex>/<sha256>.jpg|svg`，0600，原子写入，按内容哈希去重（同一文件可服务多个词）；`word_images` 每词恰好一行 `active`（部分唯一索引），旧 active → `superseded`，举报 → `rejected`；`provider` 的 CHECK 只允许 `wikimedia/openverse/pixabay/pexels/claude_svg`，`mime` 只允许 `image/jpeg`/`image/svg+xml`，`status` 只允许 `active/superseded/rejected`。（事实，高）
- `store.py:41-65` `write_bytes`、`:76-120` `activate`；`backend/wd/migrations/0001_init.sql:248`（provider CHECK）、`:265`（mime CHECK）、`:267`（status CHECK）、`:272` `CREATE UNIQUE INDEX ux_word_images_active ON word_images(word_id) WHERE status = 'active'`。
- 推论（高）：任何新来源（如生成式图片、管理员上传）或「候选」状态都需要迁移脚本改 CHECK 约束，并同步 `backend/wd/schemas.py:46` `ImageProviderName = Literal[...]`、`frontend/src/api/types.ts:84` 的联合类型、`service.py:240-243` `photo_mix` 的 provider 列表。

**[images-pipeline-14]** `alt_zh` 来源：照片激活时把当时内容的 `image_alt_zh`（清洗后 ≤ 60 字；提示词要求 ≤ 30 字）快照进 `word_images.alt_zh`；Claude SVG 用模型返回的 `alt_zh`（≤ 200 字截断）；模板卡 `alt_zh=null`。前端 `alt` 属性优先取 `content.image_alt_zh`，其次 `image.alt_zh`，否则空串——`alt_zh` 只作屏幕阅读器文本，**界面上不显示**。（事实，高）
- `handler.py:131-133`、`store.py:123-149`（`alt_zh=alt_zh`）、`store.py:166`（SVG：`alt_zh=(alt_zh or "").strip()[:200] or None`）、`service.py:29-41` `card_meta`（`"alt_zh": None`）、`service.py:78`；`frontend/src/components/study/WordImage.tsx:46` `const altText = alt?.trim() || image.alt_zh || '';`、`:53-64` `<img … alt={altText} loading="lazy" decoding="async" width=… height=…>`；`StudyCard.tsx:306` `alt={content?.image_alt_zh ?? null}`。

**[images-pipeline-15]** 前端显示尺寸与裁切：固定 16:10 盒子，宽 100%，页面内容最大宽 720 px（盒子最大约 720×450 CSS px）；照片 `object-fit: cover`（居中裁切），SVG/卡片 `object-fit: contain` 加边框；图片只出现在学习卡**背面**（释义之后），正面没有图；换图/举报按钮只在单词详情页接线，学习页（StudyPage）渲染 `StudyCard` 时不传 `onImageRefresh/onImageFlag`。（事实，高）
- `frontend/src/components/study/study.css:435-442`（`aspect-ratio: 16 / 10`）、`:456-463`（`object-fit: cover`）、`:465-467`（flat → `contain`）；`frontend/src/styles/tokens.css:54` `--content-max: 720px`；`StudyCard.tsx:297-310`（`study-card__back` 内 `<WordImage …>`；`:171`/`:206` 的 front face 没有 WordImage）；`frontend/src/pages/StudyPage.tsx:635,695` 只传 `showImage={settings?.show_images ?? true}`；`grep -rn "onImageRefresh\|onImageFlag" frontend/src --include='*.tsx'` 除 StudyCard 自身外无调用方；`WordDetailPage.tsx:193-213` 接 `refreshWordImage`/`reportWord`。
- 推论（高）：存 800 px 长边，在 720 CSS px 宽的桌面盒子上 DPR 2 需要 1440 px，放大 1.8 倍；390 CSS px 的手机 DPR 3 需 1170 px，放大 1.46 倍——目前的存储上限低于常见屏幕的像素需求。

**[images-pipeline-16]** 署名字段与显示：`word_images` 存 `title/creator/creator_url/license/license_url/landing_url/attribution_text`；`attribution_text` = `"{title}" · {creator} · {license}`，Openverse 优先用其自带 `attribution` 句（如 fixture：`"Apples" by Carriagehouse2011 is licensed under CC BY 2.0. To view a copy of this license, visit https://creativecommons.org/licenses/by/2.0/.`）；API `ImageMeta.attribution`（SVG/卡片为 null）；前端题注 `图片 · <text> ↗` 链接到 `landing_url`，SVG 显示「AI 生成示意图」，卡片「系统生成卡片」。（事实，高）
- `store.py:68-73` `attribution_line`、`:125`；`service.py:57-69`；`WordImage.tsx:26-33` `imageCaption`、`:69-75`；`frontend/src/i18n/zh.ts:54`（`imageSource: '图片', generatedCard: '系统生成卡片', aiImage: 'AI 生成示意图'`）。

**[images-pipeline-17]** 服务路径：`GET /media/images/{path}`（路径必须匹配 `^[0-9a-f]{2}/[0-9a-f]{64}\.(jpg|svg)$`，需会话 cookie，`Cache-Control: private, max-age=31536000, immutable`，SVG 另加 `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'`）；`GET /media/card/{id}.svg` 为模板卡（LRU 2000，`private, max-age=86400`）。模板卡是 800×500 的纯文字渐变卡（词头、音标、首条释义、首条例句）。（事实，高）
- `backend/wd/routers/media.py:26-31`、`:38-57`；`card_svg.py:20`、`:82-121`。

### E. Claude SVG（任务 d）

**[images-pipeline-18]** 提示词只有一句（`backend/wd/ai/prompts/svg_system.txt:1`）：「Produce a simple, flat-style educational illustration as a single SVG string for the given English word and Chinese concept description, to help a learner remember the word. Constraints: viewBox="0 0 800 500"; use only these elements: … ; 3–5 harmonious colours, large shapes; the English word in a <text> at the bottom (font-size 40, …); do not draw people's faces in detail; total length at most 8000 characters. Return {svg, alt_zh} …」。用户提示由 `display + meaning_zh(≤60) + concept(= image_alt_zh 或 meaning_zh, ≤60)` 拼成：`Draw an illustration for the word "abandon" (v. 放弃；抛弃). Concept: 被遗弃在雪地里的汽车。`。风格描述里**没有**受众年龄、没有「单一主体/去杂乱」、没有颜色/线条风格的进一步约束。（事实，高）
- `backend/wd/ai/svg.py:32-33` `CONCEPT_MAX = 60`、`MEANING_MAX = 60`，`:40-52` `build_user_prompt`/`prompt_for`；schema `backend/wd/ai/schemas/svg_v1.json:1` `{svg, alt_zh}` 均必填。

**[images-pipeline-19]** 触发规则（「never trade a photo for a Claude SVG」）：`fetch_image` 在**所有** provider 都没给出可用照片后，只有当该词当前**没有** active 图、`WD_SVG_VIA_CLAUDE=1`、job priority < 90、AI 开启且 `WD_AI_SVG_DAILY_BUDGET_USD > 0`、且该词「正在被学」（`user_words.state IN ('new','learning')` 或在最近 2 天未完成的批次里）时才入队 `generate_svg`；否则 `image_state='failed'`，服务模板卡。handler 在调用前与激活前各再查一次：期间若有照片落地就 `{"skipped":"photo_active"}`；只有管理员显式 `provider:"claude_svg"`（`requested:true`）才会覆盖已有照片。换一张（有 active 图）找不到新图 → 保留原图，`image_state='ready'`，不花 SVG 预算。（事实，高）
- `handler.py:102-103` `_svg_allowed`，`:198-206`；`service.py:223-234` `word_is_studied`；`svg.py:102-107`、`:126-130`；`handler.py:139-146`（显式请求用独立 dedupe key `svg:<id>:req`）；测试 `test_images.py:247`（`test_refresh_with_an_active_photo_never_falls_back_to_svg`）、`:276`、`:299`、`:328`。

**[images-pipeline-20]** 成本：文档口径「an SVG card $0.028」、子额度 `WD_AI_SVG_DAILY_BUDGET_USD=0.50`（≈ 18 张/日）、单次 `--max-budget-usd 0.10`、超时 120 s；线上实测 34 次 `kind='svg'` 调用合计 $0.4207，平均 **$0.01237/张**（`0.4207/34`），平均 829 个输出 token、7.9 s，模型 `claude-sonnet-5-5`。按实测值子额度可画约 40 张/日（`0.50/0.01237=40.4`）；全库 9,162 词 ≈ $113（实测均价）或 $257（文档口径），在 $0.50/日子额度下需 ≈ 229 天（`9162/40`）。`svg` 这一类永远不走 OpenAI 格式备用模型。（事实，高；外推为推断，中）
- `docs/CLAUDE_INTEGRATION.md:407`、`:416`；`config.py:124,129`；`budget.py:272-276`；live-copy：`SELECT ROUND(SUM(cost_usd),4), COUNT(*), ROUND(SUM(cost_usd)/COUNT(*),5), ROUND(AVG(output_tokens)), ROUND(AVG(duration_ms)) FROM ai_calls WHERE kind='svg'` → `0.4207|34|0.01237|829|7931`；`config.py:61` `FALLBACK_TASK_KINDS = ("content", "lookup", "consolidate")`。

> **核验修正（INDEX §3 #19，2026-11-05）**：$0.01237 是每次成功调用的均价（34 次、SUM $0.4207），不是每张交付图——34 次只交付 30 张，4 次 SVG 被拒（$0.0491），每张交付 $0.0140（0.4207 ÷ 30）；按交付口径 $0.50/日子额度 ≈35 张/日（0.50 ÷ 0.0140），全库外推相应上调约 12%，依据 verify/images-pipeline.md [images-pipeline-20]、verify/image-memorability.md [image-memorability-17]。

**[images-pipeline-21]** SVG 质量门：`sanitize_svg.clean` 用 defusedxml 解析，元素/属性白名单，去 `href`/`on*`/`<image>`/`<use>`/`<foreignObject>`，强制 viewBox；解析失败即 `SvgRejected` → `image_state='failed'`，不自动重试。线上 34 个 `generate_svg` 任务中 4 个（11.8%）被拒，错误均为 `not well-formed XML: not well-formed (invalid token): line 1, column 2xx/4xx`（jobs 45、88、97、136；词 election、employee、property、have）。（事实，高；原因见未解决问题）
- `sanitize_svg.py:28-44`、`:65-79`、`:169-181`；`svg.py:134-142`；live-copy `jobs` 表 `result_json`。

### F. 用户/管理员操作与 exclude 逻辑

**[images-pipeline-22]** 换一张：`POST /api/words/{id}/image/refresh`（20/日/用户，priority 10）→ `fetch_image{exclude = 该词 active+rejected 行的 provider_ref 与 sha256}`；当前图保留到新图落地；与进行中的任务合并（exclude 并集、最新 provider/query），任务已 running 则排 `image:<id>:r<n>` 跟随任务。（事实，高）
- `backend/wd/routers/words.py:285-301`、`:31` `FETCH_IMAGE_PRIORITY_USER = 10`；`service.py:83-94` `exclude_for`、`:155-183` `enqueue_fetch`、`:205-211`。

**[images-pipeline-23]** 举报：`POST /api/words/{id}/report {target:'image', reason}` → 立即把**全局** active 图置 `rejected`（阈值 1）、写 `system_events('image_rejected')`、入队排除该图的 `fetch_image`；前端「不合适」按钮固定用 `reason:'irrelevant_image'`，反馈表单另有「配图无关/配图不合适」。handler 侧无论 payload 带不带 exclude，都会再并入该词全部 `rejected` 行（所以被举报过的图不会被再次选中）；`used_refs`（其他词正在用的图）只扣 2 分而非排除。管理员在「内容反馈」里的「换图」= `reject_active_image` + 重抓（无 query 覆盖）。（事实，高）
- `words.py:259-281`（`:278-280`）；`service.py:186-202`；`handler.py:153` `excluded = {…} | set(service.exclude_for(conn, word_id, statuses=("rejected",)))`、`:94-99` `_used_refs`、`select.py:98-100`；`WordDetailPage.tsx:204-213`；`admin_reports.py:88`；`AdminPage.tsx:1000-1001`。

**[images-pipeline-24]** 管理员重抓 `POST /api/admin/words/{id}/refetch-image {provider?, query?}`（priority 10）：`provider ∈ wikimedia|openverse|pixabay|pexels|claude_svg`，`query ≤ 100` 字符；`provider:"claude_svg"` 直接入队带 `requested:true` 的 `generate_svg`，会覆盖已有照片。前端 `adminRefetchImage` 已在 `endpoints.ts:538-540` 定义但**没有任何页面调用**，即「指定 provider/query 重抓」目前只能用 API 或 CLI `wd fetch-image <word> [--provider P] [--query Q] [--priority N] [--no-svg]`。（事实，高）
- `backend/wd/routers/admin_ops.py:413-427`、`:33` `REFETCH_PRIORITY = 10`；`schemas.py:1349-1351`；`service.py:214-220`；`handler.py:139-146`、`:349-356`；`grep -rn adminRefetchImage frontend/src` 只命中 `endpoints.ts`。

**[images-pipeline-25]** `fetch_image` 只有两类入队点：内容落地时（`content.enqueue_image`，仅当 `image_state != 'ready'`，priority 继承内容任务）和用户/管理员动作（换一张、举报、重抓）。**没有**任何机制在 `image_state='failed'` 的词后来被用户学习时重新抓图或补 SVG，也没有定时重试。（事实，高）
- `backend/wd/ai/content.py:253-261`（`if not ctx.cfg.images_enabled or (word.get("image_state") or "none") == "ready": return None`）；`grep -rn "enqueue_fetch\|\"fetch_image\"" backend/wd --include='*.py'` 仅命中 `content.py:259`、`images/service.py`、`images/handler.py`、`jobs/queue.py:34`（类型表）、`jobs/registry.py:35`、`schemas.py:1258`。
- 线上后果见 [images-pipeline-28]。

### G. 线上库统计（任务 e；live-copy.db，2026-11-05）

**[images-pipeline-26]** `word_images` 共 31 行、31 个词、全部 `active`，0 `rejected`、0 `superseded`：**30 张 `claude_svg`**（`license='generated'`，全部 800×500，平均 1,407 字节）+ **1 张 `wikimedia`**（`election`，CC0，516×800，95,117 字节，score 8，query `ballot box`，title `Urne Ballot box république`）。`words.image_state`：ready 31、failed 18、none 9,113。管理员概览口径 `with_photo=1`、`with_claude_svg=30`、`card_only=18`（= 有内容无图的词；49 个有内容的词全部落在这三类）。（事实，高）
- SQL：`SELECT provider, status, COUNT(*), ROUND(AVG(score),2), MIN(width)||'x'||MIN(height), MAX(width)||'x'||MAX(height), ROUND(AVG(file_bytes)) FROM word_images GROUP BY 1,2` → `claude_svg|active|30||800x500|800x500|1407` / `wikimedia|active|1|8.0|516x800|516x800|95117`；`SELECT image_state, COUNT(*) FROM words GROUP BY 1`；`photo_mix` 的 SQL 原样执行（`service.py:239-244`）→ `1|30|18`。

**[images-pipeline-27]** 举报：`content_reports` 0 行；`system_events` 没有 `image_rejected`（只有 `claude_auth` 14、`claude_unavailable` 2、`seed_imported` 1）；2 个用户且 `show_images` 均为 1。即 31 张图目前**零举报、零换图**。（事实，高）
- `SELECT * FROM content_reports` → 空；`SELECT kind, COUNT(*) FROM system_events GROUP BY kind`；`SELECT COUNT(*), SUM(show_images) FROM user_settings` → `2|2`。

**[images-pipeline-28]** 照片命中率为 0：`jobs` 中 49 个 `fetch_image` 全部 `done`，`result_json.status` 全为 `failed`（「no acceptable photo from any provider」）；priority 20 的 19 个全部带 `svg_job_id`，priority 30（03:30 预取路径）的 30 个只有 15 个带 `svg_job_id`。34 个 `generate_svg`：30 成功、4 被拒。唯一的照片（election）不是任何任务产出——对应任务 30 失败、SVG 任务 45 被拒；`provider_state.wikimedia.last_ok_at = 2026-11-02T08:13:44Z` 与该图 `created_at` 相同，且 CLI `wd fetch-image` 直接调用 `fetch_for_word` 不写 jobs 行——因此这张图来自手工 CLI 抓取。18 个 `failed` 词 = 15 个预取词（抓图时既不在 new/learning 也不在开放批次 → `word_is_studied` 为假，没有 SVG）+ 3 个 SVG 被拒的词（have、employee、property；election 的被拒 SVG 后被 CLI 照片覆盖）。这 15 个词现在都已进入 2026-11-05 的开放批次（状态 known/learning），但按 [images-pipeline-25] 不会再被自动抓图。（事实 + 推断，高）
- SQL：`SELECT priority, COUNT(*), SUM(result_json LIKE '%svg_job_id%') FROM jobs WHERE type='fetch_image' GROUP BY 1` → `20|19|19`、`30|30|15`；`SELECT COUNT(*), SUM(result_json LIKE '%image_id%'), SUM(result_json LIKE '%rejected%') FROM jobs WHERE type='generate_svg'` → `34|30|4`；对 15 个词的 `user_words.state`/`push_items` 查询见工作记录（例：`consumer|known|2|2026-11-05`）。

**[images-pipeline-29]** provider 健康：副本时刻 `openverse` 冷却到 `2026-11-05T13:28:24Z`（`ReadTimeout`，连续错误 4），`wikimedia` 冷却到 `13:33:24Z`（`SSL: UNEXPECTED_EOF_WHILE_READING`，连续错误 3，`last_ok_at` 仍是 11-02）；`provider_usage` 日计数：wikimedia 11-02 34 次、11-03 2 次、11-05 1 次，openverse 1/2/1。即 49 个任务里绝大多数根本没有拿到任何候选（网络/出口问题），而不是候选被打分淘汰——这意味着**现有打分/黑名单规则在线上几乎没被真正检验过**。（事实；归因为推断，中）
- `SELECT * FROM provider_state`、`SELECT * FROM provider_usage`；旁证 `docs/ops.md:267-275`（2026-10 该 Mac 出口 IP 曾被 Commons 持续 503，2026-10-28 部署实例抓到 27 张 Commons 照片）；本机依赖代理/SOCKS（见用户记忆）。

> **核验修正（INDEX §3 #21，2026-11-05）**：归因只对一部分成立——11-03 的 30 个任务只产生 2 + 2 次请求（冷却中的 provider 在 `handler.py:160-163` 被跳过且不计数），连同 11-05 的 1 个，≥27 个任务没有发出任何 provider 请求；但 11-02 的 18 个任务在 07:48–07:53 内产生了最多 33 次 Wikimedia 请求（≈1.8 次/任务），若有 429/5xx/网络错误会触发 15 分钟冷却、不可能出现 33 次，说明 Wikimedia 当时在应答，这 18 个任务的失败原因未知（HTTP 200 但无可接受/可下载候选，或不触发冷却的 4xx），需看 journal 的 `provider_cooldown`/`provider_error`/`provider_skipped` 事件；「打分/黑名单规则几乎没被检验过」仍是合理推断但未被证明，依据 verify/images-pipeline.md [images-pipeline-29]。

---

## 二、「让图更有助于记忆」的抓手（任务 f）

学习科学依据（均为通用结论，不是针对小学英语配图的直接实验；用于推断，置信度中/低）：
- 图优效应与双重编码：「Pictures and images are more likely to be remembered than words.」「Picture stimuli have an advantage over word stimuli because they are dually encoded; they generate a verbal and image code, whereas word stimuli only generate a verbal code.」「Concrete concepts presented as pictures are encoded into both systems; however, abstract concepts are recorded only verbally.」「During childhood, specifically among seven-year-olds, the picture superiority effect is lesser in magnitude than in other age groups.」（https://en.wikipedia.org/wiki/Picture_superiority_effect ，访问 2026-11-05）→ 推断：图要表现**具体可画的场景**（抽象词必须落到具象），并与读音/中文释义同屏出现；低龄学生从图中获益更依赖配套的语言编码。
- 画面负荷：Flack & Horst 2017（Infant and Child Development, DOI 10.1002/icd.2047）对三岁儿童的实验：「children who were read stories with only one illustration at a time learned twice as many words as children who were read stories with two or more illustrations.」（https://www.eurekalert.org/news-releases/473021 ，访问 2026-11-05）→ 推断：**一图一主体、少杂物、少文字**比「信息量大」的照片更利于词义绑定。
- 关键词法/互动意象（Atkinson & Raugh 1975，来自 WebSearch 摘要，未核对原文，低）：把新词与含义通过一幅「互动」心像连接能提升保持——对应本项目已有的 `mnemonic_zh` 与 `image_alt_zh`「图与词义的联系」字段，但目前图说明不展示。

下面每条给出：改哪里、代价（小 = 单文件/少量测试；中 = 跨 provider/前后端或需迁移；大 = 新数据模型 + 新 UI；均为推断）。

**[images-pipeline-30] 抓手 1：查询词构造加入词义/语境。** 现状只搜「关键词短语」或裸 lemma（[1]）。可做：(a) 把 `MAX_KEYWORDS` 提到 4 以用上内容层已存的第 4 个关键词（`handler.py:37`）；(b) 对 Commons 追加义项名词（如 `apple fruit`、`stock warehouse`）或用内容的 `meaning_en` 提取名词作为第二查询；(c) 没有内容时按词性过滤——介词/连词/助动词（`words.pos`）不搜裸 lemma，直接走 SVG/卡片，避免 `have`/`despite` 搜出随机照片；(d) 让内容提示词明确「主体单一、无文字、无人脸特写、小学生可理解」并要求给出一个「动词→可拍场景」。位置：`handler.py:64-78,134-137`、`content_system.txt:9-10`、`content.py:60-62`；代价小（提示词改动会使已生成的 49 条内容与新规则不一致，需 `force` 重生成，见旧分析 content-media 结论 4）。（推断，高）

**[images-pipeline-31] 抓手 2：provider 与图片类型选择（照片 vs 插画 vs 矢量；儿童向）。** 现有参数把所有 provider 都锁在「照片」：Commons `filetype:bitmap`、Pixabay `image_type=photo`、Openverse 不传 `category`。可直接利用的官方过滤：Pixabay `image_type=illustration|vector`、`category=education|animals|food|…`、`editors_choice=true`、`orientation=horizontal`（[6]）；Openverse `category=illustration`、`aspect_ratio=wide`、`size=medium|large`（[5]）；Commons `filetype:drawing`（SVG 剪贴画，含 Openclipart 导入）或 `filemime:image/svg+xml`，以及 `incategory:`/`deepcat:`（[4]）——但注意本项目的下载器只接受 JPEG/PNG/WebP（`fetch.py:43`），Commons 的 SVG 需要用 `iiurlwidth` 的 PNG 缩略图（Commons 会把 SVG 光栅化为 `thumburl` PNG，这正是现在下载的字段），所以 `filetype:drawing` 可能几乎零改动即可用（需实测，见未解决问题）。位置：各 `providers/*.py` 的 `params()`；若要「按请求切换类型」需给 `ImageProvider.search(query, limit)` 增加 style 参数（`interfaces.py:74-76`）并在 `handler.py:165` 传入；代价小到中。Pixabay/Pexels 需申请 key 并接受其条款（[44]）。（推断，高）

> **核验修正（INDEX §3 #22，2026-11-05）**：`filetype:drawing` 不是零改动——Commons API 实测（`iiprop=url|mime|thumbmime|mediatype`，apple 的三个 SVG）返回 `mime image/svg+xml`、`thumbmime image/png`、`thumburl` 以 `.png` 结尾，而 `wikimedia.py:97` 取的是原文件 `mime`，会被 `select.py:65-66` 的 MIME 规则拒绝；最小改动是 `iiprop` 加 `thumbmime` 并用它作候选 MIME；「未解决的问题 2」据此关闭，依据 verify/images-pipeline.md [images-pipeline-31]、O5。

**[images-pipeline-32] 抓手 3：候选打分增加信号。** 便宜且无新依赖的：把 `description`/`object_name` 纳入相关性匹配（`select.py:83`）；Openverse `category=='illustration'`/Pixabay `type` 加分；偏好横图（1.4–1.8 +2、竖图 −2）以配合 16:10 裁切；Commons 分类含 `Diagrams|Maps|Logos|Text|Screenshots|Documents` 已被黑名单覆盖，可再加 `Photographs of people`/`Portrait` 类的降权；用 Pillow 在 `normalise_image` 后算「颜色数/边缘密度」做复杂度惩罚（新增一次解码成本，小）。需要新依赖的：人脸检测（OpenCV/ONNX 模型，部署体积与 CPU 时间，中）、OCR 文字含量（中）、CLIP 类图文相似度（最有效但需模型服务或云 API，大）。位置：`select.py:80-101`、`handler.py:182-196`（下载后再评估需调整「第一个可用即激活」为「下载前 3 个再比」）。（推断，中）

**[images-pipeline-33] 抓手 4：按阶段切换风格（小学用插画）。** 图是**按词全局**存的（每词一张 active，[13]），而阶段既是词属性（`words.stage_min`）也是用户属性（`user_settings.current_stage`）。最省事的做法是按词的 `stage_min`（新增小学阶段后即「小学词」）全局决定风格：小学词走「插画优先」的 provider/参数链，其余走照片——只需在 `fetch_for_word` 读 `stage_min` 并选择不同 `names`/style（`handler.py:148-152`），加一个 `WD_IMAGE_PROVIDERS_PRIMARY` 之类的配置；代价小到中。若要「同一词给小学生插画、给高中生照片」，则必须存多张（按 style 维度）并在 `image_meta` 按用户阶段选图——迁移 `word_images`（CHECK/唯一索引 `0001_init.sql:267,272`）、`ImageMeta` 契约、`photo_mix`，代价大。（推断，高）

**[images-pipeline-34] 抓手 5：让学习者在候选中选。** 今天任务只下载并激活第一张（[3]），没有候选列表的任何 API/UI。需要：任务一次下载并保存前 N 张为新状态 `candidate`（迁移 status CHECK）；`GET /api/words/{id}/image/candidates` 与「选这张」端点；详情页 UI；每词多 N 倍网络与磁盘（现有一张照片 95 KB，全库 3 张/词 ≈ 9,162×3×95,117 B ≈ 2.6 GB；SVG 1.4 KB 可忽略）；并且「选择」会改**全局**图，多人部署时需要定义是个人偏好还是众包投票（与 [23] 阈值 1 的举报同一个问题）。代价大。（推断，高）

**[images-pipeline-35] 抓手 6：管理员人工策展。** 已有能力：API 69 的 `provider/query` 重抓（[24]）、CLI `wd fetch-image --provider --query`、「内容反馈」页的换图。缺口：没有管理员词表/搜索页，没有「换图并指定关键词」的 UI（`adminRefetchImage` 无调用方），没有上传端点（`word_images` 唯一 INSERT 在 `store.activate`，`store.py:105-113`）。最小可行：在 AdminPage 增加按 lemma 查词 + query/provider 表单（前端中等改动，复用 endpoints.ts:538-540）；进一步做 `POST /api/admin/words/{id}/image`（multipart 上传 → `normalise_image` → `store.write_bytes` → `activate(provider='admin', license/creator 手填)`），需要迁移 provider CHECK 与前端类型（[13]）。代价中。（推断，高）

**[images-pipeline-36] 抓手 7：SVG 提示词。** 现在是单句、无受众（[18]）。可加：「for primary-school learners」「exactly one central subject, plain background, no decorative clutter」「bright, rounded, kid-friendly shapes」「no text except the word」「escape & as &amp;」；并把 `concept` 从 ≤ 60 字放宽或改为由内容的 `image_alt_zh` + `meaning_en` 共同给出。位置：`svg_system.txt:1`、`svg.py:32-52`；代价极小，但每次改提示词都只影响**新生成**的卡（旧卡不会重画，除非管理员 `provider:"claude_svg"` 重抓）。另一个可量化收益：4/34 的 XML 解析失败可在 `activate_svg` 前加一步「裸 `&` → `&amp;`」修复（`sanitize_svg._parse` 之前，`sanitize_svg.py:65-79`），或在提示词里要求转义——每次失败白花 ≈ $0.012。（推断，高）

**[images-pipeline-37] 抓手 8：用生成式图片模型。** Claude 只能产 SVG 文本，不能生成位图；仓库里的备用适配器 `backend/wd/ai/providers/openai_http.py` 只实现聊天补全，`grep -n "images/generations" backend/wd/ai/providers/*.py` 无结果。需要的接口与改动：
- 外部接口：一个 HTTPS JSON 接口，输入 prompt，返回**公网 https 图片 URL**（才能复用 `fetch.safe_download` 的 SSRF 规则：https、443、公网 IP、`image/*`、JPEG/PNG/WebP、≤ 8 MB，`fetch.py:124-237`）。可选来源（访问 2026-11-05）：智谱 CogView-3-Flash——「CogView-3-Flash 是智谱推出的免费图像生成模型」，模型码 `cogview-3-flash`，尺寸 1024×1024/768×1344/864×1152/1344×768/1152×864/1440×720/720×1440（https://docs.bigmodel.cn/cn/guide/models/free/cogview-3-flash ）；接口 `POST https://open.bigmodel.cn/api/paas/v4/images/generations`，响应 `data[].url`，「图片的临时链接有效期为 30 天」，并返回 `content_filter`（https://docs.bigmodel.cn/api-reference/模型-api/图像生成 ）；CogView-4「0.06 元 / 次」，并发按账户等级 5/10/15/20（https://docs.bigmodel.cn/cn/guide/models/image-generation/cogview-4 ）。阿里云百炼通义万相 `wan2.2-t2i-flash` 北京地域 0.14 元/张、120 RPM；异步 `POST /api/v1/services/aigc/text2image/image-synthesis`（`X-DashScope-Async: enable`）+ `GET /api/v1/tasks/{task_id}` 轮询，宽高 512–1440，prompt ≤ 500 字，「Image URL links remain valid for 24 hours」，每次 1–4 张（https://help.aliyun.com/zh/model-studio/wan2-2-t2i-flash 、https://help.aliyun.com/zh/model-studio/text-to-image-v2-api-reference ）。OpenAI gpt-image-1 第三方价目「Low 1024×1024: $0.011」且据称 2026-10-23 退役（https://pricepertoken.com/gpt-image-pricing ，第三方，低）。
- 全库规模成本（算式 9,162 × 单价）：CogView-3-Flash ¥0；CogView-4 ¥549.72；wan2.2-t2i-flash ¥1,282.68。对比 Claude SVG $113–257（[20]）。
- 代码改动：新 provider（或新 job 类型 `generate_image`）→ 生成 → `download_and_store` → `activate(provider='<新名>', license='generated')`；必须改 `word_images.provider` CHECK（`0001_init.sql:248`）、`select.license_allowed`（`generated` 现被归为 `other` → 硬拒，`base.py:184-205`、`select.py:63-64`，生成图应绕过 `select.rank`）、`service.image_meta` 的 `kind`/署名分支（`service.py:57-79`：非 `claude_svg` 一律当照片并拼署名）、`photo_mix`、`ImageProviderName`、前端类型与题注；预算台账 `ai_calls.kind` CHECK 只允许 `content/lookup/consolidate/svg/probe`（live schema），若要计入 AI 预算也需迁移。还需定义内容安全兜底（provider `content_filter` 拒绝时回退到 SVG/卡片）。代价中到大。（事实 + 推断，高）

> **核验修正（INDEX §3 #26，2026-11-05）**：OpenAI `gpt-image-1`「2026-10-23 退役」与一手来源不符——官方弃用页（访问 2026-11-05）没有 `gpt-image-1` 条目，列出的是 `dall-e-2`/`dall-e-3` → 2026-05-12 停用、`gpt-image-1-mini`/`gpt-image-1.5`/`chatgpt-image-latest` → 2026-12-01 停用（替代 `gpt-image-2.5-sunburst/-flare`），该句应删除或改写；另智谱同一接口还接受 `glm-image`（0.1 元/次），本条清单漏列；国内两家的价格、接口、算式确认，依据 verify/images-pipeline.md [images-pipeline-37]、O4。

**[images-pipeline-38] 抓手 9：每词存多张候选 / 预取备选。** 与 [34] 共用数据模型；即使不开放给学习者，也能让「换一张」零网络等待（现在要走 3 s 轮询最多 20 次，`WordDetailPage.tsx:34-35`），并在 provider 冷却时仍有图可换。成本同 [34] 的磁盘估算。（推断，中）

**[images-pipeline-39] 抓手 10：失败词的自动重试。** [25]/[28] 显示 15 个词因抓图时「还没被学」而永久停在模板卡。小改：在用户动作把词置为 `new/learning` 或批次构建选中该词时，若 `image_state='failed'` 且上次 `fetch_image` 早于 N 天，则 `service.enqueue_fetch(priority=20)`（`services/bank.py` 与 `services/batches.py` 的内容入队点旁边，已有 `enqueue_image` 可借用，`content.py:253-261`）。代价小。（推断，高）

**[images-pipeline-40] 抓手 11：展示位置与清晰度。** (a) 正面不显示图（[15]）：在「尝试回忆」阶段把图作为提示（图→词）是教学上常见的检索练习，需要 `StudyCard` 正面可选显示 + 设置项，代价小到中；(b) 把 `image_alt_zh`（「图意：…」）作为可见小字说明，显式建立图—义联系，代价极小（`WordImage.tsx:67-76`）；(c) 把 `WD_IMAGE_MAX_EDGE` 提到 1200–1600 并把 `THUMB_WIDTH`（`wikimedia.py:27`）改为可配置，匹配 DPR 2–3 屏幕（[15] 的放大倍数），磁盘约 ×2–4；(d) 竖图改用 `contain` 或在打分里压低竖图（[32]）。（推断，中）

**[images-pipeline-41] 抓手 12：用学习者反馈改进选图。** 现在单次举报即替换全局图、不记分、不聚合（[23]），且线上零反馈（[27]）。可把「换一张/不合适」记录为负样本（`system_events('image_rejected')` 已写 provider、image_id、reason）并在重抓时对同 provider/同 title 词的候选降权；再加一个轻量「这张图好记 👍」计数做正样本。代价中。（推断，中）

---

## 三、约束（任务 g）

**[images-pipeline-42] 许可白名单与署名义务。** 只接受 CC0/Public domain/PD/CC BY/CC BY-SA 以及 Pixabay/Pexels 自有许可，NC/ND 一律拒绝（`base.py:184-205`）。CC BY/BY-SA 要求署名（标题、作者、许可、链接——四个字段都已存并在题注显示，[16]）；缩放重编码后的副本仍受 BY-SA 约束（`ATTRIBUTION.md` §3：「CC BY-SA images additionally remain under CC BY-SA」）。Commons 复用指南（https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia ，访问 2026-11-05）：公有领域作品「may not have a strict legal requirement of attribution … but attribution is recommended to give correct provenance」。（事实，高）

**[images-pipeline-43] Pixabay/Pexels 条款。** Pixabay Content License（https://pixabay.com/service/license-summary/ ，访问 2026-11-05）：「Use Content without having to attribute the author (although giving credit is always appreciated …)」；允许「Modify or adapt Content into new works」；禁止「sell or distribute Content … on a Standalone basis」、用于商标；API 文档另要求「show your users where the images and videos are from, whenever search results are displayed」、缓存 24 小时、禁止永久热链（本项目下载自存，满足）。Pexels：API 文档「Show a prominent link to Pexels」「Always credit our photographers when possible」；许可页与帮助中心对抓取器返回 403，搜索摘要称「you can use them for free for personal and commercial purposes without attribution」（https://help.pexels.com/hc/en-us/articles/360042295174 ，访问 2026-11-05，未能直接核对原文，中）。两者都把「识别出的真人不得被负面呈现」列为限制——对儿童向配图是额外的审核点。（事实/中）

**[images-pipeline-44] CSP 与同源服务。** 页面 CSP `default-src 'self'; img-src 'self' data:; …`（`backend/wd/main.py:93-96`）：任何图片必须经 `/media/...` 同源、带 cookie 提供（`media.py:38-48`），不能热链 provider 或生成模型返回的临时 URL（智谱 30 天 / 百炼 24 小时有效的链接必须先下载）；SVG 以 `default-src 'none'; style-src 'unsafe-inline'` + `nosniff` 提供，前端只用 `<img>` 嵌入（`media.py:27`、`WordImage.tsx:53`）。移动端 WebView 方案对 cookie 门禁 /media 的依赖见旧分析 `capacitor.md:18-25`。（事实，高）

**[images-pipeline-45] 尺寸与格式上限。** `WD_IMAGE_MAX_EDGE` 默认 800、范围 100–4096（`config.py:526`）；`WD_IMAGE_MAX_BYTES` 默认 8,000,000（`:525`）；只接受 JPEG/PNG/WebP 输入（`fetch.py:43`），输出统一 JPEG q82 渐进式（`:267`），SVG ≤ 60 KB、≤ 5000 元素、深度 ≤ 64（`sanitize_svg.py:23-25`）；`word_images.mime` CHECK 只允许 jpeg/svg（`0001_init.sql:265`），所以 PNG/WebP 透明图会被白底合成后转 JPEG。（事实，高）

**[images-pipeline-46] Wikimedia 每日限额与礼仪。** 「2000/日」是本项目自设的软上限（`WD_WIKIMEDIA_DAILY_LIMIT`，`config.py:162`，`quota.py:39-40`），Wikimedia 官方没有硬性日配额（[4] 引文），但要求串行请求、有意义的 UA、非交互任务用 `maxlag`（本项目未传 `maxlag`）。按 1 req/s 与 2000/日计算，全库 9,162 词每词 1–3 次搜索需 9,162–27,486 次请求 ≈ 4.6–13.7 天（`N/2000`）。（事实 + 算式，高）

**[images-pipeline-47] 预热与优先级约束。** priority ≥ 90（管理员预热）永不用 Openverse、永不画 SVG（`handler.py:158-159,102-103`；旧分析 content-media 结论 18）；03:30 预取（priority 30）会抓图但词尚未「被学」时不画 SVG（[28]）。IoWorker 单线程、一次一个任务（`handler.py:3`）。（事实，高）

**[images-pipeline-48] 大陆/出口可达性。** Commons、Openverse 均为境外服务；本机出口在 2026-10 曾被 Commons 持续 503（`docs/ops.md:267-275`），2026-11-05 副本中两家都处于冷却（SSL EOF / ReadTimeout，[29]）。智谱与百炼为境内接口（[37]），Pixabay/Pexels 为境外 API。部署在东京（用户记忆中的 Lighthouse Tokyo 方案）可绕开出口问题，但本地 Mac 运行时的抓图可靠性取决于代理。（事实/推断，中）

---

## 未解决的问题

1. Commons 结构化数据检索：`haswbstatement:P180=Q…`（depicts）在 Commons 文件命名空间经 `generator=search` 是否可用——WikibaseCirrusSearch 帮助页只确认在 Wikidata 上的语法（https://www.mediawiki.org/wiki/Help:Extension:WikibaseCirrusSearch ），`Commons:MediaSearch` 说 MediaSearch「uses categories, structured data and wikitext from Commons, and Wikidata」并提到 `haswbstatement`/`incaption`，但没有给出 API 参数名。需要一次真实查询验证（本任务不发实请求到 Commons）。
2. `filetype:drawing` 命中的 SVG 文件，其 `imageinfo.thumburl` 是否总是 PNG 且 `mime` 字段为 `image/svg+xml`（会被 `select.reject_reason` 的 MIME 规则拒绝，`select.py:65-66`）——若是，抓手 2 需要同时放宽 MIME 判定或改用 `thumbmime`。
3. Openverse 生产环境匿名限额的官方数字（API 描述不给；DESIGN §9 的 20/min、200/day 为项目自测）。
4. 4 次 SVG「not well-formed XML」的根因（推测为文本中的裸 `&`），需看 `claude-logs/` 下的原始输出（线上数据目录本任务禁止触碰）。
5. 生成式模型的内容过滤在学校词表上的拒绝率（库中有 `weapon`、`sexual`、`blood` 等词；智谱返回 `content_filter` 等级，百炼未核对）；以及 CogView-3-Flash 的具体限流（文档指向需登录的 rate-limits 页）。
6. 线上 49 个任务几乎没有拿到候选是网络原因（[29]）——打分/黑名单规则的真实命中率与误杀率尚无数据；建议在出口正常的机器上对一个阶段样本（如 200 个小学高频词）跑 `wd fetch-image --no-svg` 并人工评分，再决定抓手 1–3 的优先级。
7. 「让学习者选」与「单次举报即全局替换」在多人部署下的产品决策（个人图 vs 全局图），数据模型决定代价量级（[34]）。
8. 是否存在直接比较「照片 vs 扁平插画」对小学生英语词汇保持的实验——本次只找到通用的图优效应、绘本插图负荷与关键词法证据，结论置信度低。
