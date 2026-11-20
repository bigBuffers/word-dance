# 发布说明 · 2026-11 · 跳动图卡（后端 + 前端，无迁移）

基线 `main @ d865321`。状态：**代码已完成、未提交、未上线**；试画 6 张已出，等 sqin 看过再画其余 44 个词、再确认上线。
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

## 4 上线和回滚（未执行）

上线 = 提交 → 前端快照 + `launchctl kickstart`（同 `2026-11-short-meaning.md` §3）。回滚 = `git revert` 该提交 + 指回上一个前端快照；已经存成 `svg-v3` 的图在旧代码下就是普通的简笔画（多一条看不见的 `<desc>`），不需要处理。
