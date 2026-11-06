# word-Dance 词库维护机制与「管理员维护共享词库」模式分析

日期：2026-11-04。前置文档：`docs/PUBLIC_LAUNCH_AND_IOS.md`（2026-11-03 的公网部署与 iOS 分析）。

决策背景：受众以中国大陆学习者为主，按大陆用户优先规划。Anthropic 的地区政策以最终用户所在地判定，因此大陆学习者的操作不能实时触发 Claude 调用。本文回答两个问题：

1. 目前网页版的单词库是如何更新和维护的；
2. 能否改为由管理员（你或其他授权人）在服务端手动更新共享词库，所有前端只读。

方法与证据：9 个并行读者按切片读代码（312 条带 `file:line` 的结论），16 项对抗性核验（其中 10 项在你 Mac 数据库的 `.backup` 副本或临时数据库上实际执行），三套独立方案加两位评审。全部材料在 `docs/analysis/2026-11-04-library-curation/`。行号以 2026-11-04 的 `main`（9ab13a5）为准。

---

## 0 一页结论

### 0.1 问题一：词库今天是怎么更新和维护的

- 词库是四张全局表：`words`/`word_forms`（词典层）、`word_contents`（例句等 AI 内容）、`word_images`（配图）。学习者的一切数据都在每用户表里。所有前端看到的词库就是 `is_public = 1` 的那组行。
- 词典层只有一个管理员写入通道：改种子文件 `data/seed/vocab.jsonl.gz`，然后 `wd import-seed` 或重启服务自动导入。这是幂等的按 lemma 合并，只改词典列，不删词，不碰内容、配图和用户数据。全量导入实测 0.2 秒（记录数见 `data/seed/stats.json`）。种子文件自 2026-10-14 提交后的首次改版是 K-12 五阶段发布（`docs/releases/2026-11-k12-stages.md`）：阶段归属改为只取 `data/lists/` 里官方词表的词头。
- 内容层只能由 Claude 写：唯一写入点是 `generate_content` 任务处理器，9 个触发点里 7 个由学习者的操作触发（标不熟悉、构建今日词汇、点「生成例句」、自添词校验通过等），管理员只有「预生成」和「重新生成」两个杠杆，而且和用户共用同一个 AI 开关。没有写入、编辑、导入、导出内容的接口或命令。
- 运行时词库增长的唯一非管理员路径是用户自添词：安装了 ECDICT 时，真实英文词不经 AI 即成为公开词条（例句仍会排队生成）；没有 ECDICT（你 Mac 上就没装）时，每个未知词都会变成私有临时行并排一个 Claude 校验任务，校验通过才公开。
- 现在的「关闭 AI」是暂停不是禁止：`WD_AI_ENABLED=0` 让 worker 空转并让两个显式接口返回 503，但用户的添加、标记、夜间整理仍会往队列里塞任务，AI 一恢复就全部执行；前端也不读这个开关。
- 你 Mac 上这套库的现状（2026-11-04 快照，K-12 发布之前；发布后的记录数以 `data/seed/stats.json` 为准）：9,162 个种子词全部公开有效，48 个词有内容，31 张图（30 张是 Claude SVG），0 个用户自添词，ECDICT 未安装，从未跑过预生成。

### 0.2 问题二：管理员在服务端维护、所有前端只读，是否可行

**可以，而且架构本来就是这样设计的。** 四张全局表就是共享词库；前端没有任何缓存（请求带 `no-store`，服务端也回 `no-store`），服务端写入下一次请求就可见；手工写入的内容行只要字段完整、指针正确，详情页、学习卡片、今日词汇、SVG 卡片全部直接读取，不需要任何任务（已在临时库上实测）。未来的 PWA 或 iOS 客户端读的是同一套接口，结论不变。

缺的不是存储，是三样东西加一套工具：

| 缺口 | 现状 | 要做什么 |
|---|---|---|
| 策略保证 | 开关只是暂停；10 个入队点不看开关 | 新增 `WD_AI_POLICY=curated`，在入队点、调度器、worker 三层拦住，启动时清理残留；前端按标志隐藏 AI 按钮并改文案 |
| 内容来源 | 只能由服务器上的 Claude 生成，凭证是你的公司 Enterprise 席位，且你身处大陆 | 二选一：服务器上接国产模型（新适配器），或由身在支持地区的协作者用其个人 Console key 在另一台机器上生成 |
| 搬运工具 | 内容和配图没有导入导出，只能整库恢复 | 内容包 CLI：按 lemma 导出、幂等导入、短事务、不碰任务队列 |
| 管理工具 | 不能建词、改词、下架、审核、转正用户词 | 审核队列、下架、最小词库管理页，分期做 |

### 0.3 推荐路线与工作量

| 阶段 | 内容 | 人日 | 产出 |
|---|---|---|---|
| A 只读安全模式 | 策略开关三层拦截、启动清理、前端隐藏与文案、安装脚本容忍无 claude、不变量测试 | 8–11 | 公共服务器上学习者的任何操作都不可能产生模型调用 |
| B 生成来源 | B1 国产模型适配器加 50 词评测（推荐）；或 B2 协作者用个人 Console key 在境外机器跑现有 Claude 流程（零代码） | B1 7–9；B2 0 | 9,162 词的例句一次填满：B1 个位数美元；B2 约 $37–50 |
| C 运营闭环 | 内容包导入导出、预生成 CLI、审核队列、下架与最小词库页、AI 标识与条款、配图反馈阈值、种子回流 | 13–15 | 用户贡献词能被人工审核后进入共享词库 |
| D 后续 | 审核员角色、图片上传、Messages/Batch 适配、国产模型下的实时 AI（需主体与登记） | 10–15 | 可选 |

合计约 35–45 人日，分布在一个季度；让公共服务安全只需要前 10 人日左右。

### 0.4 只有你能决定的事

见第 3 节。最关键的四项：内容由谁、用什么模型生成（B1 还是 B2）；上线时未知词是拒绝还是进审核队列；Mac 上用公司席位生成的 48 条内容是重做还是沿用（建议重做）；是否要向 Anthropic 书面确认「缓存输出给大陆读者」这一推断（走 B2 时必须问）。

