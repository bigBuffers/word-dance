# word-Dance：「单词之舞」—— 让单词自己跳出拼写、读音和意思（设计稿 v0.1，待 review）

> 日期：2026-11-08 · 代码基线：`main` @ `d9d5033` · 应 sqin 的要求由 Claude 撰写 · 状态：**v0.1 已评审；P1（拼写舞 + 重音舞）已上线（`2a1359d`，发布说明 `docs/releases/2026-11-word-dance-p1.md`）；P2（语义舞）已上线，见 §11 与 `docs/releases/2026-11-word-dance-p2.md`；P3 第一批（`hop` / `onto` 两个原语、设置页三档）见 §12 与 `docs/releases/2026-11-word-dance-p3.md`**
>
> 你的话：小学的图片确实提高了记单词的效率；软件叫 word dance，最初的想法是用一个单词「跳舞」的动态、醒目来增加记忆。请思考、分析、给出改进设计。
>
> 本文回答三件事：动态为什么可能有用、什么样的动态才有用（以及什么样的会帮倒忙）、在现有代码上怎么做。配套一个能点开看动效的原型页（31 个小学真词、现有图卡）：**https://claude.ai/artifact/18SLSmA1rj1aVnt5Z34Ngc**（私有链接，只有你能打开）。原型是设计探针，不是学习效果的证据；效果要按第 7 节的办法量出来。
>
> 代码事实来自对 `frontend/src` 与 `backend/wd` 的只读核对（文中给出文件与行号）；研究证据一部分来自 `docs/analysis/2026-11-05-stages-regions-images/facts/image-memorability.md`（已核验），一部分是本次新查的（标「新查」，只读到摘要，结论按证据强弱标注）。

## 0. 一页结论

**0.1 图片为什么有效，又差在哪。** 图片帮的是「义」：双重编码、图优效应，小学生尤其受益（image-memorability-7）。但两点已被反复证实：图片分走对**词形**的注意，拼写记不牢（image-memorability-8，Boers 等 2009/2017）；图片在回忆之前出现会造成「我记住了」的错觉，只有配合提取练习才兑现收益（image-memorability-6，Carpenter & Olson 2012）。另外静态图天然画不好的恰是小学词表里的一大类：方位词（in / out / over / under / behind）、动词（jump / turn / open）、程度形容词（big / small / fast / slow / tall / heavy）、状态词（cold / hot / happy / sad）。这些词的意思**本身就是一个动作或变化**。

**0.2 「单词跳舞」改进后的定义。** 不是让单词随便动，而是让单词的动作**承载信息**，分三层，彼此独立、可单独开关：

| 舞 | 动什么 | 教什么 | 覆盖 | 需要 AI 吗 |
|---|---|---|---|---|
| **拼写舞** | 字母按**音节**顺序入场，双写字母一起跳，不发音字母颜色变浅、不参与节拍 | 词形、字母顺序、音节分块（把 elephant 从 8 个字母变成 3 块） | 每个词 | 不需要（音节与重音从词库现成的 `phonetic` 算出，598/600 个小学词有音标） |
| **重音舞** | 全词按音节打拍子，**重读音节跳最高**、带橙色，和朗读同步 | 读音节奏、重音位置（中国孩子最常错的地方） | 每个词 | 不需要 |
| **语义舞** | 单词做一次它的意思：up 从下面升上来，small 缩小，in 走进盒子，cold 发抖，open 从中间分开 | 词义，专治图片画不好的那一类词 | 约三分之一的词（估计 180–210 个小学词，批量标注后出准确数） | 需要，但只是**从固定的舞步库里选一个**（JSON，≈ $0.003/词，600 词 ≈ $2），不生成动画本身 |

再加两种**用法**：首次学习的 2.5 秒编排（图先在 → 字母随朗读入场 → 重音节拍 → 翻面后做一次意思动作 → 释义与联想出现）；复习时把舞当**线索**（字母蒙住、只让它跳，孩子先说出单词，想不起再给图，最后揭晓），并随掌握程度把线索一级级撤掉，最终回到考试那样的静态文字。触屏上还可以让孩子**自己做**这个动作（把单词拖进盒子 = in，往上推 = up），研究里做手势与看手势都能帮记词（新查，见 §2）。

**0.3 为什么是这样而不是「炫」。** 动画对学习的元分析整体效应中等（d ≈ 0.37，Höffler & Leutner 2007，新查），但条件是动画**表现要学的内容**，装饰性的动画没有收益甚至有害；儿童对无关细节更敏感（image-memorability-13）；动态文字的研究也提醒：少数在动才醒目，全都在动就没有醒目可言（新查）。所以本设计的硬规则是：一个词一次只跳**一个念头**，不超过 2.5 秒；同一个动作永远表示同一类意思（动作成为一套孩子能学会的「视觉语法」）；只在前两三次见面和线索复习时跳，普通翻卡不跳；结束时**一定回到标准字形**（孩子正在学字母，不能把字形玩坏）；尊重系统「减弱动态效果」，退化成静态姿态（重读音节仍是橙色，big 仍比别人大）。

**0.4 在现有代码上的位置。** 学习卡正面已有词头、🔊、音标（`StudyCard.tsx` → `WordHeader`），翻面是直接替换、没有任何过渡（`StudyCard.tsx:207-235`）；发音只有浏览器 `speechSynthesis`（`hooks/useSpeech.ts`）。拼写舞 + 重音舞放在**正面**，跟现有的自动发音同一个时机；语义舞放在**翻面那一刻**（意思属于背面，正面不泄露词义，也不改动现在的「先想再翻」流程）。新增一个 `<DancingWord>` 组件（Web Animations API，只动 transform / opacity，零依赖，约 6–8 KB gzip，远在 200 KB 预算内），一个用户设置 `dance_mode`（全部 / 只拼读 / 关），后端一张 `word_dances` 表与一种新任务 `generate_dance`，照抄 `word_images` 的模式。**P1（拼写舞 + 重音舞）不需要 AI、不改学习流程、约 3–4 人日**，可以先上、先量效果。

