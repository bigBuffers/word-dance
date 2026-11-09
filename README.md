# word-Dance

**word-Dance** 是一款面向中国学习者（学生与职场人士）的英语单词记忆 Web 应用。它内置小学（义务教育课标二级词汇）、初中、高中、大学英语四级、六级的全部官方词表词汇；把不认识的单词标为「不熟悉」即可进入个人**生词库**；后端借助 **Claude Code** 整理生词库、生成地道例句，并按每个人的设置**每日推送**一组生词，搭配配图与发音辅助记忆。

> **English summary.** word-Dance is a self-hosted English-vocabulary trainer for Chinese learners (UI in Simplified Chinese). It ships the complete primary-school (MOE 2022 Level 2), junior-high (MOE 2022 Level 3 + the Shanghai 2020 list), senior-high (MOE 2020/2025 revisions) and CET-4 / CET-6 word lists (head-word counts in `data/seed/stats.json`; dictionary fields from ECDICT), lets each user mark words as unfamiliar to build a personal word bank, uses Claude Code (the headless `claude` CLI) to consolidate that bank and to generate idiomatic example sentences, and pushes a daily spaced-repetition batch of words, each with an attributed picture, on the user's own schedule. One Python process (FastAPI + SQLite + scheduler + job worker) serves a React single-page app and runs as a systemd unit on Ubuntu.

## 功能概览

- **词库**：小学 / 初中 / 高中 / 四级 / 六级全部官方词表词汇（词数见 `data/seed/stats.json`），按阶段浏览，支持 A–Z 索引、按前缀或中文释义搜索、只看本阶段新增的词；掉出所有官方词表的「课标外」词只在「全部」页签与搜索中出现。
- **生词库**：在任何列表或卡片上把单词标为「不熟悉」即进入个人生词库；也可随时**自添生词**（工作、阅读中遇到的任何英文词，支持批量粘贴和导入）。
- **筛词与推荐词**：快速判断「认识 / 不熟悉」，系统据此了解你的水平，并在每日推送中附上几张推荐词卡片。
- **Claude Code 整理**：后端以无头方式调用 `claude` CLI，校验并规范化自添生词（词形还原、拼写提示、合并重复），夜间整理生词库并把结果放进「整理建议」收件箱，由你决定是否采纳。
- **每日推送**：按你设置的时间与时区，每天生成一组「今日词汇」（复习 + 新词 + 推荐词），以站内学习为准，可选邮件或企业微信 / 飞书 / Server酱 / Bark 通知。
- **记忆算法**：WD-SRS 间隔重复（1 → 3 → 8 → 20 → 51 → 133 → 180 天），评分「不熟悉 / 模糊 / 记住了」；达到建议条件后由你确认「已掌握」，单词即从生词库移出，15 分钟内可撤销。
- **例句与配图**：每个推送的单词都有 AI 生成的地道例句（中英对照）、常用搭配与助记；配图来自 Wikimedia Commons / Openverse 并带版权署名，没有合适照片时退回 AI 示意图或系统生成卡片；发音用浏览器 / 系统语音，没有英文语音的设备（如鸿蒙平板里的 App）由服务器生成发音。
- **记录**：学习热力图、连续学习天数、历史批次回放；数据可导出（CSV / JSON）、导入，账号可自助删除。
- **多用户与管理**：邀请码 / 开放 / 关闭三种注册模式，首个注册的账号自动成为管理员；管理页可查看 AI 花费、任务队列、图片来源命中率，并可一键暂停 AI。

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.12 · FastAPI · uvicorn（单进程）· 标准库 `sqlite3`（WAL）· 手写 SQL 与编号迁移 · Pydantic v2 |
| 前端 | React 19 · TypeScript 5.9 · Vite 8 · react-router 7 · 原生 CSS（移动优先，支持深色模式） |
| AI | Claude Code CLI（`claude -p … --json-schema …`），按词批量调用、全局缓存、每次 / 每日 / 每月预算上限 |
| 图片 | Wikimedia Commons（主）→ Openverse（次）→ 可选 Pixabay / Pexels → Claude 生成 SVG → 系统卡片；全部下载、重编码并由本机提供 |
| 部署 | Ubuntu 24.04 · systemd 系统单元 · 一个数据目录 · 每夜自动备份 · 可选 Caddy / nginx 反向代理 |