---

## 1 现状：词库是如何更新和维护的

### 1.1 数据分层：四张全局表 + 每用户表

全局（所有用户共享）的只有四张表，其他全部按用户存储（DESIGN §3.1「内容从不按用户存」）。

| 表 | 存什么 | 谁在写 | 位置 |
|---|---|---|---|
| `words` | 每个词条一行，`lemma` 全局唯一。词典字段（phonetic / translation / definition / pos / frq / bnc / collins / oxford / exchange / stage_xs·zk·gk·cet4·cet6 / stage_min / exam_tags / cet6_star）；来源与信任标志（`source` ∈ seed·ecdict·claude·user，`is_public`，`is_valid_english`，`safe_for_sharing`，`created_by_user_id`，`merged_into_word_id`）；状态指针（`active_content_id`·`content_state`，`active_image_id`·`image_state`，`difficulty`） | 种子导入 `seed.py`；用户添加时的 `services/words.resolve`；三个 AI 处理器（lookup / content / consolidate）改标志与空字段 | `migrations/0001_init.sql:166-216` |
| `word_forms` | 词形 → 原形（went → go），由 ECDICT 的 exchange 代码重建 | `seed.py`；lookup / consolidate 写 `alt` 行 | `0001_init.sql:219-228` |
| `word_contents` | AI 内容：meaning_zh / meaning_en / examples[{en, zh}]×3–4 / collocations / mnemonic_zh / image_keywords / image_alt_zh / difficulty；按词版本化（version，prompt_version=当前 `content.PROMPT_VERSION`（`content-v2`），model），每词至多一条 `active` | **只有** `ai/content.py` 的 `store_content`（全后端唯一的 INSERT / UPDATE） | `0001_init.sql:230-243`，`ai/content.py:212-218` |
| `word_images` | 每词至多一张 `active` 图：provider ∈ wikimedia·openverse·pixabay·pexels·claude_svg，许可与署名字段；文件在 `数据目录/images/<2hex>/<sha256>.jpg|svg` | **只有** `images/store.py` 的 `activate` 插入；反馈路径写 `rejected`，`images-prune` 删除 | `0001_init.sql:245-276` |

每用户：`user_words`（生词库，含 needs_attention / attention_msg / SRS 字段）、`review_logs`、`daily_stats`、`push_batches` / `push_items`（今日词汇）、`bank_suggestions` / `consolidation_runs`（整理建议）、`user_settings`。

可见性只有一条规则（DESIGN §5.2）：`is_public = 1 OR created_by_user_id = 我 OR 我持有该词的 user_words 行`，管理员看全部。实现上有两份：SQL 片段 `deps.visible_word_sql` 用在词库列表、搜索预览和 SVG 卡片三处，按 id 读取的路由（详情、内容、配图、标记、反馈）用 Python 版 `words.is_visible`；筛词和推荐词用更严的 `is_public = 1 AND is_valid_english = 1`；`/api/stages` 只按 `is_public = 1` 计数。核验发现两处低风险绕过：整理建议的目标词与「是否改为」提示词的简要信息不经过可见性检查（`services/words.py:321-324`，`services/suggestions.py:75-78`）。

### 1.2 词典层：种子文件是唯一的管理员写入通道

**来源与构建。** 词典字段（音标、释义、词频、词形变化）来自 ECDICT 1.0.28（MIT，`data/licenses/ECDICT-LICENSE`）；**阶段归属只来自 `data/lists/` 里官方文件的词头**——教育部 2022 课标二级（小学 `xs`）、三级与附表（初中 `zk`）、上海市教育考试院 2020 初中词汇表（单词、附表、词组 → `zk`）、高中课标 2020 修订 ∪ 2025 修订（`gk`）；四级 / 六级沿用 ECDICT 考试标签与可选的 mahavivo CET 四表（表缺席时现有行的 CET 旗标逐字保留）。构建器是 `backend/wd/seedbuild/`（`make seed`：`scripts/build_seed.py` 按 `data/lists/manifest.json` 做集合代数与 12 条归一化规则 → `scripts/seed_diff.py` 写 `data/seed/DIFF.md` 并断言「旧 lemma 一个不少」「xs ⊆ zk」→ `scripts/pack_seed.sh` 以 `gzip -9 -n` 打包并核对 `stats.json.content_sha256`），两次构建字节相同。记录数、每阶段词数、课标外词数一律以 `data/seed/stats.json` 为准（本文不抄数字）。种子**没有例句、搭配、助记**；考研 / 托福 / 雅思 / GRE 只是展示用标签，不是阶段；掉出所有官方表的老词不删除，变成 `stage_min` 为空的「课标外」词典词（只在「全部」页签与搜索可见，不进筛词与推荐词），旧出处以 `legacy:zk` / `legacy:gk` 令牌保留；导入时不做释义质量检查（人工修正走 `data/lists/overrides.tsv`，上限 30 条）。要改阶段来源，改的是 `data/lists/` 的词表文件与 manifest 再重建种子，而不是数据库里的 `words.sources`。

**导入入口三个。** `wd import-seed [--file PATH] [--force] [--dry-run] [--report PATH]`（`--dry-run` 只读文件与 `words` 表，打印或保存将要发生的插入、更新、孤儿、各阶段旗标增减与 `stage_min` 迁移矩阵，不写任何东西）；`deploy/install.sh` 第 6 步；以及**每次 `wd serve` 启动**时 `main.seed_check` 比较 `kv.seed_version` 与文件**解压后内容**的 sha256（`seed.seed_digest`），不同就自动导入——所以 Mac 与 Linux 用不同的 gzip 重打包同一份记录不会触发重导，而迁移 0011 删掉 `kv.seed_version` 则恰好强制一次重导。没有任何 HTTP 或管理页入口。

**导入语义**（`seed.py:72-82`，已在临时库和你库的副本上实测）：