**0.5 证据的诚实边界。** 直接证明「字母跳舞 → 单词记得更牢」的对照实验我没有找到；动态文字方面多是设计与理论文章。支持本设计的是四条**间接**证据：动画对动态内容的学习优势（元分析）、手势 / 观看手势对外语词汇的帮助（元分析，含 8 岁儿童 6 个月的保持）、提取练习与线索渐退（成熟结论）、以及「图片帮义不帮形」这一反面——拼写舞正是把注意力拉回词形。所以第 7 节的度量不是可选项：P1 上线即按词随机开关、看首次复习正确率，4 周出结论；没有效果就关掉，代码量不大，可逆。

**0.6 需要你定的事**（第 9 节）：功能名；P1 范围（只做拼读两舞，还是连语义舞一起）；语义舞在翻面时跳还是正面就跳；线索复习要不要做成小学默认；小学词头要不要换识字字体（需要自托管字体、改前端规则）；手势版现在做还是等移动壳；标注预算。

## 1. 现状（代码事实）

- **学习卡**（`frontend/src/components/study/StudyCard.tsx`）：正面 = 种类徽章 + 「第 i/n」 + 跳过（156–171），`WordHeader`（词头用衬线字体 `--font-word`：Charter / Georgia，🔊 按钮，`/音标/`，阶段芯片），「提示」是把例句里的词挖成 `___`（209–226），点「显示释义」或点卡面直接换成背面（213），**无过渡动画**；背面 = 释义（`meaning_zh` → 词典 → `translation_short`，148、306）、图（`show_images`，309–318）、例句（词高亮，每句 🔊，中文藏在「译」后）、搭配、记忆（`mnemonic_zh` 纯文本）、易混、词典释义、SRS 行；评分栏 不熟悉 / 模糊 / 记住了 / 已掌握 / 跳过。
- **发音**：只有 Web Speech `speechSynthesis`（`hooks/useSpeech.ts`，rate 0.92，`cancel()` 后再 `speak()`），没有 `onboundary`、没有任何时间点信息；自动发音在卡片切换的 `useEffect` 里（`StudyPage.tsx:205-212`）。已知坑：iOS 从非点击触发的朗读可能不响（`PUBLIC_LAUNCH_AND_IOS.md:51`），Android WebView 没有 `speechSynthesis`（`QUICK_DEPLOY_AND_MOBILE.md:359`）。**结论：舞不能依赖声音的时间轴，必须无声也成立。**
- **动效**：没有动画库（运行时依赖只有 react / react-dom / react-router）；令牌 `--dur: 180ms`（`tokens.css:59-61`）；几处 keyframes（按钮转圈、底部抽屉、toast、骨架屏）、筛词卡的拖拽位移；`prefers-reduced-motion` 是一条全局 CSS 把所有时长压到 0.01ms（`global.css:226-234`），JS 不检测。`FRONTEND.md:3` 禁止 UI 套件、CDN 资源和 web 字体。
- **数据**：`words.phonetic` 来自 ECDICT，重音用 ASCII 撇号（`'ræbit`、`bə'nɑːnə`），Claude 查词补的词用 IPA `ˈ`；全库 9618 个公开词里 9112 个有音标。**没有**音节、音素、重音字段，没有词根词缀，没有 CMUdict 之类的发音词典（`requirements.txt`）。AI 内容字段见 `backend/wd/ai/schemas/content_v1.json`：`meaning_zh`、`meaning_en`、`examples[{en,zh}]`、`collocations`、`mnemonic_zh`（联想句以「联想：」开头，`svg.py:85-93` 据此抽出画图的钩子）、`image_keywords`、`image_alt_zh`、`difficulty`。
- **复习状态**：`user_words`（10 分钟学习步，然后 1→3→8→20→51→133→180 天；`srs.py:24-32`）；`review_logs` 只在评分时写（action、context、前后状态、`elapsed_ms`）；展示、翻面、发音、看图**都不记录**。首次见面 = `push_items.kind='new'` 且 `repetitions=0`。
- **约束**：中文文案只在 `src/i18n/zh.ts`，`docs/FRONTEND.md` §8 与之镜像并有契约测试；`types.ts` / `schemas.py` / `zh.ts` 等冻结文件只能通过「contract change」提交修改（`TASKS.md:5`）；首屏 JS ≤ 200 KB gzip（现约 98.5 KB）；移动优先 360px；Vitest + jsdom（**jsdom 没有 Web Animations API**，组件必须对 `el.animate` 判空）；`make smoke` 只测 HTTP API。
- **已有的相关决定**：K-12 发布的 P15 把 `text_free` 列留给将来的「图→词」模式（第四期候选，`releases/2026-11-k12-stages.md:205`）——本设计的「线索复习」正好落在这个格子里。

## 2. 证据：动态什么时候帮记忆，什么时候帮倒忙

已核验（`facts/image-memorability.md`）：

- **图片帮义不帮形**：加图对词形保持「贡献很小」，回忆词形时无图反而更好；图片分走对词形的注意（[8]，Boers 等 2009、2017）。→ 拼写舞的立足点：把注意力拉回字母顺序，而且是在**图之前**、在正面。
- **图在回忆前出现 = 过度自信**；提取练习消除后图片才显出优势（[6]）。→ 线索复习的立足点：舞和图都应是「回忆的线索」，不是「答案」。
- **儿童对无关细节更敏感**（[13]）；Mayer 一致性原则，诱人细节效应为负（[12]）。→ 节制规则的立足点。
- **小学 / 初中更受益于配图，成人更受益于释义**（[7]）。→ 学段差异化的依据，同样适用于舞。

新查（只读到摘要或综述，标注强弱）：