设计细节见 [`docs/DESIGN.md`](docs/DESIGN.md)。

## 快速开始（开发）

环境要求：Linux（目标为 Ubuntu 24.04），Python 3.12（含 `python3-venv`），Node 22 与 npm 10，GNU make。开发模式默认使用仓库内的假 `claude`（`backend/tests/fake_claude.py`），不花钱、不联网；要使用真实的 Claude Code，请先在本机登录 `claude` CLI，再以 `WD_DEV_REAL_CLAUDE=1 make dev` 启动。

```bash
make setup   # 创建 .venv，安装后端依赖并以可编辑方式安装 wd 包，frontend 执行 npm ci
make dev     # scripts/dev.sh：后端 uvicorn --reload :8000（数据目录 ./.dev-data，开放注册）+ 前端 Vite :5173（代理 /api 与 /media）
make test    # pytest + 契约审计（scripts/check_contract.py：schemas.py ↔ types.ts 逐字段比对）+ tsc + vitest + vite build
make smoke   # scripts/smoke.py：在临时数据目录、端口 8010 上启动一次性实例，用假 claude 与模拟图片源走完整个产品流程
```

打开 <http://localhost:5173>，注册的第一个账号即为管理员。`make help` 列出全部目标（`build`、`smoke`、`seed`、`install`、`backup`、`check`、`check-contract`、`clean`）。

## 部署（生产，Ubuntu 24.04）

一台机器、一个数据目录、一个 systemd 系统单元；运行用户必须是已登录 `claude` CLI 的那个用户（本机为 `sqin`）。

```bash
git clone <repo> /home/sqin/word-Dance && cd /home/sqin/word-Dance
deploy/install.sh                                   # 局域网部署：绑定 0.0.0.0:8000，打印 http://<LAN-ip>:8000
deploy/install.sh --with-caddy words.example.com    # 公网域名 + 自动 HTTPS（或 --with-nginx DOMAIN）
deploy/install.sh --with-ecdict                     # 可选：下载完整 ECDICT 词典（216 MB → 851 MB），用于种子之外单词的即时查询
deploy/install.sh --dry-run                         # 只打印将要执行的步骤（每行以 + 开头），不做任何更改
deploy/install.sh --contact-email you@example.com   # 写入 WD_CONTACT_EMAIL：Wikimedia API 政策要求 User-Agent 附带联系邮箱（默认 admin@localhost，也可在 .env 中设置）
```

`install.sh` 是幂等的：预检（Python 3.12、Node ≥ 22、`claude` 在 PATH 中、磁盘空间）→ 创建数据目录 `/home/sqin/word-dance-data`（0700）→ venv 与依赖 → 构建前端 → 首次生成 `.env`（0600，随机 `WD_SECRET_KEY`，之后永不覆盖）→ **停止运行中的服务** → `wd migrate`（先写 pre-migrate 快照）→ `wd import-seed` → `wd claude-check`（一次 ≤ $0.05 的探测调用）→ `wd create-admin --if-none` → 安装 `word-dance.service` 与 `word-dance-backup.timer` → 启动 → 健康检查。升级只需 `git pull && deploy/install.sh`（或 `make install`）。

打开打印出的地址，**第一个注册的账号自动成为管理员**（无需邀请码）；之后在管理页或用 `.venv/bin/wd invite --uses 5 --days 7` 生成邀请码。配置都在 `/home/sqin/word-dance-data/.env`（每行 `KEY="value"`，模板与说明见 [`deploy/env.example`](deploy/env.example)），修改后 `sudo systemctl restart word-dance`。

常用运维命令：