- `INSERT … ON CONFLICT(lemma) DO UPDATE`，只在种子管理列（含五个阶段旗标 `stage_xs … stage_cet6` 与 `stage_min`）或信任标志有差异时更新该行；`stage_min` = 记录 `stages[]` 中最低阶段的索引（1 小学 … 5 六级），空列表 → NULL；未知阶段码只计数告警、不拒绝（硬门在构建器）；
- 对文件里的每个 lemma 强制 `source='seed'`、`is_public=1`、`is_valid_english=1`、`safe_for_sharing=1`、`merged_into_word_id=NULL`。同名的用户临时词会被「转正」，词典列被种子记录覆盖，`created_by_user_id` 保留；
- **从不删除** `words` 行（文件里删掉的词留在库里；掉出全部官方表的词只是变成课标外）；非 `alt` 的词形行会被删除重建，包括由记录 `aliases[]` 写入的 `kind='alias'` 官方拼写行（`Mr` → `mr.`，迁移 0013）；
- **从不触碰** `word_contents`、`word_images`、`active_*`、`content_state`、`difficulty` 以及任何每用户表；
- 所有写入在一个 `BEGIN IMMEDIATE` 事务里；成功后写 `kv.seed_version`、`kv.seed_imported_at` 和一条 `system_events('seed_imported')`，管理页「词库版本」显示的就是这个哈希；
- 实测（75df534 种子）：你库副本上全量 `--force` 导入 9,162 条，`import_seed` 内 0.2 秒，持有写锁 0.21 秒，进程总耗时 0.5 秒；词库、内容、配图、用户表字节级不变。`import-seed` 不检查 worker 租约，可以在服务运行时执行——但 K-12 发布的首次导入要在停服务、迁移 0011 之后做（`docs/releases/2026-11-k12-stages.md`）。

**所以管理员今天已经可以**：改一行 JSONL 的释义或音标（更稳的做法是写进 `data/lists/overrides.tsv` 再 `make seed`，重建可复现）、追加新词（只需 `word` 字段；不给 `stages` 则 `stage_min` 为空，只在「全部」标签可见，不会进入筛词与推荐词）、修正词形，然后打包、提交、部署或重启。**不能**：删词或下架、提供例句、在网页上操作。

**一个陷阱（已复现）。** `kv` 只记录哈希，不记录路径。`wd import-seed --file 自定义文件` 之后，下次服务启动或下次 `install.sh`（第 6 步也是不带 `--file` 的 `wd import-seed`）会再次导入仓库种子，把两边都有且被你改过的 lemma 改回原值；只在自定义文件里的词因为不删除而保留。你 Mac 的 `.env` 里 `WD_SEED_PATH=""`，等价于未设置，也在这个陷阱范围内。要么替换 `data/seed/vocab.jsonl.gz`，要么把 `WD_SEED_PATH` 指向自定义文件。`seed_check` 对损坏或不配套的种子文件（截断的 gzip、未知阶段码）现在有防御：导入异常被捕获并记录为 `system_events('seed_import_failed')`（管理页事件表可见），服务用库里已有的词表继续启动，下次启动再试；改种子前仍应先在副本上 `wd import-seed --file … --dry-run` 看计划，导入后 `wd check db` 看全部不变量（schema 14 起八条，含学习顺序四条——导入会在同一事务里重算 `learn_rank`）。

**运行时的非管理员增长路径。**

- **ECDICT 命中**：需要 `WD_ECDICT_DB_PATH` 指向 851 MB 的 `stardict.db`（`deploy/fetch_ecdict.sh` 下载，仅 GNU 工具）。用户添加一个不在种子里的词时，直接新建全局公开行（`source='ecdict'`，`is_public=1`，`is_valid_english=1`），**不需要 AI 校验**（`services/words.py:669-677`）；但加入生词库这一步照常给它排一个 `generate_content` 任务，`content_state` 变成 queued。例外：译文全为「[网络]」的行按 `source='ecdict'` 私有行处理并排校验任务。ECDICT 每次查询都重新打开这个 851 MB 文件，且搜索预览没有服务端限流。你 Mac 上这套部署没有安装 ECDICT。
- **临时词**：既不在种子也不在 ECDICT 时，新建全局私有行（`source='user'`，`is_public=0`，`is_valid_english=NULL`，`created_by_user_id=我`），并入队 `lookup_word`（20 秒去抖，一次 Claude 调用最多 20 个词，提示词里只有词串，没有用户名和备注）。Claude 返回 is_english / headword / phonetic / pos / meaning_zh / definition_en / difficulty / safe_for_sharing。通过则 `is_valid_english=1`、`is_public = safe_for_sharing`、`source='claude'`、只填空字段，再入队 `generate_content`；不通过则 `is_valid_english=0` 永久私有并标「未识别为英文单词」；AI 关闭或任务死亡则标「暂时无法校验」。两个用户添加同一个未知词共享同一行和同一个任务。
- **把临时词转正**：运行时只有 lookup 会写 `is_valid_english=1`；管理员没有接口或命令能做这件事。唯一的非 AI 办法是把这个 lemma 写进种子文件再导入（种子导入会把同名临时行转正）。
- **整理（consolidate_bank）的副作用**：给非种子词填空字段并把 `source` 从 user 改为 claude；给任何词（含种子词）写 `difficulty`；把临时词判为无效；为建议的目标词新建临时行并再入队 lookup。用户「接受」一条整理建议也会写全局表：目标词 `content_state` 置为 queued，没有目标词 id 的拼写建议还会插入新的临时行并排校验任务。

### 1.3 内容层：例句只能由 Claude 生成

**触发点 9 处**，全部汇入去重键 `content:<word_id>`，所以一个词的生成对所有人共享：