- **动画 vs 静图**：Höffler & Leutner 2007 元分析（26 项研究、76 组对比）整体 d ≈ 0.37，中等；优势集中在**表现型**动画（画的就是要学的动态内容），装饰型没有。儿童词汇的个别实验里「动画卡通 vs 静图」常无差异，呈现时长一致时差异消失。**中**。含义：只给「意思就是动作」的词编舞，别给名词硬编。
- **手势 / 具身**：2023 年系统综述与元分析（7 项研究、309 人）：**看**手势和**做**手势对外语词汇的效果相当；Andrä 等 2020：8 岁儿童用手势或图片学外语词，收益保持到 6 个月；2026 年三层元分析（Educational Psychology Review）结论为正；Macedonia 2011：**有象征意义**的手势优于无意义动作。**中到高**（方向一致，效应量各异）。含义：语义舞 = 「看手势」的屏幕版，触屏拖拽 = 「做手势」的屏幕版；动作必须表意。
- **动态文字（kinetic typography）**：2023 年 *Humanities & Social Sciences Communications* 的理论讨论认为动态文字有学习潜力，但也明确：动的少才吸引注意，大面积动反而让静态的更显眼，滥用只剩干扰。面向儿童语言学习的交互式动态文字研究（ERIC EJ1074052）报告的是感知敏感度与「可学性」提升，没有保持测试。**低到中**。含义：动是稀缺资源，按预算花。
- **语义排版**：Word-As-Image（SIGGRAPH 2023）与 Dynamic Typography（ICCV 2025）证明可以让字形表达词义同时**保持可读性**。我们借它的思想（字形的姿态承载语义），不借它的生成式管线（一词一个视频：贵、不可控、风格不统一、手机上重）。我们用**参数化的舞步库**：确定性、可审核、可访问、几 KB。

## 3. 设计原则（七条，实施时逐条对照）

1. **动作必须表意**：拼写舞表形、重音舞表音、语义舞表义；没有可表之意就不动（虚词、抽象词只有拼读两舞）。
2. **一词一舞一念头**：每次最多一个语义动作，总时长 ≤ 2.5 s（拼写 ≈ 0.6–1.1 s，重音 ≈ 0.3 s × 音节数，语义 ≈ 0.8–1.7 s），无粒子、无彩带、无音效（唯一的声音是单词的读音）。
3. **统一的动作语法**：同一个舞步永远表示同一类意思（升起 = 向上类，进盒子 = 进入类），孩子学会这套「语法」后，动作才能成为可迁移的线索。
4. **舞是脚手架**：只在前 2–3 次见面与线索复习时出现；线索按掌握程度三级渐退，最终回到静态文字（考试的样子）。
5. **不伤字形**：动的是 transform，静止时一律回到标准字体；静态姿态只允许改**大小与颜色**（big 更大、cold 蓝色），不允许拉变形（最多 scaleY 1.2）。
6. **可访问、可关闭**：尊重 `prefers-reduced-motion` 与用户设置（全部 / 只拼读 / 关）；减弱动态时退化为静态姿态 + 重音着色，信息不丢。
7. **可度量、可逆**：按词随机开关，4 周看首次复习正确率；没有效果就关，不留技术债。

## 4. 三种舞的规格

### 4.1 拼写舞（所有词）

- 输入：`letters: string[]`（字母按音节分组，拼起来必须等于 `lemma`）、`marks.double`（双写字母对）、`marks.silent`（不发音字母下标）。
- 动作：字母按顺序入场（下方 18px 淡入，每字母 85 ms，音节边界多停 150 ms）；双写字母在入场后一起跳一下并轻微摆动（rabbit 的 bb、happy 的 pp）；不发音字母颜色变浅、不参与节拍（night 的 gh）。
- 时机：卡片正面出现时，与自动发音同一时刻触发（`StudyPage.tsx:205-212` 那个 effect）；点 🔊 时**重放**（声音与动作绑定，让「听」也有可看之物）。
- 数据来源：**规则**。音节数 = 音标里元音核的数量（含双元音），重音下标 = 撇号 / `ˈ` 之前的元音核数；字母分组用启发式（元音组之后的辅音簇从中间切开、双辅音从中间切、词尾 -le 自成一节、词尾不发音 e 并入前一节），预计 80–90% 的小学词一次正确。剩下的由 Claude 批量校对（见 §6.2），或者先只对规则**有把握**的词启用拼写分组、其余退化为整词入场。

### 4.2 重音舞（所有词）

- 输入：`letters`、`stress`（重读音节下标；单音节词为 0）。
- 动作：按音节依次打拍（每拍 330 ms），非重读音节跳 9px，重读音节跳 28px、放大 1.18、变橙（`--accent`）。音节芯片在词下方同步高亮（rab · **bit** 式的分块显示，带音标）。
- 为什么值得单独做：英语重音是中国孩子最常见、最少被纠正的发音问题；banana 的重音在第二拍，yesterday 在第一拍，静态音标很少有人看懂，跳一下就懂了。

### 4.3 语义舞（约三分之一的词）

舞步库第一批 26 个原语（P2 实现为 28 个，§11；P3 加 `hop`、`onto` 成 30 个，§12），每个原语附带：适用语义类、例词、可调参数、静态姿态（减弱动态时用）。原语名是代码里的枚举值，AI 只能选、不能造。

