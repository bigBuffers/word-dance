# 发布说明 · 2026-11 · 单词之舞 P3 第二批（规则层 -er 后缀切分 · `word_dances.corrected` · 迁移 0017，加列不停机）

基线 `main @ 83cc919`（P3 第一批已上线，schema 16）；本次发布 = 规则层学会把派生的 -er 词切在词干之后（work·er、farm·er、low·er），并让已存的标注只在模型「真改过」切块时才覆盖规则层（`word_dances.corrected`）。设计记录：`docs/WORD_DANCE_DESIGN.md` §13；接口字段说明：`docs/API.md` §9.1 `dance`；管线：`docs/CLAUDE_INTEGRATION.md` §6.8。

迁移文件：`0017_word_dances_corrected.sql` —— `word_dances` 加一列 `corrected INTEGER CHECK (0/1)`（可空），不回填（全部 NULL，由下一次服务启动的 `backfill_corrected` 逐行算出）；不重建任何表，`deploy/install.sh --no-restart` 或 Mac 上的 `launchctl kickstart -k` 都可以。前端无改动（`types.ts` 只改了两行注释——接口头注释和 `source` 的注释——和 API.md §9 逐字一致），不需要重建前端快照。

## 1 变更概览

- **规则层**（`backend/wd/dance.py`）：新函数 `er_evidence(word, stem)`（纯函数：词干拼写正是去掉 -er 的全小写词、音标拼得上、词干是实词、有派生证据且词性相符四条）、`er_stem(conn, word)`（查词库一次，只认公开、有效、未合并的词干）、`rule_spec(conn, word)`（= `spec_for` 加词干提示）；`spec_for(display, phonetic, er_stem=None)` 有提示时把词干按普通规则切再加 `er` 一块，提示不能套用（音标拼不上、音节数对不上）就回到普通切法。全库 65 个词命中（`backend/tests/fixtures/dance_er_splits.json`）。
- **存储与服务**：`store_spec(..., corrected=)` 写新列；`active_record` 返回 `(spec, corrected)`；`spec_for_word` = 当前规则 spec 叠加已存标注的语义动作，切块 / 重音只在 `corrected = 1` 时用模型的；`backfill_corrected(conn)` 在启动时补 NULL 行。标注器（`wd/ai/dance.py`）给模型的建议改为 `rule_spec`，并把 `corrected` 写进行。
- **不变**：提示词（dance-v2）、入队与预算、前端播放、`DanceSpec` 契约字段（`source` 的注释更新）。

## 2 机制要点

- 为什么不再喂一次模型：提示词第 1 条要求「除非明显错误否则保留规则层建议」，11-09 00:05 的强制重标证明模型会原样保留 wor·ker；机械切分属于规则层。
- 为什么加列：已存标注里 580 / 592 个小学词的切块是模型「确认」的规则输出，不加标记就无法区分「模型改过」和「规则当时就这样」，规则层改进也就永远到不了这些词。
- 保守默认：`corrected` 为 NULL（回填尚未运行）时按「模型改过」处理，服务端继续用存的切块。
- 重音按模型实际收到的建议比较：规则层给不出重音（整词一块、音节数对不上）时发给模型的是 `rule_stress: 0`，模型原样回答算「确认」而不是「改过」（`wd.dance.suggested_stress`，标注器和回填共用）。
- 标记永远是规则层的：模型改过切块的词也只保留它的切块和重音，哑音 / 双写标记用当前规则算；-er 切分的哑音标记取词干自己的加整词模式（lis·ten·er 标 t，不标 ten 的 e）。

## 3 验收