| 触发 | 优先级 | 配额 / 门槛 | 位置 |
|---|---|---|---|
| 标为不熟悉（已校验且无内容的词） | 10 / 20 | 无按用户配额 | `services/bank.py:618,640` |
| 构建今日词汇、今天就学、再来一组 | 20 | 批次大小 | `services/batches.py:341-352,639` |
| 03:30 预取明日词 | 30 | 每用户 ≤50；AI 关闭、暂停或当日已花 ≥50% 时跳过 | `jobs/scheduler.py:252-258` |
| 用户点「生成例句」 | 10 | 60 次/天/人；AI 关闭 503；预算耗尽 409 | `routers/words.py:305-331` |
| lookup 校验通过 | 10 | 随 lookup | `ai/lookup.py:487` |
| 整理 / 接受建议 | 20 | 随整理 | `services/suggestions.py:195` |
| 管理员重新生成 / 反馈处理 | 10（force） | 仅 API；不看开关，任务排队等 worker | `routers/admin_ops.py:376-395` |
| 管理员预生成 prewarm | 90 | 见下；AI 关闭或暂停时 503 | `ai/prewarm.py` |

浏览、搜索、导入都不触发。

**版本。** 新版本 = MAX(version)+1，旧行置 `superseded`；已 `ready` 且 prompt_version 相同的词会被跳过，除非任务带 `force`。**提升 PROMPT_VERSION 不会让任何词重新入队**，全库刷新只能逐词 force。`status='rejected'` 在模式里存在但从未被写入。

**预生成 prewarm。** 管理员专用、从不自动；按阶段或全部（全部 = `stage_min IS NOT NULL`，正好覆盖整个种子，但不覆盖用户添加的词）；每个计划 ≤2,000 词、≤$50；每 2 分钟放行 5 × 批量（50 词）。受 prewarm 子预算 $1/天、「当日已花 < 50%」、60 次调用/小时、$3/天、$40/月共同约束。你 Mac 上从未跑过预生成，现有 48 条内容都来自生词库和预取任务。

吞吐与成本（核验 C11 重算）：

| 口径 | 每 10 词一次调用 | 默认设置下每天 | 全库 9,114 个待生成词 |
|---|---|---|---|
| 文档测量值（CLAUDE_INTEGRATION §7） | $0.040，24 秒 | 25 次、250 词，约 37 天 | 约 $37 |
| 你 Mac 账本的 3 次 10 词调用 | 平均 $0.0546，约 30 秒 | 19 次、190 词，约 48 天 | 约 $50，超过 $40 月预算 |

放开日预算后，60 次/小时的上限名义上是 600 词/小时，但被拒的任务会被推迟到下一个整点加 1 分钟，而计数窗口是滚动 60 分钟，实际约 300 词/小时、全库约 30 小时；把 `WD_AI_HOURLY_CALL_CAP` 提到 120 才能做到约 14 小时。prewarm 不用 Openverse，也不画 SVG。

**内容缺失时。** API 返回 `{state, content: null, eta_s, deferred_until}`；卡片用词典释义；none / failed 显示「今天的例句暂时生成不了，先用词典释义学习」加「生成例句」按钮。AI 关闭时 `queued` 的词在第一次 5 秒轮询后会显示「今日 AI 额度已用完，例句将在明天补齐」，这句话在永久关闭时是错的。学习流程不等内容，AI 关闭时批次立即 ready。

**没有的东西。** 写入或编辑内容的接口（整个后端只有三个 PUT/PATCH：settings、account、bank）、内容的导入或导出（CLI 共 22 个子命令，唯一的导入是 `import-seed`，没有任何导出）、人工审核状态。

### 1.4 配图层

来源顺序 wikimedia → openverse（配置了 key 再加 pixabay / pexels），许可白名单（CC0 / 公有领域 / CC BY / CC BY-SA，拒绝 NC / ND），文件按内容哈希存放。Claude SVG 只在无现役配图、词正在被学习、优先级 < 90、`WD_SVG_VIA_CLAUDE=1`、`WD_AI_ENABLED=1` 且 SVG 预算允许时作为最后手段；模板卡片永不失败，所以每个词总有图。

治理上要注意（核验 C13）：「换一张」不会废弃共享配图，只是排除当前图重抓；「不合适」反馈会把该词的**共享**配图置为 rejected 并重抓，阈值是 1，对所有人立即生效。没有现役配图时，这两个用户路径都可能落到 Claude SVG。`/media/images` 只验 cookie 不验可见性；`wd images-prune` 会删除无人学习的词的全部配图行（含 rejected，等于忘记排除记录），没有租约检查。你 Mac 上 31 张图里 30 张是 Claude SVG，这是 11 月 2 日代理故障造成的，不代表真实照片命中率。

### 1.5 管理员今天能做什么、不能做什么

能做（21 个接口加 CLI，全部要求 admin 角色）：概览与健康；用户、邀请、禁用、重置密码、设为管理员；任务重试与重排；AI 暂停 24 小时、恢复、探测；预生成；单词重新生成（仅 API，无按钮）；换图（仅 API）；内容反馈处理（重新生成 / 换图 / 忽略）；事件；只读配置。CLI 另有 `import-seed`、`backup` / `restore`、`fetch-image`、`images-prune`、`consolidate <用户>`、`create-admin` / `promote` 等。

不能做：新建、编辑、隐藏、删除词；编辑或手写内容；通过界面或命令把用户临时词转正（只能走种子文件）；下架一个词（用 SQL 把种子词的 `is_public` 改成 0，也会在下一次种子哈希变化时被导入改回去）；按创建者列出用户添加的词；跨用户查看待校验；导入或导出词与内容；发布「词库版本」（唯一的版本信号是 `kv.seed_version`）；改学习顺序——只能改策略版本（`services/learn_order.py` 的 `LEARN_ORDER_VERSION`）并重算，不能手改 `learn_rank`（`wd check db` 的 `learn_rank_matches_policy` 会报；撒入的无词频词、副词等的键则在下一次重算时被改回）。角色只有 user 和 admin。

管理员对内容的每个操作都回到同一条 Claude 任务管线，而且管理员触发与用户触发共用**一个** AI 开关：没有「只允许管理员用 AI」的模式。唯一绕过开关的是「探测」接口和 `wd claude-check`，它们在 `WD_AI_ENABLED=0` 时照样调用 Claude（每次最多两次、各 $0.05 上限）；`install.sh` 没有 claude 二进制就直接退出，并无条件执行 `claude-check`。