| 原语 | 动作 | 适用语义类 | 小学例词 | 静态姿态 |
|---|---|---|---|---|
| `rise` | 从下方升起到位 | 向上 / 起来 / 高 | up, high, stand up, climb | — |
| `fall` | 从上方落下并反弹 | 向下 / 低 | down, low, sit down, fall | — |
| `hop` | 整词蹲下、弹起、落地压扁，再小跳一次（P3） | 跳 | jump, hop, skip | — |
| `grow` | 由小变大到位 | 大 / 长大 / 更多 | big, large, grow, more | 字号 1.4× |
| `shrink` | 由大缩小到位 | 小 / 少 | small, little, tiny, less | 字号 0.6× |
| `dash` | 快速冲入带斜切 | 快 | fast, quick, run, hurry | — |
| `creep` | 缓慢挪入 | 慢 | slow, slowly | — |
| `enter` | 走进盒子（舞台上有盒子） | 进入 | in, into, inside, enter | 盒子静止在词周围 |
| `exit` | 从盒子里出来 | 出去 | out, outside, leave | 盒子在左侧 |
| `arc` | 从屋顶上方越过 | 越过 / 上方 | over, above, across | 屋子在下方 |
| `onto` | 从左上方落到台子顶上停住，台子微微一沉（P3，舞台上有台子） | 在……上面 | on, onto | 台子在下方 |
| `under` | 钻到桌子下面 | 下方 | under, below | 桌子在上方 |
| `behind` | 躲到树后、半遮住 | 后面 | behind | 半遮 |
| `between` | 夹到两个物体中间 | 中间 | between, middle | 两侧有物 |
| `split` | 从中间分开 | 打开 / 分开 | open, apart | 中间留缝 |
| `join` | 从两侧合拢 | 关上 / 一起 | close, together, meet | — |
| `shiver` | 快速抖动 | 冷 / 怕 | cold, afraid, scared | 蓝色 |
| `shimmer` | 热浪上浮 | 热 / 暖 | hot, warm, sunny | 红色 |
| `wave` | 字母依次欢快起伏 | 高兴 / 兴奋 | happy, fun, excited, glad | 橙色 |
| `droop` | 缓慢垂下再抬起 | 难过 / 累 | sad, tired, sorry | 灰蓝色 |
| `stretch` | 竖向拉高 | 高 / 长 | tall, long | scaleY 1.2 |
| `squash` | 压扁 | 矮 / 短 / 扁 | short, flat | — |
| `thud` | 重重落下压扁 | 重 / 强 | heavy, strong | 加粗 |
| `float` | 轻飘上浮 | 轻 / 飞 | light, fly, balloon | — |
| `spin` | 转一圈 | 转 / 圆 / 周围 | turn, round, around, circle | — |
| `repeat` | 入场两次 | 再 / 总是 / 常常 | again, always, often, every | — |
| `multiply` | 分身成 2–3 个再合并 | 数词 / 很多 | two, three, many, both | — |
| `dim` / `glow` | 舞台变暗发光 / 变亮 | 夜 / 暗 · 亮 / 白天 | night, dark · light, bright, day | 暗底 / 亮底 |
| `color` | 单词穿上这个颜色 | 颜色词 | red, yellow, blue, green… | 该颜色 |

选舞规则（写进提示词，也写进代码校验）：只看 `meaning_zh` 的**第一个义项**；具体名词（rabbit、banana、elephant）不编舞，图已经承担词义；虚词（the、of、and、is）不编舞；一个词只能有一个原语；拿不准就 `null`。原型里 24 个语义舞的实际效果见原型第 ③ 节。

### 4.4 首次学习的编排（学习卡）

| 时间 | 正面 / 背面 | 发生什么 | 现有代码位置 |
|---|---|---|---|
| 0.0 s | 正面 | 卡片出现：词头（字母尚未入场）、音标、阶段芯片、提示例句照旧 | `StudyCard.tsx:207-235` |
| 0.3 s | 正面 | 自动发音开始，同时**拼写舞**：字母按音节入场 | `StudyPage.tsx:205-212` 的 effect 里一并触发 |
| ≈1.4 s | 正面 | **重音舞**：按拍跳，重读音节最高；音节芯片同步 | `WordHeader` 下方新加一行音节芯片 |
| 孩子点「显示释义」 | 背面 | 背面出现（现在是瞬间替换）：词头在背面顶部做一次**语义舞**（0.8–1.7 s），释义、图、联想随后淡入 | `StudyCard.tsx:301-408` |
| 之后 | 背面 | 点 🔊 重放拼写 + 重音舞；评分栏照旧 | — |

只在 `kind='new'` 或 `repetitions < 3` 的卡上自动跳；其余卡只在点 🔊 时跳（用户设置可改）。

### 4.5 线索复习（P3）

对 `repetitions` 在 1–3 之间、且上次评分不是「不熟悉」的复习卡，正面改为：蒙住的字母（等长的色块）做这个词的舞，图模糊；按钮「看图提示」（去模糊）→ 「显示答案」（揭开字母、读音、释义）。三级渐退按掌握程度自动选择：

1. **强线索**（刚学会）：图 + 舞 + 色块 → 说出单词；
2. **弱线索**（间隔 ≥ 8 天）：只有舞 → 说出单词，再自己拼一遍；
3. **无线索**（间隔 ≥ 20 天）：现在的静态卡片 → 说意思（和考试一样）。

这改变了复习方向（从「看词说义」变成「由线索说词」，是更难也更有效的产出式练习），所以作为**可选模式**上线，先在小学阶段试。顺带满足 P15 预留的「图→词」模式。

### 4.6 做动作（P4，触屏）

把单词拖进盒子（in）、往上推过线（up）、点一下让它跳（jump）、双指捏小（small）。原型第 ④ 节做了 in 和 up 两张。只在触屏、只对有 `enter` / `rise` / `hop` / `shrink` 等「可做」原语的词启用；做对了才算完成，做错弹回。手机壳（Capacitor）之前就能在手机浏览器里用，Pointer Events 够了。

### 4.7 学段差异

- **小学**：全部三舞 + 线索复习（试点后决定默认）+ 手势；词头字体可考虑识字字体（见 §9 问题 5）。
- **初中 / 高中**：默认「只拼读」；重音舞对长词仍有价值；语义舞只留连接词、介词、程度副词这类抽象却有方向感的词（however 转身、therefore 推进、despite 顶着走）；新增**词缀舞**（第五期）：un · happi · ness 三块分别入场再对接，前缀后缀着色。词根词缀数据现在没有（`exchange_json` 只有屈折变化），需要 Claude 标注。

## 5. 原型说明

