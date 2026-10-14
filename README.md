# word-Dance

**word-Dance** 是一款面向中国学习者（学生与职场人士）的英语单词记忆 Web 应用。它内置初中、高中、大学英语四级、六级的全部词汇；把不认识的单词标为「不熟悉」即可进入个人**生词库**；后端借助 **Claude Code** 整理生词库、生成地道例句，并按每个人的设置**每日推送**一组生词，搭配配图与发音辅助记忆。

> **English summary.** word-Dance is a self-hosted English-vocabulary trainer for Chinese learners (UI in Simplified Chinese). It ships the complete junior-high, senior-high, CET-4 and CET-6 word lists (9,162 headwords derived from ECDICT), lets each user mark words as unfamiliar to build a personal word bank, uses Claude Code (the headless `claude` CLI) to consolidate that bank and to generate idiomatic example sentences, and pushes a daily spaced-repetition batch of words, each with an attributed picture, on the user's own schedule. One Python process (FastAPI + SQLite + scheduler + job worker) serves a React single-page app and runs as a systemd unit on Ubuntu.

## 功能概览

- **词库**：初中 / 高中 / 四级 / 六级全部词汇（9,162 词），按阶段浏览，支持 A–Z 索引、按前缀或中文释义搜索、只看本阶段新增的词。
- **生词库**：在任何列表或卡片上把单词标为「不熟悉」即进入个人生词库；也可随时**自添生词**（工作、阅读中遇到的任何英文词，支持批量粘贴和导入）。
- **筛词与推荐词**：快速判断「认识 / 不熟悉」，系统据此了解你的水平，并在每日推送中附上几张推荐词卡片。
- **Claude Code 整理**：后端以无头方式调用 `claude` CLI，校验并规范化自添生词（词形还原、拼写提示、合并重复），夜间整理生词库并把结果放进「整理建议」收件箱，由你决定是否采纳。
- **每日推送**：按你设置的时间与时区，每天生成一组「今日词汇」（复习 + 新词 + 推荐词），以站内学习为准，可选邮件或企业微信 / 飞书 / Server酱 / Bark 通知。
- **记忆算法**：WD-SRS 间隔重复（1 → 3 → 8 → 20 → 51 → 133 → 180 天），评分「不熟悉 / 模糊 / 记住了」；达到建议条件后由你确认「已掌握」，单词即从生词库移出，15 分钟内可撤销。
- **例句与配图**：每个推送的单词都有 AI 生成的地道例句（中英对照）、常用搭配与助记；配图来自 Wikimedia Commons / Openverse 并带版权署名，没有合适照片时退回 AI 示意图或系统生成卡片；发音使用浏览器内置 TTS。
- **记录**：学习热力图、连续学习天数、历史批次回放；数据可导出（CSV / JSON）、导入，账号可自助删除。
- **多用户与管理**：邀请码 / 开放 / 关闭三种注册模式，首个注册的账号自动成为管理员；管理页可查看 AI 花费、任务队列、图片来源命中率，并可一键暂停 AI。

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.12 · FastAPI · uvicorn（单进程）· 标准库 `sqlite3`（WAL）· 手写 SQL 与编号迁移 · Pydantic v2 |
| 前端 | React 19 · TypeScript 5.9 · Vite 8 · react-router 7 · 原生 CSS（移动优先，支持深色模式） |
| AI | Claude Code CLI（`claude -p … --json-schema …`），按词批量调用、全局缓存、每次 / 每日 / 每月预算上限 |
| 图片 | Wikimedia Commons（主）→ Openverse（次）→ 可选 Pixabay / Pexels → Claude 生成 SVG → 系统卡片；全部下载、重编码并由本机提供 |
| 部署 | Ubuntu 24.04 · systemd 系统单元 · 一个数据目录 · 可选 Caddy / nginx 反向代理 |

设计细节见 [`docs/DESIGN.md`](docs/DESIGN.md)。

## 快速开始（开发）