### 1.6 前端如何消费词库

SPA 没有 service worker、没有缓存库，请求带 `cache: 'no-store'`，服务端对 `/api` 全部回 `Cache-Control: no-store`，每次进入页面都重新读服务器，所以服务端的任何改动下一次请求就可见。两个例外：`/media/images` 按哈希不可变缓存一年（换图等于换 URL）；`/media/card/{id}.svg` 浏览器缓存 24 小时，服务端 LRU 的键是（词 id，active_content_id，`words.updated_at`），所以直接用 SQL 改释义而不更新 `updated_at`，卡片会一直是旧的。

选词规则（核验 C10）：词库页列出 `is_public=1` 的行，不要求 `is_valid_english`；筛词与每日推荐词要求 `is_public=1` 且 `is_valid_english=1` 且未合并且命中用户阶段且用户未持有，按阶段距离 → 学习顺序 `learn_rank`（为空排最后）→ 词频 → 字母序。阶段距离按 `stage_min` 计算，`stage_min` 为空的行距离为 11，排在每个用户筛词的**末尾**（不再是第一位；`wd check db` 的 `stage_min_consistent` 会报这种行）；`learn_rank` 由 `services/learn_order.py` 从 `pos`（主词性）、`frq`/`bnc`、`sources`、`stage_min` 派生，服务启动、导种子、每夜维护和 `wd learn-order` 时重算，不能手改。所以管理员在服务端插入词条时必须同时给 `stage_*`、`stage_min`、`frq` 与 `pos`，然后跑 `wd learn-order`（或等下一次启动）。

### 1.7 开关语义：现在的「关闭 AI」是暂停，不是禁止

`WD_AI_ENABLED=0`（改 `.env` 需重启）或 `kv claude.enabled='0'`（只能手工 SQL，没有任何代码写它；管理员点「恢复 AI」会把它写回 `'1'`）的效果（核验 C3，在真实应用上执行）：

- 会：Claude worker 空转；「生成例句」与「立即整理」返回 503；预取、预生成、SVG 入队被跳过；批次立即 ready；`ServerFlags.ai_enabled=false`；排队中的校验词被标「暂时无法校验」。
- 不会：用户添加仍创建临时行并入队 lookup；标不熟悉、构建批次、接受建议仍入队 content；调度器仍每晚为每个有未生成词的用户入队 consolidate；管理员重新生成仍入队；同步排空（`wd worker-once`）只是把任务推迟 30 分钟。16 个入队点里只有 4 个完整地看开关。
- AI 恢复后这些任务全部执行：kv 开关在 worker 下一次 30 秒轮询生效，环境变量需要重启。
- 前端不读 `ai_enabled`，「生成例句」「立即整理」「添加生词」照常显示，点击后才看到「AI 功能暂时关闭」。

### 1.8 你 Mac 上这套库的实际状态（2026-11-04 只读查询）

| 项 | 值 |
|---|---|
| words | 9,162（K-12 发布前的种子；发布后见 `data/seed/stats.json.total_words`），全部 source=seed、公开、有效；用户添加 0；`difficulty` 为空 9,114 |
| word_contents | 48 个词有内容（content-v1，claude-sonnet-5-5） |
| word_images | 31（30 张 Claude SVG，1 张 Wikimedia） |
| content_state | none 9,114 / ready 48 |
| users / user_words / 整理建议 / 反馈 | 1 / 52 / 6 / 0 |
| AI 花费 | 内容 $0.279（9 次成功、12 次 auth 失败），SVG $0.408（33 次），整理 $0.059（3 次成功、3 次失败、12 次因暂停跳过），探测 $0.014 |
| 配置 | WD_AI_ENABLED=1，ECDICT 未安装，种子为仓库默认，注册模式 invite，从未运行预生成 |

---

## 2 问题二：管理员在服务端维护共享词库并共享给所有前端

### 2.1 结论与依据

可行。依据都已核验：

- 共享词库就是服务端的四张全局表，前端无缓存，写入即可见（1.6）。
- 词典层已经有幂等的服务端更新通道，全量导入 0.2 秒，可在服务运行时做（1.2）。
- 内容层接受直接写入（核验 C4，在真实应用上执行）：插入一条 `status='active'` 的 `word_contents`，`content_json` 含全部 14 个键（word、valid、meaning_zh、meaning_en、examples、collocations、mnemonic_zh、image_keywords、image_alt_zh、difficulty、version、prompt_version、model、created_at），把旧的 active 行置 superseded，更新 `words.active_content_id`、`content_state='ready'` 并刷新 `updated_at`，详情、内容接口、今日词汇的学习项、SVG 卡片就全部显示它，不产生任何任务，`ai_calls` 为 0，「生成例句」按钮自动消失。缺键或多键会让这些接口返回 500（包括整个今日页），所以导入器必须复用 `content.validate_item` 并写全 14 个键；`prompt_version` 列要写当前的 `content.PROMPT_VERSION`（`content-v2`），否则残留的普通任务会重新生成并覆盖手工内容。
- 内容的模型与来源字段是自由文本的非空列，`model='human'` 或国产模型 id 都能存，不需要改表。

### 2.2 四档清单

| 档 | 内容 |
|---|---|
| 已有 | 种子导入与自动重导；预生成与逐词重新生成；可见性规则；只读的浏览与搜索；AI 关闭时的降级卡片；按词版本化的内容表；备份 / 恢复 |
| 仅配置 | `WD_AI_ENABLED=0`（暂停层）；`WD_SVG_VIA_CLAUDE=0`；安装 ECDICT；一次性放开预算上限做全库填充；`WD_REGISTRATION_MODE=invite` |
| 小改动 | 策略开关与入队点拦截；启动清理残留 queued；前端按标志隐藏 AI 按钮并改三处文案；`install.sh` 容忍无 claude；「不合适」反馈的阈值；AI 生成标识 |
| 新功能 | 内容包导入导出；国产模型适配器；审核队列与转正、合并、拒绝；下架；最小词库管理页；种子回流；审核员角色；图片上传 |