- 链接：https://claude.ai/artifact/18SLSmA1rj1aVnt5Z34Ngc （31 个小学真词、各自现有的 Claude 图卡、真实的 `meaning_zh` / `mnemonic_zh` / 例句 / 音标；约 123 KB，图卡内嵌）。
- 六节：① 学一个新词的 2.5 秒（可换 jump / rabbit / up / banana / cold / dance，带时间轴）；② 拼写舞 + 重音舞（rabbit、banana、yesterday、elephant、happy、night）；③ 语义舞 24 张（卡右上角是舞步名）；④ 自己做动作（拖 in 进盒子、推 up 过线）；⑤ 复习线索（蒙住字母的 jump / cold / open / big，看图提示 → 显示答案）；⑥ 不该跳的词（the、and、beautiful）与「减少动态」的样子。
- 顶部可调速度、模拟「减少动态」、开关朗读（浏览器语音）。点任何卡重跳一次。
- 原型与正式版的差别：原型的词头字体用了 Google Fonts 的 Andika（为识字设计：单层 a、单层 g、I / l / 1 可区分），正式版受 `FRONTEND.md:3` 约束只能自托管或沿用衬线；原型的音节分组是手标的，正式版由规则 + 校对产生；原型的语义舞时长偏长（方便看清），正式版按 §3 第 2 条收紧。
- 构建脚本在会话草稿目录 `scratchpad/dance/`（`proto_template.html` + `build_proto.py`，只读数据库），不进仓库。

## 6. 实现方案

### 6.1 数据

新表 `word_dances`（照 `word_images` 的模式）：`id, word_id, status(active|superseded), spec_json, model, prompt_version, reason, created_at`（`reason` = 模型给的 ≤ 12 字理由，供人工审核）；`words` 加 `active_dance_id`、`dance_state(none|queued|ready|failed)`。**实际落地为迁移 0016**（0015 已被 `dance_mode` 用掉）：因为 `jobs.type` 与 `ai_calls.kind` 的 CHECK 列表写死在初始迁移里，新增任务类型 `generate_dance` 和调用种类 `dance` 需要重建这两张表，所以 0016 是停机迁移（和 0011 / 0013 一样）。

`spec_json`（与 API.md §9 `DanceSpec` 一致，P2 实际写入的样子）：

```json
{
  "version": 1,
  "letters": ["up"],
  "stress": 0,
  "marks": { "double": [], "silent": [] },
  "semantic": { "primitive": "rise", "params": {} },
  "source": "claude"
}
```

（名词 rabbit 的存储结果是 `"semantic": null`——具体名词靠图，见 §4.3 的规则。）

校验（实际落地见 §11）：后端用 pydantic `schemas.DanceSpec` 校验；`"".join(letters) == display` **严格相等**（区分大小写，不做空格处理——词组、带缩写点的词条根本不标注，规则层也不给它们 spec），不满足就回退到规则层的切块；`0 <= stress < len(letters)`，不满足则连同切块一起回退规则层（不混用两层）；`primitive` ∈ 枚举或 `null`，`params` 按原语白名单（`multiply` 的 `n` ∈ {2, 3}，`color` 的 `color` ∈ 颜色枚举）。API：`StudyItem.word.dance: DanceSpec | null`（`schemas.py` + `types.ts` 契约变更一次）。

### 6.2 生成

- **规则层**（P1，无 AI）：`backend/wd/dance/syllables.py`：从 `phonetic` 得音节数与重音下标（两种重音记号都认），用启发式把字母分组；对 600 个小学词跑一遍，人工抽 50 个核对，正确率 < 85% 就把分组交给校对层、只保留重音。
- **校对 + 选舞层**（P2）：新任务类型 `generate_dance`（`kind='dance'`，复用 `ClaudeWorker` 与预算模块，独立日预算 `WD_AI_DANCE_DAILY_BUDGET_USD`，默认 0.50）：20 词一组，输入 lemma、音标、`meaning_zh` 第一义项、规则层的分组建议，输出每词 `letters`（确认或改正）、`semantic.primitive`（枚举或 null）、一句理由；JSON schema 强制枚举。成本：文本输出很短，≈ $0.003/词；小学 600 词 ≈ $2，一个晚上跑完（受每小时 60 次调用上限，20 词一组只要 30 次调用）。其余 9000 词像 SVG 一样**学到才生成**。
- **审核**：一个只读的审核页（像 2026-11-07 的「小学全部词卡」那样由脚本生成的 Artifact 即可，不必进产品）按原语分组列出所有词，一眼扫出选错的（例如把 close 的「近」当成「关」）。错的在管理页改原语或置 null（`reviewed: true`）。

### 6.3 前端

- `components/study/DancingWord.tsx`：props `word, spec, mode('learn'|'cue'|'static'), play(signal), onDone`；把词拆成 `<span class="l" aria-hidden>`，容器 `aria-label={word}`；动画全部用 `element.animate()`（WAAPI），只动 `transform` / `opacity`；`if (!el.animate) return`（jsdom）；`matchMedia('(prefers-reduced-motion: reduce)')` 或设置为「关」时直接呈现静态姿态。舞步库 `components/study/dances.ts` 是**纯函数** `primitive → Keyframe[] + options`，便于单测。
- 接入点：`WordHeader` 的词头换成 `<DancingWord>`；`StudyPage.tsx:205-212` 的自动发音 effect 同时触发 `play('form')`；`StudyCard` 翻面时触发 `play('semantic')`，背面内容加 150 ms 淡入（现在是瞬间替换）；`SpeakButton` 点击重放 `form`。
- 设置：`user_settings.dance_mode`（`full | form_only | off`），默认按主攻阶段（小学 `full`，其余 `form_only`）；设置页「学习设置」加一项；文案进 `zh.ts` 与 `FRONTEND.md` §8。
- 曝光预算不需要新表：由 `user_words.repetitions` / `interval` 推导；度量用 `review_logs.context` 附加 `dance=1|0`（已有字段，不改表）。
- 声音：动作与声音并行而非同步（Web Speech 没有音素时间；按 85 ms/字母 + 150 ms/音节边界估算的入场时长与 rate 0.92 的朗读长度大致相当）；无声环境（Android WebView、静音）动作照常。
- 性能：一个词最多十几个 span，transform / opacity 走合成层；不用 `will-change` 常驻；360px 下字号随容器缩放；无新依赖。
- 测试：`dances.test.ts`（纯函数快照）、`syllables` 规则的 200 词黄金表（后端 pytest）、`DancingWord` 在 jsdom 下渲染且不报错；`qa-study.md` 加一组手测项（iOS Safari、Android Chrome、减弱动态）。

