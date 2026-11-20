# 发布说明 · 2026-11 · 跳动图卡（后端 + 前端，无迁移）

基线 `main @ d865321`；本次发布 = 提交 `cae93ef`。状态：**已上线**（2026-11-20 14:25，这台 Mac，前端快照 `frontend-releases/cae93ef`，服务重启约 1 秒；46 张图卡 14:27 导入，见第 4 节）。
起因：2026-11-20 sqin：「单词图片生成耗费的 token 过大……是否可以生成更加简洁的图片，结合单词跳动主题，帮助记忆」→ 看过六词样例后「可以，按照这个做」「上限 100，开始做」。

## 1 是什么

一张**一次调用画成的简笔画**（和小学 600 张同一条管线），加三样由程序完成的东西：

| 部分 | 谁做 | 说明 |
|---|---|---|
| 画面 | 模型（`svg_system.txt`，`svg-v3`） | 只画一个主体；画布最下面五分之一（y 400–500）留成一条空地面；会动的那一部分包在唯一的 `<g id="actor">` 里 |
| 动作 | 模型**点名**，前端播放 | `motion` 只能取 `none hop rise fall shiver sway spin pulse grow shrink dash float` 之一；关键帧只在 `frontend/src/components/study/dancingMotions.ts`，图片文件里没有任何动画 |
| 单词 | 前端 | 印在地面上，每个字母一个 `<text>`，字体 WD Letters（Andika Bold 的子集）；字母依次入场 → 整词一拍 → 主体和单词做同一个动作 |
| 拼写钩子 | 模型点名，服务器校验 | `highlight`（单词里的一段字母，如 hear 的 ear）亮起来；`hook_zh` 一句提示，进「记忆」区（沿用 `word_images.hook_zh`） |

服务器在存图时把校验过的选择写进文件：`<desc id="wd-stage">{"v":1,"motion":…,"highlight":…}</desc>`（`images/dancing.py`）。没有恰好一个 actor、或动作不在表里 → 记为 `none`，图就是一张不动的画。识别规则：`provider = 'claude_svg'` 且 `prompt_version` 以 `svg-v3` 开头 → `ImageMeta.dancing = true`。**没有迁移**，没有新表新列。

契约：`docs/API.md` §9 `ImageMeta.dancing`、§9.1；`docs/CLAUDE_INTEGRATION.md` §4.4（`svg_v1.json` 多了三个可选字段）、§5.5（提示词）；`docs/FRONTEND.md` §4。

行为细节：
- 「单词之舞」设为「关」或系统开了减弱动态 → 图和单词都不动；「只拼读」→ 只有字母入场。
- 「图片上显示单词」关掉 → 地面上不印单词，主体照样动。
- 图读不出来（网络、旧浏览器）→ 退回普通 `<img>`，和以前的简笔画一样。
- 以前的简笔画（`svg-v2`）、记忆图卡（`memo-1`）、照片都不变。今后新画的图（包括学习时自动补画的）都是 `svg-v3`。

## 2 试画（2026-11-20，Sonnet 5.5，每词一次调用，不写线上库）

| 词 | 费用 | 动作 | 钩子 | 我看到的 |
|---|---|---|---|---|
| jump | $0.021 | hop | — | 可用；小人画成了已经起跳的姿势 |
| rain | $0.023 | fall | — | 可用 |
| up（第一次） | $0.013 | rise | up 像箭头指向天空 | **箭头画成了朝下** → 提示词加了「y 向下增长，画完对一遍方向」后重画 |
| up（重画） | $0.021 | rise | 同上 | 见试画页 |
| hear | $0.016 | none | hear 里藏着 ear：用耳朵听 | 可用，ear 高亮 |
| cold | $0.017 | shiver | — | 可用 |
| book | $0.012 | none | 两个 o 像一双眼睛 | 可用，oo 高亮 |