### 2.3 内容由谁、在哪、用什么凭证和模型生成（关键前提）

这是整个方案里唯一不能靠写代码解决的问题。约束：你的 Claude 登录是公司配发的 Enterprise 席位，不能支撑个人公共产品；你的网络直连 Anthropic 返回 403，说明你本人也在不受支持的地区，地区政策按「使用时所在地」判定，所以「管理员自己在服务器上跑预生成」不成立，哪怕服务器在新加坡。评审还指出支持地区政策有第三条「由不受支持地区的人控制」的判定，这会波及由身在大陆的所有者控制的产品，哪怕 key 是别人的。

| 路径 | 在哪、谁、什么凭证 | 代码量 | 全库填充成本 | 政策面 | 质量 |
|---|---|---|---|---|---|
| B1 国产模型适配器（推荐） | 公共服务器本机，管理员触发，国产厂商 API key（DeepSeek / 通义 / 智谱 / 豆包，OpenAI 兼容接口） | 7–9 人日：provider 抽象、结构化输出转换、价格表计费、错误分类、50 词评测 | 个位数美元 | 彻底不涉及 Anthropic；是将来大陆实时 AI 与「登记」的唯一可走路径 | 未验证，用评测决定模型与 JSON 模式 |
| B2 协作者用 Claude | 身在支持地区的协作者，用其**个人** Console key（不是你的席位）在境外机器跑现有流程，内容打包送到公共服务器 | 0 代码（现有 `claude -p` 流程，key 经 systemd 环境注入） | 约 $37–50 | 依赖「缓存输出给大陆读者可以」这一未经书面确认的推断，且有「控制」判定风险；协作者成为 Anthropic 客户，需给项目一份输出许可 | Sonnet 5.5 已在现有 48 条上验证 |
| B3 人工撰写 | 管理页或内容包，`model='human'` | 随审核队列一起做 | 人力 | 无 | 适合纠错，不适合 9,162 词 |

推荐：B1 为默认，B2 只作为可选的质量补充，而且必须先拿到 Anthropic 的书面答复；两条路产出的内容包格式相同，可按词混用。公共服务器上不放 claude 二进制和任何 Anthropic 凭证，`ai_calls` 表（新增 provider 列）就是审计证据。Mac 上用公司席位生成的 48 条内容和 30 张 SVG 建议重做（成本不到 1 美元）而不是搬到公共库。

### 2.4 推荐方案（综合三套设计与两位评审）

两位评审的综合意见一致：以 D3 的策略与 runner 骨架为主线，先按 D1 的最小路径让服务安全上线，第一个月再补 D2 的审核闭环。

**阶段 A：只读安全模式（8–11 人日，上线前必做）**

- 新增 `WD_AI_POLICY ∈ {live, curated}`（默认 live，开发与测试不变）、`WD_AI_PROVIDER ∈ {claude_cli, openai_http, none}`、`WD_CUSTOM_WORDS ∈ {ecdict_review, ecdict_only}`（curated 下必须显式选择）；`ServerFlags` 增加 `ai_mode`。
- 入队点拦截：`bank.enqueue_content_if_needed` 对用户来源直接返回 None 且不改 `content_state`（覆盖标不熟悉、批次构建、再来一组、接受建议、预取）；`words.resolve` 的临时词、`[网络]` 与 `_ensure_lookup` 分支不再入队 lookup；「生成例句」「立即整理」返回 503，「重试」返回 409；`nightly_consolidation`、`prefetch`、`requeue_dead_once` 直接返回；管理员重新生成、反馈重新生成、探测在没有 provider 时返回 503。
- worker 纵深防御：curated 下 Claude worker 的任务类型表去掉 `consolidate_bank`；content / svg / lookup 的 `select_jobs` 跳过没有 `plan_id`、`force`、`requested`、`actor=admin` 标记的任务。注意去重合并不会改写旧任务的 payload，所以启动清理必须先于任何管理员 AI 操作。
- 启动时与 `wd policy reconcile` 命令：取消排队中的用户来源任务，把没有活任务的 `content_state='queued'` 置回 none，把「暂时无法校验」改写为「待管理员审核」或删除临时行（按 `WD_CUSTOM_WORDS`）。
- 前端：按 `ai_mode` 隐藏「生成例句」「立即整理」「重试」和管理页的预生成 / 探测 / 重新生成；三处文案改为「暂无例句，先用词典释义学习」「词典中未收录，暂时无法添加」或「提交后由管理员审核」「暂无整理建议」；`FRONTEND.md §8` 同步（有测试钉住）。
- 安装：`install.sh` 在 provider 不是 claude_cli 时不要求 claude 二进制、不跑 `claude-check`；`env.example` 与 `DEPLOY.md` 增加 curated 配置段；`word-dance.service` 在无 CLI 时可以开 `ProtectHome`。
- 不变量测试：以 curated 启动，跑完添加 / 导入 / 标记 / 构建 / 再来一组 / 接受建议 / 反馈 / 换图 / 重试 / 调度一轮，断言 Claude 类任务为 0、`content_state='queued'` 为 0，而管理员预生成仍能入队。
- 上线时未知词的处理：若第一周没有人值守审核队列，选 `ecdict_only`（状态 `invalid`，提示「词典中未收录，暂时无法添加」，不建私有行，不改接口契约）；否则 `ecdict_review`。无论哪种都安装 ECDICT，并顺手复核种子里的 4 条「[网络]」词条和考纲拼写错误。

**阶段 B：生成来源与一次性填充（B1 7–9 人日或 B2 0 人日）**