### 6.4 工作量与成本（业余，人日）

| 期 | 内容 | 人日 | 钱 |
|---|---|---|---|
| P0 | 本设计 + 原型（已完成） | — | $0 |
| P1 | 拼写舞 + 重音舞（规则层、组件、设置、接入、测试、文档） | 3–4 | $0 |
| P2 | 舞步库 26 原语、`generate_dance`、600 小学词标注、审核页 | 5–6 | ≈ $2 |
| P3 | 线索复习三级渐退（可选模式） | 3 | $0 |
| P4 | 触屏做动作（in / up / jump / small 四种） | 3–4 | $0 |
| P5 | 初高中词缀舞（需词根词缀标注） | 2–3 | 待估 |

## 7. 怎么知道有没有用

- **分组**：P1 上线起 4 周，按 `word_id` 奇偶把舞随机开关（同一孩子一半词有舞、一半没有），`review_logs.context` 记 `dance=1|0`。
- **主指标**：首次复习（第 1 天）评「记住了 / 已掌握」的比例，有舞 vs 无舞；次指标：到达 8 天间隔所需的复习次数、`elapsed_ms`（不应增加 > 20%）、🔊 重放次数（评分时写进 context）、设置里关掉的人数。
- **拼写**：现在没有听写模式，所以 P1 量不到词形；P3 的线索复习里加一个「自己拼一遍」的可选输入框后再量拼写正确率。
- **定性**：先看家里的孩子学 20 个新词的样子——哪些舞她能复述、哪些词她记得「它是怎么跳的」、有没有因为好玩而反复点（好事）或者被分神（坏事）。
- **判据**：主指标提高 ≥ 10 个百分点且时长不超 → 开为默认；无差异 → 保留为可选、不再投入；变差 → 关闭。

## 8. 风险与反对意见

| 风险 | 对策 |
|---|---|
| 变成炫技，分散注意（Mayer；儿童更敏感） | 原则 1–3 的硬规则写进代码（时长上限、单动作、无装饰）；按词随机开关量效果；一键关闭 |
| 语义选错（close 是「关」还是「近」） | 只看第一义项；拿不准就 null；审核页按原语扫；管理页可改 |
| 动作看多了麻木 | 动作的多样性来自词义而不是随机花样；只在前 2–3 次见面与线索复习时跳 |
| 伤字形（孩子在学字母） | 静止必回标准字体；静态姿态只改大小与颜色 |
| 动态敏感的孩子 | 系统减弱动态 + 用户设置双保险；减弱后信息不丢 |
| iOS 朗读时机不可控 | 舞不依赖声音；声音能响就并行 |
| 初高中学生觉得幼稚 | 学段默认「只拼读」；重音与词缀是他们的刚需 |
| 范围蔓延 | P1 不依赖 AI、不改复习流程，先上先量；P3 以后看数据再定 |

## 9. 需要你决定的事

1. **名字**：产品里叫「单词之舞」吗（设置项、说明文案进 `zh.ts`）？
2. **P1 范围**：先只做拼写舞 + 重音舞（3–4 人日、$0），还是 P1 + P2 一起上（再加 5–6 人日、$2）？我建议先 P1，4 周有数据再做 P2。
3. **语义舞的时机**：翻面时跳（我建议：不泄露词义，不改流程），还是正面就跳（更醒目，但「先想再翻」就没了）？
4. **线索复习**：做成小学的默认复习方式，还是可选模式先试？我建议可选先试。
5. **小学词头字体**：换成识字字体（Andika 一类，需自托管一个约 30 KB 的拉丁子集并修改 `FRONTEND.md:3` 的规则），还是沿用现在的衬线？原型用了 Andika，你可以直接比较。
6. **手势版**：P4 现在排进去，还是等到有移动壳之后？
7. **预算**：小学 600 词的标注 ≈ $2 一次性；全库按学到才生成，日预算 0.50。可以吗？

---

附：本次新查的来源（只读到摘要 / 综述页）——Höffler & Leutner 2007 元分析（动画 vs 静图，d ≈ 0.37）；*Humanities & Social Sciences Communications* 2023「What drives the learning benefits of moving text?」；ERIC EJ1074052（儿童交互式动态文字）；Systematic review & meta-analysis of enacting vs observing gestures in FL vocabulary（PMC10669578，2023）；Andrä 等 2020（*Educational Psychology Review*，8 岁儿童，6 个月）；「From Body to Word」三层元分析（*Educational Psychology Review* 2026）；Iluz 等「Word-As-Image for Semantic Typography」（SIGGRAPH 2023）；Liu 等「Dynamic Typography」（ICCV 2025）。

## 10. 2026-11-08 的决定与 P1 实现记录

**决定（sqin：「按你的建议定，先做拼写舞和重音舞」）。** ① 功能名「单词之舞」；② P1 只做拼写舞 + 重音舞（不依赖 AI、$0），语义舞（P2）等 4 周 A/B 数据；③ 语义舞将来放在翻面时跳；④ 线索复习（P3）先做可选模式；⑤ 小学词头字体暂不换，沿用衬线；⑥ 手势版（P4）等移动壳之后；⑦ 标注预算（≈ $2）留到 P2。