```bash
systemctl status word-dance && journalctl -u word-dance -f          # 状态与 JSON 日志
.venv/bin/wd backup --keep-daily 14 --keep-weekly 8                 # 手动备份（定时器每天 03:30 Asia/Shanghai 自动执行）
sudo systemctl stop word-dance && .venv/bin/wd restore /home/sqin/word-dance-data/backups/<file>.db.gz --yes && sudo systemctl start word-dance
.venv/bin/wd check all                                              # db · claude · smtp · providers 自检
```

完整说明：安装脚本、systemd 单元、全部环境变量、数据目录、日志、反向代理、升级与回滚见 [`docs/DEPLOY.md`](docs/DEPLOY.md)；日常运维、备份与恢复演练、故障处理手册见 [`docs/ops.md`](docs/ops.md)；手工验收清单见 [`docs/qa.md`](docs/qa.md)。

## 仓库结构

| 路径 | 说明 |
|---|---|
| `backend/` | FastAPI 后端：`wd` 包（API 路由、服务层、SQLite 迁移、任务队列与调度、Claude 与图片管线、备份、`wd` 命令行）及 pytest 测试 |
| `frontend/` | React + TypeScript 单页应用（Vite）；构建产物由后端直接提供——开发时为 `frontend/dist`，安装后由 `deploy/install.sh` 构建到数据目录的版本化快照 `frontend-releases/<sha>` 并以符号链接 `frontend` 原子发布，仓库内的构建不会影响线上页面 |
| `mobile/` | Capacitor 远程壳：Android / iOS 原生工程、离线页模板 `templates/index.html` 与钩子脚本 `scripts/prepare.mjs`、图标源 `resources/`、阿里云镜像 init 脚本；签名密钥与构建产物不入库（`docs/MOBILE_APP.md`） |
| `data/` | 官方词表词头清单与构建器元数据 `lists/`（来源说明、`manifest.json`、别名表、人工释义表、校验和）；随仓库分发的压缩词汇种子 `seed/vocab.jsonl.gz`（记录数与各阶段词数见 `seed/stats.json`）、与上一版的差异 `seed/DIFF.md`、数据来源说明与 ECDICT 许可证文本 |
| `scripts/` | `build_seed.py` / `seed_diff.py`（`backend/wd/seedbuild` 的入口：从 ECDICT 与 `data/lists/` 官方词表重建种子并生成差异报告，`make seed`）、`pack_seed.sh`、`rehearse_migration.py`（在数据库拷贝上排练待办迁移并核对结果）、`check_contract.py`、`smoke.py`（端到端冒烟测试）、`dev.sh`（开发服务器） |
| `deploy/` | `install.sh`、`fetch_ecdict.sh`、systemd 单元（服务 + 每夜备份定时器）、`env.example`、Caddy / nginx 示例配置 |
| `docs/` | 设计与契约文档（见下）、运维手册与手工验收清单 |
| `Makefile` | 开发与运维入口（`make help`） |
| `README.md` · `LICENSE` · `ATTRIBUTION.md` | 本文件、MIT 许可证、第三方数据与服务的来源与许可说明 |

运行时状态（数据库、图片缓存、`.env`、备份）全部位于仓库之外的数据目录 `WD_DATA_DIR`（默认 `/home/sqin/word-dance-data`），`git pull` 与 `git clean` 永远不会触及它。

## 文档