七次调用共 $0.12，平均 $0.018 一张。**一次画成、没人看过的图会出错（7 张里 1 张方向反了）**，所以其余词的流程是：先画到临时目录 → 逐张看 → 重画有问题的 → 再导入。

## 3 验收

- 后端 pytest：3134 通过；21 个失败是这台 Mac 上一向如此的（`test_deploy_files.py` 20 个、`test_config.py::test_defaults_without_environment`）。新增 `tests/unit/test_dancing.py`、`test_images.py` 两处。`scripts/check_contract.py` 通过。
- 前端：typecheck、lint、vitest 70 个文件 716 个用例（新增 `DancingPicture.test.tsx` 8 个）。
- 真实链路：线上库的临时副本 + 不带后台线程的实例（127.0.0.1:8011），把 6 张试画存进副本，用无头 Chrome 打开六个单词的详情页：图内联显示、字体加载、动画在跑、hear / book 的提示出现在「记忆」区、没有脚本报错。副本和实例事后已删除。
- 没有覆盖到的：真机和平板上的流畅度；学习卡翻面时的观感（卡片顶上的单词也会做它的语义舞，两处先后在动）；深色模式下的图卡（图本身是浅色的）。

## 4 上线记录（2026-11-20，sqin：「上线」）

1. 其余 44 个词按第 2 节的流程画到 `studio/tmp/dancing-pilot/`（43 次调用 + `place` 重画一次，约 $0.67），逐张看过。整理：`mother`、`now` 的动作改为不动（标出的活动部分是头 / 一根表针）；`keep`、`kind`、`head`、`month` 的提示句太牵强，去掉。sqin 看过 46 张的页面后回复「上线」。
2. `cae93ef` 提交在 `main`（未推送）。上线前没有正在执行的任务；数据库备份 `backups/pre-dancing-cards-20261120-1425.db.gz`。
3. 14:25:58 切换前端快照并 `launchctl kickstart -k`，14:25:59 健康检查通过（`frontend.prev` = `frontend-releases/969d1df`，三个安装包原样带过去）。
4. 14:27 用 `store.activate_svg(..., prompt_version='svg-v3', stage=…)` 导入 46 张（44 个词 + jump、cold；rain、up、book 已有记忆图卡，不替换）：46 行 `svg-v3` 生效、13 张带提示句、66 张记忆图卡不变。每个词换下的旧图和新图的 id 记在 `backups/dancing-import-20261120.json`（旧图是 `superseded`，文件还在）。
5. 上线后核对：健康检查 200；首页入口文件、`WordImage-*.js`（含新的图卡代码）、字体 `wd-letters-bold-*.woff`、学习页和详情页的文件都能取到；日志没有报错。没有做的：用 sqin 的登录态在线上打开页面；平板和真机。

## 5 回滚（未执行）

只退显示（图卡变回不动的简笔画，图本身留着）——前端指回上一个快照并重启：

```sh
D=/Users/sqin/word-dance-data; PREV=frontend-releases/969d1df
test -f $D/$PREV/index.html && ln -sfn $PREV $D/frontend.tmp && python3 -c "import os; os.rename('$D/frontend.tmp','$D/frontend')" && launchctl kickstart -k gui/$(id -u)/com.word-dance.server && sleep 3 && curl -s --noproxy '*' http://127.0.0.1:8000/api/health || echo 'ROLLBACK NOT COMPLETED: fix the error above, then rerun this line'
```

代码也退回：先 `git -C /Users/sqin/word-dance -c user.name=sqin -c user.email=sqin@nvidia.com revert --no-edit cae93ef`，再执行上面那一块。已存成 `svg-v3` 的图在旧代码下就是普通的简笔画。

把 46 张图也换回原来的：按 `backups/dancing-import-20261120.json` 逐词把 `words.active_image_id` 指回 `old_image_id`，旧图行 `status='active'`、新图行 `status='superseded'`（先停服务或在低峰做）；或者整库恢复 `backups/pre-dancing-cards-20261120-1425.db.gz`（会丢掉之后的学习记录，不建议）。