**P1 实现（同日）。**
- 后端 `backend/wd/dance.py`：纯规则，从 `display` + ECDICT `phonetic` 得 `DanceSpec`（§6.1 的 JSON，少了 `semantic`，多了 `source: 'rule'`）；不落库，`services/words.word_detail` 与 `services/screen.study_item_dict` 序列化时现算。规则要点见发布说明 §2。覆盖：小学 600 词 586 切开、6 个按单音节（hour、fire、our、tired、TV、OK）、8 个词组 / 缩写为 `null`；全库 9618 词 8917 切开、106 整词退化、595 为 `null`。
- **规则评审（同日）**：6 个评审代理按词典音节划分与小学自然拼读规则逐词核对 600 个小学切法和 400 个初中样本，每条疑点再由一个「反驳者」代理核实：30 条确认、14 条驳回（ev·ery / eve·ry、mo·ther / moth·er 这类两可切法不算错）。确认的问题全部修进规则而不是改词：ECDICT 双撇号记法（'fif'tiːn）取最后一个为主重音、13–19 数词一律重读 -teen；iə / uə 在拼写为 i / u + 元音字母时读成两拍（se·ri·ous、Jan·u·a·ry、ex·pe·ri·ence）；拼 /ʃ/ 的 ti / ci / si 归后缀（na·tion·al、spe·cial、sit·u·a·tion）；r 控制元音与非重读 er 带着 r（or·ange、dif·fer·ent）；tch 不拆（kitch·en）；n 后的音节 l（fi·nal、per·son·al）；gh 在 fight 里也标为不发音；音标省掉的 ə 按拼写补回（in·ter·est·ing、con·sid·er、choc·o·late）；-ing 保留词干（meet·ing、morn·ing）；y 在无 /j/ 时并入元音组（play·er）；august（月份）与 email 两个词按词覆盖音标。第二轮复核（规则修正后重新生成的 600 行，4 个评审 + 逐条反驳）：无回归，确认 1 条（Wednesday 的第一个 d 不发音，已加规则）、驳回 6 条策略性意见（wh- 作为字母组合不标 h 不发音；people / friend 元音组合里的字母不标；-le 的 e 不标；sc- 的 c 不标）。留给 P2 的 Claude 校对：后缀 -er 的切法（teach·er 词典 vs tea·cher 自然拼读）、多音词（record）、连字符词（ping-pong）、ECDICT 省音读法（diffe·rent、inte·rest、vege·ta·ble 保持可辩护的拼读切法）。
- 迁移 `0015_dance_mode.sql`：`user_settings.dance_mode`，默认 `full`，纯附加。
- 契约：`schemas.py` / `types.ts` / API.md §9 新增 `DanceMode`、`DanceSpec`，`Settings.dance_mode`，`StudyItem.word.dance`、`WordDetail.word.dance`；`PUT /api/settings` 校验枚举。
- 前端：`components/word/dances.ts`（纯关键帧计划，≤ 2.5 s）+ `DancingWord.tsx`（WAAPI，jsdom / 减弱动态时静态）；`WordHeader` 接 `dance` / `playToken`，加音节芯片，🔊 重放；`StudyCard` 透传；`StudyPage` 持有 `danceToken`（新词与 `repetitions < 3` 的复习卡出现时 +1，按 `P` +1，推荐词不跳）；详情页显示芯片；设置页开关「单词之舞」；文案 `zh.ts` 四条（`word.syllables`、`word.replayDance`、`settings.dance`、`settings.danceHint`）+ FRONTEND §8 镜像。
- 测试：`test_dance.py`（101 条金表（100 词，abandon 的两种音标记法各一条） + 全种子不变量）、`test_db_0015.py`、契约审计、`dances.test.ts`、`DancingWord.test.tsx`、`WordHeader.test.tsx`、`StudyCard` / `SettingsPage` 各一组。
- 与 §4.1–4.2 / §6.3 的差别（实现以 `docs/FRONTEND.md` §6.5 与发布说明 §2 为准）：拼写舞入场是 `translateY(0.35em) scale(0.86)`（不是 18px），8 个及以上字母的词字母 55 ms、音节边界 120 ms；重音舞每拍 300 ms、重读那拍 330 ms（不是每拍 330 ms），非重读跳 −0.2em、重读跳 −0.6em（不是 9px / 28px），重读着色取 `--dance-accent` = `--brand-ink`（品牌蓝，没有橙色令牌）；音节芯片静态标出重读块，不随节拍高亮；组件在 `components/word/`（不是 `components/study/`），props 为 `text, spec, playToken?, autoplay?`（没有 `mode` / `onDone`）；`dance_mode` 对所有阶段默认 `full`（没有按主攻阶段默认 `form_only`），P1 把 `form_only` 当 `full`；自动播放的范围是新词与 `repetitions < 3` 的复习 / 加练卡（推荐词不跳，翻面不重跳），不记曝光日志，靠 `user_words.repetitions` 推导；度量用 `review_logs.context` 的方案留到 A/B 开始时接。

## 11. P2 语义舞实现记录（2026-11-08，sqin 在手机上确认 P1 效果后：「继续做语义舞」）