- B1：把 `runner.py` 拆成 `providers/claude_cli.py` 与 `providers/openai_http.py`，共用 `common.claude_call → budget.reserve → ledger` 这条链。评审指出的两个细节：账本行由 `budget.reserve` 预先插入，适配器必须接收 `call_id` 去 `finish_call` 而不是自己插入；五个 JSON schema 需要一层转换（strict json_schema 或 json_object 加提示词内嵌 schema），现有 `validate_item` 仍是真正的门。费用按 usage × 价格表计算并记 `ai_calls.provider`。先用 50 词评测（每阶段 10 词加短语缩写）决定模型与 JSON 模式。
- 填充运行手册：一次性放开 `WD_AI_DAILY_BUDGET_USD`、`WD_AI_MONTHLY_BUDGET_USD`、`WD_AI_PREWARM_DAILY_BUDGET_USD`、`WD_AI_HOURLY_CALL_CAP`（预算先查月再查日，预生成还受「当日已花 < 50%」约束），重启，连续发 5 个 `stage=all, limit=2000` 的预生成计划（或把 2,000 的上限改掉），完成后恢复上限。配图另起一个优先级 90 的回填计划（Wikimedia 每秒 1 次、每天 2,000，约 5 天）。
- B2：协作者在境外机器上用同一代码、个人 Console key（systemd drop-in 注入，`.env` 校验不接受非 WD_ 键）、`WD_AI_MODEL=claude-sonnet-5-5`、`--bare`，按同样参数预生成，内容以内容包交付；上线前那一次也可以直接用 `wd backup --with-images` / `wd restore` 整库交付，但此后不能再整库恢复（会覆盖用户数据），且交付的库里会带着协作者的 `ai_calls` 行。

**阶段 C：运营闭环（13–15 人日，第一个月）**

- 内容包 CLI（4–5 人日）：`wd content-export / content-import / content-wanted`。按 lemma 键控（各机 id 不同）；清单含生成器信息（provider、model、prompt_version、提示词与 schema 哈希、种子哈希）和每个文件的 sha256；导入前逐条 `validate_item`，按内容哈希与图片 sha256 幂等，每 100–200 条一个短事务，只写四张全局表与 kv / system_events，不碰任务表；`--reset-stuck` 与 `--fetch-missing-images`；`kv.content_pack.last` 显示在管理页健康卡旁。
- 预生成 CLI（1 人日）：`wd prewarm --stage any|--lemmas --force [--drain]`，覆盖 `stage_min` 为空的用户贡献词。
- 审核队列（约 6 人日）：新增表 `word_submissions`（输入文本、来源、状态、目标词、审核人、备注，每词一条 pending），管理员通过 / 合并（复用 `lookup.merge_into`）/ 拒绝 / 补全词典字段与阶段词频；决定通过现有的 `attention_msg` 机制反馈给生词库行（「已收录」「已合并到…」「未收录：…」，保留仍为仅收藏）；每用户未决提交上限；公共词条屏蔽词表。
- 下架与最小词库页（约 4.5 人日）：下架用 `is_public=0, is_valid_english=0`（沿用现有可见性判断，避免新增 `hidden_at` 漏掉 `words.is_visible` 的问题）；管理页新增「词库」标签：搜索、来源与状态筛选、下架、审核队列、内容包与版本面板。
- 合规与治理（2–3 人日）：例句、搭配、记忆旁的「AI 生成 · 模型名」标识与推送文本中的标记；注册时记录条款版本与贡献许可；「不合适」反馈改为 N 个不同用户才废弃共享配图；种子回流导出（把审核通过的词写回 `data/seed`）与 `retired.jsonl`（让下架能随种子传播）。

**阶段 D：后续（按需）**

审核员角色（授权表而不是重建 `users.role`）；图片上传（需重建 `word_images.provider` 的 CHECK，并给该路由放开 1 MiB 的请求体上限）；Anthropic Messages / Batch 适配（仅在保留 B2 时）；国产模型下为大陆用户重开实时 AI（需要主体、登记、按用户配额与归因）。

**评审发现、三套设计都遗漏的点（已纳入上面的清单）**

- `wd images-prune` 会删掉内容包带来的配图，且不会再被抓回；curated 下要禁用或让它识别导入来源。
- ECDICT 成为每次添加、导入和搜索预览的关键路径，却是每次调用重新打开 851 MB 文件且无服务端限流，上线前要测延迟并加缓存连接与限流。
- 改种子不会使旧的 AI 内容失效：例句提示词用的是第一行译文与词性，修正释义后要把该词列入下一轮重新生成。
- `content_reports` 记录的是反馈时的内容版本，导入新版本后旧反馈会悬空，需要在导入时自动结案或重新标注。
- 按用户的自添词配额在拒绝或进审核队列的情况下仍然按 token 预扣；待审核行的 3 秒轮询要停掉。
- 「待生成词表」来自大陆学习者的添加需求（只含词头，不含输入原文与备注），走 B2 时应由协作者先过一遍再生成，并在向 Anthropic 书面询问时如实说明。
- 你自己的运维通道（scp 数百 MB 图片包、GitHub、管理页）要穿过 GFW，需要镜像与小包分片。

### 2.5 对大陆侧合规定性的影响（推断，非法律意见）

curated 模式移除的是：Anthropic 的最终用户地区问题（走 B1 完全移除，走 B2 降为「缓存输出」推断）；学习者输入的跨境传输（没有用户文本到达任何模型）；你本人调用 Claude 的地区问题。没有移除的是：PIPL 的告知、同意与未成年人要求；生成内容标识要求（展示给公众的仍是 AI 生成文本，所以要有逐块标识与协议条款）；生成式 AI 办法是否适用于「发布预生成文本」没有豁免条文，正式的登记路径仍要求国产备案模型加一个主体；用户贡献内容的审核义务反而因为有了人工审核而更容易满足；ICP / 公安 / APP 备案只在把主机搬进大陆时出现。这是 B1 优于 B2 的另一个理由：它保留了将来合法走实时 AI 的可能性。

### 2.6 工作量汇总

| 阶段 | 人日 | 备注 |
|---|---|---|
| A 只读安全模式 | 8–11 | 评审把三套设计的 2.5–3.5 人日后端估计上调到含测试与文档的 4 人日左右 |
| B1 国产模型适配器 | 7–9（含评测） | 触及测试最多的 `runner.py`，claude_cli 路径必须保持字节级不变 |
| B2 协作者 Claude | 0 代码，1 人日运维 | 依赖一个人、一份输出许可、一封询问信 |
| C 运营闭环 | 13–15 | 内容包 4–5，预生成 CLI 1，审核队列 6，下架与词库页 4.5 以内，合规治理 2–3 |
| D 后续 | 10–15 | 可选 |
| 合计 | 约 35–45 | 分布在一个季度；前 10 人日后公共服务即安全 |