环境要求：Linux（目标为 Ubuntu 24.04），Python 3.12（含 `python3-venv`），Node 22 与 npm 10，GNU make。开发模式默认使用仓库内的假 `claude`（`backend/tests/fake_claude.py`），不花钱、不联网；要使用真实的 Claude Code，请先在本机登录 `claude` CLI，再以 `WD_DEV_REAL_CLAUDE=1 make dev` 启动。

```bash
make setup   # 创建 .venv，安装后端依赖并以可编辑方式安装 wd 包，frontend 执行 npm ci
make dev     # 后端 uvicorn --reload :8000（数据目录 ./.dev-data，开放注册）+ 前端 Vite :5173（代理 /api 与 /media）
make test    # pytest + tsc + vitest + vite build
```

打开 <http://localhost:5173>，注册的第一个账号即为管理员。`make help` 列出全部目标（`build`、`smoke`、`seed`、`install`、`backup`、`check`、`clean`）。

## 部署

生产部署（`deploy/install.sh`、systemd 单元、`.env` 配置、备份与恢复、反向代理与 HTTPS、升级与回滚）以及界面截图：**见 [`docs/DEPLOY.md`](docs/DEPLOY.md)**。

## 仓库结构

| 路径 | 说明 |
|---|---|
| `backend/` | FastAPI 后端：`wd` 包（API 路由、服务层、SQLite 迁移、任务队列与调度、Claude 与图片管线、`wd` 命令行）及 pytest 测试 |
| `frontend/` | React + TypeScript 单页应用（Vite）；构建产物 `frontend/dist` 由后端直接提供 |
| `data/` | 随仓库分发的压缩词汇种子 `seed/vocab.jsonl.gz`（9,162 词）、统计 `seed/stats.json`、数据来源说明与 ECDICT 许可证文本 |
| `scripts/` | 维护脚本：`build_seed.py`（从 ECDICT 与大纲词表重建种子）、`smoke.py`（端到端冒烟测试）、`dev.sh` |
| `deploy/` | 安装脚本、systemd 单元与定时备份、`env.example`、Caddy / nginx 示例配置 |
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
| [`docs/DEPLOY.md`](docs/DEPLOY.md) | 安装脚本、systemd、环境变量、数据目录、备份、日志、反向代理、开发流程、CLI 参考 |
| [`docs/TASKS.md`](docs/TASKS.md) | 实现工作包：文件归属、依赖关系、验收标准 |

## 数据来源与许可

- **词汇种子** [`data/seed/vocab.jsonl.gz`](data/seed/vocab.jsonl.gz)（9,162 词；按阶段累计：初中 2,099 · 高中 3,829 · 四级 4,722 · 六级 7,671）由 [ECDICT](https://github.com/skywind3000/ECDICT)（MIT 许可，全文见 [`data/licenses/ECDICT-LICENSE`](data/licenses/ECDICT-LICENSE)）派生：音标、释义、词频与词形变化均来自 ECDICT；各阶段归属由 ECDICT 的考试标签与 [mahavivo/english-wordlists](https://github.com/mahavivo/english-wordlists) 整理的中考 / 高考 / 四六级大纲词表共同决定（仅使用「某词是否在某词表中」这一事实，不分发任何词表文件）。重建方法：`make seed`（`scripts/build_seed.py`）；字段说明见 [`data/seed/ATTRIBUTION.md`](data/seed/ATTRIBUTION.md)。
- **配图** 来自 Wikimedia Commons 与 Openverse（仅接受 CC0 / 公有领域 / CC BY / CC BY-SA），每张图片下方显示标题、作者、许可证并链接到来源页；AI 示意图与系统生成卡片不含第三方素材。
- **例句、搭配与助记** 由 Claude（Claude Code CLI）生成，界面有「例句由 AI 生成」提示；Claude Code 需由运维者自行安装并登录，不随本仓库分发。

完整说明见 [`ATTRIBUTION.md`](ATTRIBUTION.md)。

## 许可证

word-Dance 以 [MIT 许可证](LICENSE) 发布（Copyright (c) 2026 word-Dance contributors）。第三方数据与服务以其各自的许可和条款为准，见 [`ATTRIBUTION.md`](ATTRIBUTION.md)。