- **舞步库**：§4.3 的 26 行落成 28 个原语（`dim` / `glow` 拆开，`color` 带颜色参数）：`rise fall grow shrink dash creep enter exit arc under behind between split join shiver shimmer wave droop stretch squash thud float spin repeat multiply dim glow color`，前端 `dances.semanticPlan` 每个原语一种动作，全部以 em 为单位、≤ 2.5 s；enter / exit / arc / under / behind / between 六个原语站在 CSS 画的小舞台物件上（盒子、屋顶、桌子、树、两道杠）；cold / hot / sad 与颜色词有静态姿态色（只改颜色不改字形，原则 5）。
- **何时跳**：语义舞只在**翻面**时随背面挂载播放一次（决定 ③），正面只有拼读两舞；背面的 🔊 / `P` 重放 = 拼读 + 重音 + 语义；`dance_mode = form_only` 不播、不摆姿态（P2 起有实际含义；设置页暂时仍是开关，`form_only` 只能通过接口设置 —— P3 第一批已改为三档，见 §12）。
- **标注管线**：新任务类型 `generate_dance`（每次 20 词，kind `dance`，独立日预算 `WD_AI_DANCE_DAILY_BUDGET_USD` 默认 0.50，单次 `WD_AI_BUDGET_DANCE` 0.25，超时 120 s）；提示词 `dance_system.txt`（dance-v1），schema `dance_v1.json`（扁平：`primitive` 含 `none`，`n` / `color` 以 0 / "" 表示不适用，因为 CLI 已验证的关键字集合没有 oneOf）；输入给模型的是词形、音标、`meaning_zh` 第一义项（没有内容时取词典里主要词性那一行——ECDICT 按词性排列，fly 的第一行是「n. 苍蝇」而它八成是动词；内容任务还在路上时舞步任务顺延 10 分钟等卡片上的义项，最多 6 次）和规则层的切块；运行时再查一遍词是否被合并 / 判无效（跳过）；后验证：切块拼不回词形就回退规则切块，重读越界则切块和重读一起回退规则层（不混用两层），字母标记永远取规则层，最终用 `schemas.DanceSpec` 校验后写入 `word_dances`（旧行 superseded）并指向 `words.active_dance_id`；缺失或不合格的词任务失败重试，全军覆没则按 invalid_output 走 §6.3。
- **入队**：`bank.enqueue_content_if_needed` 在内容任务**之后**顺带 `dance.enqueue_if_needed`，优先级比内容任务低一档（11 / 21 / 31），等内容的学习者永远不用排在舞步调用后面；门控：词有效、未合并、有规则 spec、没有仍能拼回词形的 Claude spec、没有存活的 `dance:<id>` 任务；子预算为 0 时什么都不排（关掉功能不产生任务抖动）；词形改名导致旧 spec 拼不回、或任务在 worker 崩溃路径上死掉留下 `queued` 的词会被重新排队。批量 `wd dance-annotate --stage xs` 跑小学 600 词（30 次调用 ≈ $2，一个晚上，预算临时抬高后脚本回退）。
- **读取**：`dance.spec_for_word` 先取存储的 Claude spec，没有再按规则现算；卡片从不等任务。
- **数据与运维**：迁移 0016 重建 `jobs` / `ai_calls`（CHECK 列表加新值）、新建 `word_dances`、`words` 加两列 —— 停机迁移；`wd check db` 不变；管理页 `ai` 多两项 `dance_today_usd` / `dance_daily_budget_usd`。
- **测试**：`test_db_0016`（重建保留全部行与索引、CHECK 生效、唯一活动行）、`test_dance_annotate`（入队门控与去重、worker 整批标注、存储 spec 优先于规则、坏切块回退、预算为 0 时跳过、CLI）、契约与 fake claude 测试扩到 `dance_v1`；前端 `dances.test`（28 原语全部 ≤ 2.5 s、目标合法）、`DancingWord`（舞台物件 / 分身 / 姿态色 / 三种播放方式 / form_only）、`StudyCard`（背面翻面播放、form_only 不播）。
- **回填与评审（2026-11-08）**：小学 600 词中 592 个标注完成（30 次调用 $0.675），67 个有动作；评审确认动作全部合库、无漏判；切块改正 12 处里 10 处更好。确认的两处**库空缺**：`jump`（库里没有「跳」——rise 是向上 / 高处的位置义，不是跳）和 `on`（in / on / under 三件套缺 on）；提议 P3 加两个原语 `hop`（整词向上弹一下落回）和 `onto`（词落到舞台物件顶上停住），各自对应的典型词：jump、hop、skip / on、on top of。
- **留给 P3**：线索复习；按学段默认 `form_only`；设置页三档开关（§12 已做）；标注结果的人工审核页（本次用一次性 Artifact）；上面两个库空缺（§12 已做：`hop` / `onto`）；规则层的 `-er` 后缀切分（work·er / farm·er 而不是 wor·ker / far·mer）。

## 12. P3 第一批实现记录（2026-11-08 晚，sqin：「P3 加 hop 和 onto 两个原语，设置页开三档」）

- **两个原语**：`hop`（jump / hop / skip：整词以脚底为变换原点蹲下 → 弹起 1.3 em → 落地压扁 → 再小跳一次 → 回到原样，1.3 s，没有舞台物件、没有姿态）和 `onto`（on / onto / upon：从左上方划一道弧落到台子顶上、落地时微微压扁、台子跟着沉一下，1.3 s；新舞台物件 `shelf`，台面在基线处，字母（含下伸部）画在台子前面）。库从 28 个到 30 个；枚举顺序 = 提示词舞步库顺序（hop 在 fall 之后，onto 在 arc 之后），`test_schemas` 把 `dance_v1.json`、`schemas.DancePrimitive`、`models.DanceItem` 与提示词的舞步库锁成一份，types.ts 由 `check_contract` 对齐，API.md §9 的 ts 块由 `test_docs_contract` 锁定为与 types.ts 逐字相同。
- **提示词** `dance-v2`（`word_dances.prompt_version`）：只加两行舞步；已存的 `dance-v1` spec 全部有效（枚举只增不减），不重跑小学 600 词，只对评审确认的库空缺 `jump`、`on` 用 `wd dance-annotate --word jump --word on --force` 重标（和 worker / farmer 的切块重标一起受当日舞步子预算限制，11-09 00:05 已执行：一次合并调用 $0.019，jump → hop、on → onto；worker / farmer 的切块仍是 wor·ker / far·mer——提示词第 1 条要模型「除非明显错误，否则保留规则层建议」，音节上的 VC·CV 切分并不「明显错误」，所以 -er 后缀切分要在规则层做，见下方「留给以后」）。
- **设置页三档**：学习设置里的「单词之舞」从开关改为分段控件 全部 / 只拼读 / 关（`dance_mode` = `full` / `form_only` / `off`，和例句译文、口音同一控件），说明文字另起一行；文案 `settings.danceModes` + 改写的 `settings.danceHint`，FRONTEND §8 镜像。
- **不变**：数据库（无迁移）、入队与预算、P1 / P2 的播放时机、`form_only` 的含义。
- **测试**：`dances.test`（30 原语 ≤ 2.5 s；hop 整词起跳后回到原样；onto 从左上方进场、落定后回到原样，台子步不带效果级 easing、在落地偏移之后才下沉）、`DancingWord`（onto 画 shelf，台子步真的落在舞台物件上）、`test_docs_contract`（API.md §9 与 types.ts 逐字相同）、`SettingsPage`（三档保存 form_only / off / full，顺序 全部 / 只拼读 / 关）、`test_dance_annotate.build_spec`（hop / onto 不带参数，多余的 n / color 丢弃）、`test_schemas`（三份枚举与提示词同序）。
- **留给以后**：线索复习（§4.5）；按学段默认 `form_only`；规则层 -er 后缀切分；标注审核页进产品；手势版（§4.6）。