- `make test`（新增 `test_db_0017`、`test_main_dance_corrected`；`test_dance` 加 -er 金表、`er_evidence`、`er_stem`、全量种子夹具；`test_dance_annotate` 加建议 / 存储 / 合并 / 回填；`test_db_0016` 的列清单加 `corrected`）、`scripts/check_contract.py`、`test_docs_contract`（API.md §9 与 types.ts）、前端 `tsc` / lint / vitest 不变。
- 在数据库副本上 `scripts/rehearse_migration.py`：0017 套用（只加列，全部 NULL），脚本随即在副本上跑 `backfill_corrected`（新增的 `check_0017`：637 行里 13 行 = 1、624 行 = 0、NULL 0 行，重跑为 0）；服务端逐词比对见 §6。

## 4 上线步骤（Mac launchd；加列迁移，约 3 秒）

0. 本机测试全绿；`VACUUM INTO` 复制数据库到私有目录并彩排 0017。
1. `git pull`（或已在工作区）；前端快照不动（仍是 `frontend-releases/bb2d1b5`）。
2. `launchctl kickstart -k gui/$(id -u)/com.word-dance.server`：新进程启动时套用 0017（先写 `backups/pre-migrate-16-to-17.db.gz`），随即 `backfill_corrected` 逐行算出 `corrected`（第一次启动填全部行，日志 `word_dances.corrected backfilled for N row(s)`；之后的启动为 0 行、无日志）。
3. `curl --noproxy '*' http://127.0.0.1:8000/api/health`；只读查 `SELECT corrected, COUNT(*) FROM word_dances GROUP BY corrected`；`GET /api/words/{id}` 看 worker 的 `dance.letters` 为 `["work","er"]`、`source` 仍为 `claude`、`semantic` 不变。

## 5 回滚

`git checkout 83cc919` 并重启即可：旧代码的 INSERT 指名列，不读 `corrected`，可空列不需要默认值；不必恢复快照。回滚后 worker / farmer 又显示 wor·ker / far·mer（存的 spec 没改），其余 45 个规则词回到旧切法。

## 6 上线记录

- 评审：对抗式评审 `review-word-dance-p3b`（5 个视角 × 每条 3 个反驳者，74 个 agent）确认 20 条（去重 16 条），全部修掉——其中两条影响行为：`corrected` 在「规则层只给一块、重音为空」的词上把模型的原样回答误判为改过（提示词发的是 `rule_stress: 0`，比较却拿 None），改为按 `suggested_stress` 比较；-er 切分的哑音标记沿用了被否掉的普通切法（lis·ten·er 把 ten 的 e 标成哑音），改为词干标记加整词模式。顺带把 0017 简化成只加列、回填全部交给启动时的 `backfill_corrected`，并给彩排脚本加了 `check_0017`。验证评审 `verify-word-dance-p3b-fixes`（16 个验证者 + 3 个新视角，20 个 agent）确认 16 条全部修复，余下只有注释和文档措辞，已一并改掉。
- 门禁：后端 2202 通过（失败的 21 个全是环境相关：`test_config` 的 Mac 专属用例、20 个 Linux 部署脚本用例因这台 Mac 新增了 `/sbin/sha256sum` 不再跳过而败在 BSD `df`），HEAD 与工作区的纯规则层在全部 9618 个种子词上 `spec_for` / `silent_letters` 零差异，契约审计、`test_docs_contract`、前端 tsc / lint / 364 条 vitest 通过；数据库副本彩排 71 项检查通过。
- 11-09 14:40 `20dc00e` 上线（后端重启，前端快照仍为 `frontend-releases/bb2d1b5`）：启动时写快照 `backups/pre-migrate-16-to-17.db.gz`，套用 0017，`word_dances.corrected backfilled for 637 row(s)`（624 行 = 0、13 行 = 1），3 秒内健康；`jobs` 2940 / `ai_calls` 892 / `word_dances` 637 行数不变，integrity ok。
- 抽查（服务端 `spec_for_word`）：worker → work·er、farmer → farm·er（source 仍为 claude，语义动作仍为无）、teacher → teach·er、sweater → sweat·er；jump / on 仍为 hop / onto。
- 审核页按服务端切法重建并发布到原链接（卡片显示的切块 = 卡片实际播放的切块；橙边 = 模型改过规则建议的 12 个小学词）。