---

## 3 需要你决定的事

1. **内容由谁生成**：B1 国产模型（推荐，需选厂商并做 50 词评测）还是 B2 身在支持地区的协作者用个人 Console key；若 B2，是否先向 Anthropic 书面确认「缓存输出给大陆读者」。
2. **上线时未知词的处理**：直接拒绝（`ecdict_only`）还是进审核队列（`ecdict_review`）；ECDICT 命中的词是否也要先审再公开。
3. **Mac 上的 48 条内容与 30 张 SVG**：重做（建议）还是搬入公共库。
4. **贡献许可**：学习者添加的词以什么条款进入共享词库，是否回流到仓库种子；注册时的条款文本。
5. **配图策略**：公共服务器现场抓 Wikimedia / Openverse，还是只靠内容包；「不合适」反馈的阈值。
6. **托管地**：新加坡还是东京；是否有朝一日搬进大陆（只有 B1 路径下才可能，且需备案）。
7. **是否成立主体**：这是将来登记和为大陆用户重开实时 AI 的前提。
8. **AI 标识文案与位置**，推送邮件与 webhook 文本是否带标记。
9. **是否保留整理功能的界面**（curated 下它只会空着）。

---

## 4 附录

### 4.1 核验记录

| 编号 | 结论 | 判定 | 关键修正 |
|---|---|---|---|
| C1a/C1b | 种子导入语义与 `--file` 回退陷阱 | 确认（执行） | 陷阱在启动和 `install.sh` 第 6 步都触发；`--force` 会重建词形行；写锁只在解析之后持有 |
| C2 | 你库副本上全量导入耗时 | 确认（执行） | 0.2 秒内，锁内 0.21 秒；无需 `.env`；不检查租约 |
| C3a/C3b | 开关是暂停不是禁止 | 部分（执行） | 开关还会让两个显式接口 503 并跳过预取等；16 个入队点仅 4 个完整受控；SVG 只看环境变量；探测绕过一切 |
| C4a/C4b | 手工写入内容被所有读取路径接受 | 部分（执行） | 必须写全 14 个键且无多余键，否则接口 500；卡片缓存键含 `updated_at`；`validate_item` 可独立复用 |
| C5 | 没有内容写入 / 导入 / 导出路径 | 部分（grep） | `import-seed` 是词典导入器；配图还有 rejected 与 prune 两个写入点 |
| C6 | 公开 / 有效标志的写入者 | 部分（执行） | 种子文件是非 AI 的「发布 + 校验」通道；只有下架没有非 SQL 路径；可见性 SQL 只用在 3 处，其余用 Python 镜像；两处低风险绕过 |
| C7 | 21 个管理接口、共用开关、探测绕过 | 确认（执行） | 暂停下任务会被领取后推迟而不是空转；自动暂停 30 / 15 分钟 |
| C8 | ECDICT 路径不需要 AI | 部分（执行） | 不需要校验但仍排例句任务；`[网络]` 行是 `source='ecdict'`；预览与添加的提示不一致 |
| C9 | 前端无缓存 | 部分（执行） | `/media/card` 的 24 小时缓存与 `updated_at` 键；错误的「明天补齐」文案在第一次轮询后出现 |
| C10 | 选词规则 | 部分（执行） | `/api/stages` 只按 `is_public`；`stage_min` 为空的行排最后（距离 11）；`learn_rank` 为空的行在同距离组内排最后；预生成排除有活任务的词 |
| C11 | 预生成吞吐与成本 | 部分（算术） | 整点推迟使实际吞吐减半；账本实测 $0.0055/词，全库约 $50 |
| C12 | 整理对全局表的写入 | 部分（执行） | 接受建议会写 `words`；夜间入队有条件但实际上几乎每晚触发；原始日志每段截断在 20,000 字符 |
| C13 | 配图治理 | 部分（执行） | 「换一张」不废弃共享图；无现役图时用户路径会落到 Claude SVG；prune 无租约检查 |

### 4.2 方案评审摘要

| 方案 | 工程评审 | 产品与政策评审 | 评价要点 |
|---|---|---|---|
| D1 最小改动 | 43 | 42 | 代码引用最准、估算最诚实（12 人日，评审认为 14–16）；学习者体验最差；把 Claude 作为唯一引擎 |
| D2 管理员工作台 | 46（胜） | 47（并列） | 学习者与贡献者闭环最完整；上线前 28.5 人日被评审上调到 38–42，不应挡在第一个用户前面 |
| D3 模型与合规优先 | 45 | 47（胜） | 对「谁生成、什么凭证、什么模型」给出最可信答案，合规分析最完整；下架实现漏掉 `words.is_visible`，新错误码漏掉错误目录与文档 |

两份综合意见的交集即第 2.4 节。评审修正的事实错误：账本行由 `budget.reserve` 预插入而非 runner；新增错误码需同步 `errors.CATALOGUE`、`API.md` 与客户端提示映射；8 MB 图片上传撞到 1 MiB 的全局请求体上限；D2 的填充时间估算与自身的小时上限不自洽；D1 的 $41–49 是保守上界而非测量值。

### 4.3 证据索引

- `docs/analysis/2026-11-04-library-curation/facts/` — 9 个切片共 312 条带出处的结论；`live-mac-deployment.md` 为你 Mac 部署的只读查询结果
- `docs/analysis/2026-11-04-library-curation/verdicts.txt` — 16 项核验的执行记录、数字与修正
- `docs/analysis/2026-11-04-library-curation/design-D{1,2,3}-*.txt` 与 `judgements.txt` — 三套设计与两位评审的原文
- `docs/PUBLIC_LAUNCH_AND_IOS.md` — Anthropic 政策、地区判定、中国备案与成本的前置分析（2026-11-03）