| 文档 | 内容 |
|---|---|
| [`docs/DESIGN.md`](docs/DESIGN.md) | 架构总览：技术栈、数据模型、生词库状态机、自添生词处理、每日推送与调度、WD-SRS、图片管线、安全与隐私、决策记录 |
| [`docs/SCHEMA.sql`](docs/SCHEMA.sql) | 完整的 SQLite DDL（与 `backend/wd/migrations/0001_init.sql` 逐字节一致） |
| [`docs/API.md`](docs/API.md) | 全部 HTTP 接口、错误信封与共享 TypeScript 类型（= `frontend/src/api/types.ts`） |
| [`docs/CLAUDE_INTEGRATION.md`](docs/CLAUDE_INTEGRATION.md) | `claude` CLI 的精确调用方式、提示词、JSON Schema、批处理、预算与失败处理、整理规则 |
| [`docs/FRONTEND.md`](docs/FRONTEND.md) | 路由、页面、组件、状态、交互、响应式规则与全部中文文案 |
| [`docs/MOBILE_APP.md`](docs/MOBILE_APP.md) | iOS / Android 壳（`mobile/`，Capacitor 远程壳）：开发环境、构建、TestFlight / App Store / Google Play / 国内商店的上架步骤 |
| [`docs/DEPLOY.md`](docs/DEPLOY.md) | 安装脚本、systemd、环境变量、数据目录、备份、日志、反向代理、开发流程、CLI 参考 |
| [`docs/ops.md`](docs/ops.md) | 运维手册：日常检查、备份与恢复、升级与回滚、配置修改、故障处理表 |
| [`docs/qa.md`](docs/qa.md) | 手工验收索引：部署验收、真实 Claude 验收、推送渠道检查；链接前端 / 学习流程清单 `qa-frontend.md`、`qa-study.md` |
| [`docs/TASKS.md`](docs/TASKS.md) · [`docs/P0_STATUS.md`](docs/P0_STATUS.md) | 实现工作包（文件归属、依赖关系、验收标准）与 Phase 0 验证记录 |
| [`docs/releases/`](docs/releases/) | 发布说明，每次发布一份（有无迁移都有）：[`2026-11-k12-stages.md`](docs/releases/2026-11-k12-stages.md)——小学阶段与官方词表、阶段重编号、配图一期的变更、上线步骤、回滚与假设清单；[`2026-11-server-audio.md`](docs/releases/2026-11-server-audio.md)——服务器发音兜底（`GET /media/audio`，没有英文语音的设备也能出声） |

## 数据来源与许可

- **词汇种子** [`data/seed/vocab.jsonl.gz`](data/seed/vocab.jsonl.gz)（记录数与各阶段词数见 [`data/seed/stats.json`](data/seed/stats.json)）：音标、释义、词频与词形变化来自 [ECDICT](https://github.com/skywind3000/ECDICT)（MIT 许可，全文见 [`data/licenses/ECDICT-LICENSE`](data/licenses/ECDICT-LICENSE)）；小学 / 初中 / 高中的归属只取自官方文件的**词头**——教育部《义务教育英语课程标准（2022 年版）》附录 3 二级、三级词汇表与附表，上海市教育考试院 2020 年初中英语词汇表（含词组），《普通高中英语课程标准》2020 年修订与 2025 年修订附录 2 词汇表（词头清单、来源、校验值与解析规则见 [`data/lists/README.md`](data/lists/README.md)；原件未声明许可，本仓库不收录其释义、音标与版式）；四级 / 六级归属沿用 ECDICT 的考试标签与 [mahavivo/english-wordlists](https://github.com/mahavivo/english-wordlists) 的四六级词表（可选输入，仅使用「某词是否在某词表中」这一事实，不分发词表文件）。重建方法：`make seed`（`backend/wd/seedbuild/`，入口 `scripts/build_seed.py`）；字段与来源令牌说明见 [`data/seed/ATTRIBUTION.md`](data/seed/ATTRIBUTION.md)。
- **配图** 来自 Wikimedia Commons 与 Openverse（仅接受 CC0 / 公有领域 / CC BY / CC BY-SA），每张图片下方显示标题、作者、许可证并链接到来源页；AI 示意图与系统生成卡片不含第三方素材。
- **例句、搭配与助记** 由 Claude（Claude Code CLI）生成，界面有「例句由 AI 生成」提示；Claude Code 需由运维者自行安装并登录，不随本仓库分发。

完整说明见 [`ATTRIBUTION.md`](ATTRIBUTION.md)。

## 许可证

word-Dance 以 [MIT 许可证](LICENSE) 发布（Copyright (c) 2026 word-Dance contributors）。第三方数据与服务以其各自的许可和条款为准，见 [`ATTRIBUTION.md`](ATTRIBUTION.md)。
