# studio/ —「记忆图卡」是怎么做出来的

这个目录是做图的地方：手册、画风、人物设定、工具、字体，以及已经定稿的图。App 本身不依赖这里的任何东西——图在这里**离线**做好、检查好，再用 `wd images-import` 导入线上。方案和已定的事见 `docs/MEMORY_CARDS_DESIGN.md`。

> 来历：2026-11-12 sqin 说小学词库的图「不够生动」，要更贴近生活、更唯美、带单词记忆功能。先做了 10 张样例（画风由三位评审从三个试画方向里选出），11-13 确认「符合预期」。当时的制作现场是一次会话的临时目录，会被清掉，所以把要长期留的部分收进了仓库；没收进来的东西见文末。

## 1. 一张图卡是什么

一张 800×500 的 SVG，分两层：

- **场景层** `<g id="scene">`：一个生活瞬间（朵朵、乐乐、奶奶、橘猫团子轮流出场），**没有任何文字**，单独看也完整。
- **单词层** `<g id="word-art">`：永远是最后一层。单词本身，用开源识字字体 Andika 的字形轮廓画成路径（不是 `<text>`，设备上不用装字体），按拼读块分色，不发音的字母是虚线的「幽灵字母」，双写字母成对；再加一个由画面演出来的**记忆钩子**（比如 moon 的两个 o 是天上和水里的两轮月亮）。

每张图配三句话，写在清单 `manifest.json` 里，随图一起导入：

| 字段 | 是什么 | 上限 |
|---|---|---|
| `hook_zh` | 记忆钩子，一句话，学习卡「记忆」一栏显示它 | 导入时 60 字；手册要求 34 字以内 |
| `note_zh` | 读音或词义提醒（拼读块可能让孩子读错、理解错的时候才写），可以为空 | 导入时 60 字；手册要求 30 字以内 |
| `alt_zh` | 画面描述（图片的替代文字） | 200 字 |

App 里同一张图有两种取法：带单词层，或者（设置里关掉「图片上显示单词」后）不带。所以场景层必须自己站得住。

## 2. 目录里有什么

```
studio/README.md            本文
studio/STUDIO.md            制卡手册（英文，给画图的人 / 模型看）：两层结构、技术限制、场景要求、单词层要求、怎么自查
studio/STYLE.md             画风「晨光动画」：评审的结论和必须遵守的规则（比手册严的地方以它为准）
studio/LESSONS.md           批量试画时评审扣分的地方（英文）：动笔之前读，排在 STYLE.md 之后
studio/pilots/B/STYLE.md    画风的技术配方（调色、打光顺序、景深、渐变和模糊的写法、踩过的坑）——STYLE.md 引用它
studio/cast/CAST.md         人物设定：朵朵、乐乐、奶奶、团子的 SVG 片段，直接粘贴，不要重画
studio/cast/cards/sheet.svg 人物设定图的源文件
studio/cast/family/         大人角色的设定（11-13 新增）：CAST-family.md 是爸爸、妈妈、爷爷、李老师、路人的 SVG 片段（先读 CAST.md），cards/ 是两张设定图和 7 张测试场景的源文件
studio/tools/               letters（字形）、check（校验 + 渲染）、build_gallery（总览页），各有一个同名的 sh 包装
studio/fonts/               Andika-Bold.ttf + OFL.txt（许可见 §8）
studio/cards/<lemma>.svg    已导入线上的图（原始文件，未清洗）。现在是 68 张：确认过的 10 张样例，加上 2026-11-14 按 sqin 的要求先行上线的前 100 词中的 56 张，再加 2026-11-20 为登录页补的 jump（11-13 画法试验里的 F2 那张）和 cold（当天新画）（其中只有 10 张做过评审返修，另 44 个词还没画，见 studio/recovery-20261114.json）
studio/manifest.json        这些图的清单：画法版本、做图的模型、每张图的三句话
studio/requirements.txt     工具的依赖（fonttools、skia-pathops、defusedxml）
studio/tests/               工具的自测
```

不进 git 的（已写进 `.gitignore`）：`studio/.venv/`、`studio/tmp/`（草稿、批次的工作文件、渲染用的临时网页）、任何 `png/`（渲染图）和 `clean/`（清洗后的文件）。`studio/tmp/` 顶层那些 `full-*.html`、`sheet-*.html`、`zoom-*.html` 是渲染用的临时网页，随时可删；**批次的目录不是**——正在做的批次只存在于这里（眼下是前 100 个词的 `studio/tmp/run100/` 和批量画法试验的 `studio/tmp/scratch-archive/exp/`，见 §3），定稿收进 `studio/cards/` 之前别删，也别删它所在的工作区。

## 3. 流程

```
美术指导 → 画 → tools/check → 看图 → 评审 → wd images-import
```

1. **美术指导**：给每个词定场景和记忆钩子（谁、在哪、做什么、哪种光；钩子必须和拼写、读音都对得上，不用谐音，不编词源），再由另一位逐条核对钩子属实、画得出来。输入是这个词在 App 里的资料（释义、例句、拼读块、不发音字母、双写字母）——格式见 `STUDIO.md` 开头的「brief」。
2. **画**：照 `STUDIO.md`、`STYLE.md`、`LESSONS.md`、`cast/CAST.md` 写一张 SVG。草稿放在 `studio/tmp/<批次>/cards/<词>.svg`。字母一律用 `tools/letters` 生成的路径，原样粘贴，不许手改。
3. **tools/check**：程序校验 + 渲染。先过 App 自己的清洗器和导入时的结构校验（用的就是 `backend/wd/images/` 里的代码，不是另抄一份），再做只有这里能做的字形校验（这里有字体），最后用 Chrome 渲染成 PNG。`errors` 必须清零，`warnings` 逐条掂量。
4. **看图**：打开渲染出来的 PNG，像 sqin 那样看：整图、去掉单词的场景、手机大小、每张脸每只手的放大图。第一版从来不是定稿，回到第 2 步改。
5. **评审**：整批看一遍（孩子和家长、美术指导、英语老师三个角度），该返修的返修；出总览页（`tools/build_gallery`）给 sqin 看。
6. **导入**：sqin 点头之后，把定稿的图放进 `studio/cards/`，三句话写进 `studio/manifest.json`，再 `wd images-import`（§6）。

10 张样例是精修出来的，每张反复画了 9–14 轮；批量做（先做小学学习顺序的前 100 个词）不能照搬，画法由 `docs/MEMORY_CARDS_DESIGN.md` §6 的试验定了下来（2026-11-13）。

**批量画法的试验。** 四种画法各画同样的四个词（kite、jump、hungry、library），场景和钩子都出自第 1 步那样的自动美术指导；16 张图打乱编号，由三位评审（孩子和家长、美术指导、英语老师）对着确认过的样例盲评，8 分 = 样例的水平，每种画法 12 票：

| 画法 | 平均分 | 可直接用 / 小修 / 不可用 |
|---|---|---|
| 会话模型，最多看两次渲染图 | **7.54** | 9 / 3 / 0 |
| 会话模型，不看渲染图直接画 | 7.21 | 6 / 6 / 0 |
| Opus，看两次 | 6.96 | 3 / 9 / 0 |
| Sonnet，看三次 | 6.38 | 1 / 9 / 2 |

「会话模型」是做图的会话自己用的模型，也就是画那 10 张样例的那个（清单里的 `model`）。每种画法每张都要 20–25 万 token——大头是读手册和写出约 35 KB 的 SVG，不是看图的那几次，所以少看几眼省不了多少。

**选定的画法**（前 100 个词照此做）：

- **画**：会话模型，每张最多看两次渲染图（第 3、4 步最多走两轮）。和样例是同一个模型，所以这 100 张和样例共用 `studio/manifest.json`，`model` 不变。
- **美术指导**：每批 11 个词，一位策划定场景和钩子，一位挑错的人逐条核对；全部 100 个词再由一位编辑通看一遍（场景、人物、钩子在整套里不重复、不打架）。
- **评审的教训**：试验里扣分的地方整理成了 `LESSONS.md`，画之前读。

试验的 16 张图、评审记录和这 100 张的工作文件都在 `studio/tmp/` 下（写这段话时是 `studio/tmp/scratch-archive/exp/` 和 `studio/tmp/run100/`），不进 git。

## 4. 搭环境（一次）

工具有自己的小虚拟环境，不和 App 的 `.venv` 混用（App 不需要 fonttools、skia-pathops）。三个依赖都写在 `studio/requirements.txt` 里，照它装，不要凭印象手装——缺了 skia-pathops，`letters` 和 `check` 一运行就报 `ModuleNotFoundError: No module named 'pathops'`：

```sh
cd <仓库根目录>
python3.12 -m venv studio/.venv
studio/.venv/bin/pip install -r studio/requirements.txt pytest    # pytest 只有跑自测才需要
```

渲染需要本机装有 Google Chrome，路径是 `studio/tools/check.py` 顶部的常量 `CHROME`（默认 `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`）；Chrome 不在那里时 `check` 会明说，换路径就改这一行。只校验不渲染（`--no-render`）不需要 Chrome。

自测（不属于 `make test`）：

```sh
make studio-check        # 没有 studio/.venv 时先建好，按 requirements.txt 装依赖，再跑 studio/tests
# 或者直接：
studio/.venv/bin/python -m pytest -q -p no:cacheprovider studio/tests
```

`make studio-check` 每次运行都会按 `studio/requirements.txt` 核一遍依赖（外加 pytest）：装齐之后这一步是空操作，不用联网；第一次装到一半断了（比如 pip 要走的代理没开），网络通了再跑一次就补齐，不用删 `studio/.venv`。

## 5. 工具

三个工具都可以在任何目录下运行，路径都是从工具自己的位置算出来的。

### tools/letters —— 字形

把一个词按基线排好，输出每个字母的 SVG 路径（画布坐标）和尺寸信息（JSON）。

```sh
studio/tools/letters moon --size 150 --x 400 --baseline 330                      # 以 x=400 居中
studio/tools/letters breakfast --chunks "break|fast" --gap 12 --size 100 --x 400 --baseline 440
studio/tools/letters rain --split-dots --size 140 --x 250 --baseline 200         # i / j 的点单独成一条路径（好让一滴雨来当这个点）
studio/tools/letters moon --size 150 --x 400 --baseline 330 --brief              # 只要尺寸，不要路径
```

输出里每个字母有 `id`（`wa-<序号>-<字母>`，必须原样保留——导入时就是靠这些 id 核对拼写）、`d`、外框 `bbox`、中心、每个轮廓的外框（`hole: true` 是字母里的空心，比如 o 的肚子）。连字符、撇号这类不算字母的符号 id 是 `wap-<序号>`，不参与拼写核对。要挪动或缩放字母就换参数重新生成；**不要改 `d`**。给 `<path>` 或外层 `<g>` 加 `transform` 只能平移、等比缩放（`scale(.9)`，不能是 `scale(.8 1)`）、微微倾斜——镜像、上下翻转、压扁、拉长、斜切、倒过来的字母，`check` 一律判错（见下）。

输出的轮廓默认是**合并过的**：字体里 f、t、k、e 这些字母由几块互相重叠的轮廓拼成，`letters` 用 skia-pathops 把它们并成一条不重叠的轮廓，这样幽灵字母的虚线描边不会在字母内部出现重影（`LESSONS.md` 第 10 条靠的就是这个）。`--raw-outlines` 输出字体原始的重叠轮廓，只用来复现最早的 10 张图（它们用的是原始轮廓；两种 `check` 都认）。

### tools/check —— 校验 + 渲染

```sh
studio/tools/check studio/cards/moon.svg --word moon
studio/tools/check studio/tmp/batch-01/cards/kite.svg --word kite --zoom 300,120,220,200 --zoom 40,300,720,180
studio/tools/check studio/cards/moon.svg --word moon --no-render            # 只校验
studio/tools/check studio/cast/cards/sheet.svg --sheet                      # 不是图卡（人物设定图）：只清洗 + 渲染
```

`--word` 是单词的**显示形式**（`Monday`、`T-shirt`），因为图上画的就是它。产物写在 SVG 所在目录的上一层：`clean/<名>.svg`（清洗后的文件，也就是 App 会下发的那个）、`png/<名>.png`（800×500）、`png/<名>.sheet.png`（左：去掉单词层的场景；右：手机大小），每个 `--zoom X,Y,W,H` 再出一张局部放大图。屏幕上打印一份 JSON 报告。退出码 0 = 没有错误，1 = 有错误，2 = 工具本身没法跑（参数不对、找不到仓库里的清洗器）。

它依次做四件事：

1. 用仓库自己的清洗器清洗：`wd.images.sanitize_svg.clean(…, allow_text=False, effects=True)`，和导入时一模一样；被清洗器丢掉的元素、属性逐项报错（`<text>`、`<image>`、`<use>`、`<mask>`、`class`、外部引用、任何 `style` 属性、值里带反斜杠的属性……）。图卡里不能有 CSS：`style` 写在哪个元素上都会被整个丢掉，导入时也一样，只是导入不会告诉你。
2. 用仓库自己的结构校验：`wd.images.memo.check_structure`——viewBox、两层及其顺序、`wa-…` 路径按序号拼出的正是这个词、不超过 60 KB、模糊预算（带 `filter` 的元素不超过 16 个；一个 `<filter>` 里的 `feGaussianBlur` / `feDropShadow` 不超过 3 个，实际只用 1 个；`stdDeviation` 是一两个 0–60 的普通数字）、单词层能被整层切掉，并且切掉之后的画面不依赖单词层里定义的东西（场景用的渐变、滤镜、裁剪路径都放在根的 `<defs>` 里）。这就是导入时的那道门，这里过了导入就不会被拒。
3. 只有这里能查的（这里有字体）：
   - 每个字母的 `d` 确实是 Andika 的字形（手改一个点就不行）；
   - 字形贴上去之后没有被 `transform` 弄走样：字母和它外层各组的 `transform` 合起来，只能是平移、等比缩放和小角度倾斜——5° 以内不提示，5°–15° 给警告，超过 15° 报错；镜像、上下翻转、两个方向缩放比例不同、斜切一律报错。这里只看属性就够了：能做同样事情的 `style` 在第 1 步已经被丢掉并报了错；
   - 字母画得出来：填充和描边沿着外层的组继承着看（自己 `fill="none"`、靠外层组的虚线描边的幽灵字母是合格的）；既没填充也没描边、`opacity="0"`、`display="none"`、`visibility="hidden"`、放在 `<defs>` / `<clipPath>` 里的，报「invisible letter」；
   - 不出画布：按字母墨迹的外框量（不是按中心点），出了 800×500 报错，离边不到 20 px 给警告；报告里的 `word_art.ink_bbox` 是整个单词的墨迹外框；
   - 字母从左到右、不小于 64 px（小于 76 px 给警告）；
   - i / j 的点：`wa-<序号>-i-dot` 必须就是字体里的那个点、在原来的位置、和字母一起移动、画得出来，才算「有点」；被改形、挪走、藏起来或清空的，照样给「dotless glyph」警告（只是警告——可以用画出来的东西顶替这个点，要看渲染图确认）；
   - 另外查重复的 id、指向不存在 id 的 `url(#…)`；带模糊滤镜的元素超过 14 个给警告（超过 16 个是第 2 步的错误，导入会拒绝）。
4. 用无界面的 Chrome 渲染。整图、对照图（sheet）、每张放大图，哪一张没渲染出来都算错误（`render failed: …`，退出码 1），报告的 `zoom_pngs` 只列真正写出来的文件——重跑一次即可。

已知的小毛病：机器很忙的时候，Chrome 偶尔会在画完之前截图，渲染图上本该有画面的地方出现一条边缘整齐的空白带（沿着 Chrome 256 px 的渲染分块）。这是截图的问题，不是图的问题，重跑一次就好。

### tools/build_gallery —— 总览页

```sh
studio/tools/build_gallery                                  # studio/cards + studio/manifest.json → studio/tmp/gallery/memory-cards.html
studio/tools/build_gallery --cards studio/tmp/batch-01/cards --manifest studio/tmp/batch-01/manifest.json \
                           --out studio/tmp/batch-01/gallery.html --title "记忆图卡 · 第一批"
```

把清单里的每张图清洗后内嵌进**一个**网页：每张图下面是它的三句话，页面上方的开关（或者点图）可以在「显示单词 / 只看画面」之间切换。直接用浏览器打开，或者发布成 claude.ai 的 Artifact 给 sqin 看。输出在 `studio/tmp/` 下，不要提交。

## 6. 加图，导入

1. 定稿的图放进 `studio/cards/<lemma>.svg`。文件名是词库里的 **lemma**（小写；空格写成 `_`，比如 `ice_cream.svg`）。
2. 在 `studio/manifest.json` 的 `cards` 里加一项，键是 lemma：

   ```json
   {
     "prompt_version": "memo-1",
     "model": "claude-fable-5-2",
     "cards": {
       "moon": {"alt_zh": "中秋夜的湖边，朵朵指着……", "hook_zh": "两个 o 像两轮圆月：……", "note_zh": "注意：book、look 里的 oo 读短音 /ʊ/。"}
     }
   }
   ```

   `prompt_version` 是画法版本（这一代是 `memo-1`；画风规则有实质变化时才升），`model` 是做图的模型。注意一份清单只有一个 `model`：如果后面的批次换了模型，就得另写一份清单、图也另放一个目录（导入时 `DIR` 和 `--manifest` 指过去即可，撤回时也要逐份清单执行）；自测目前只认 `studio/cards/` + `studio/manifest.json` 这一对，到时候要相应扩一下。
3. `make studio-check`（或 §4 的 pytest 命令）：自测会把 `studio/cards/` 里的每张图都过一遍校验，并核对清单和图一一对应、三句话没超长。
4. 导入。**导入会替换线上这些词正在用的图**，所以先得到 sqin 的同意，并且先空跑一遍。在跑 word-Dance 的那台机器上，用和 `wd backup`、`wd images-retry` 相同的方式运行（同一个 `wd`、同一份环境变量）：

   ```sh
   wd images-import studio/cards --manifest studio/manifest.json --dry-run     # 只校验，不写入；看汇总里有没有 rejected
   wd images-import studio/cards --manifest studio/manifest.json               # 真导入
   wd images-import studio/cards --manifest studio/manifest.json --only moon rain   # 只导其中几个
   ```

   逐词处理：找不到这个 lemma（或者它不是公开词）→ 拒绝并跳过；清洗、结构校验不过 → 拒绝并说明原因；和正在用的图完全相同 → `unchanged`（三句话有改动会更新；`images/` 里它的文件丢了会原样补回）；这张图是管理员处理反馈时撤下的 → `retired`，不动它，要恢复就用 `--only <词>` 点名；否则换上新图，旧图标成 `superseded`，文件保留；存盘失败（磁盘满、数据库锁住）→ 这一张 `rejected: could not store`，后面的照常处理。最后打印汇总；有 `rejected` 时退出码是 1。清单本身有问题时整份拒绝、退出码 2：两个键指向同一个词（`moon` 和 `Moon`），或者里面有半个代理对这类存不了的字符。需要数据库已经迁移到带记忆图卡的版本（`wd migrate`）。

## 7. 撤回

```sh
wd images-import --undo studio/manifest.json --dry-run     # 先看会发生什么
wd images-import --undo studio/manifest.json               # 清单里每个词：在用的若是记忆图卡，就撤下，换回它之前的那张图
wd images-import --undo studio/manifest.json --only moon   # 只撤一个
```

撤下的记忆图卡标成 `superseded`（文件还在），这个词回到图卡到来时的样子：最近一张不是记忆图卡的旧图重新启用；那张旧图要是被反馈撤下了（`rejected`）、之后一直没有新图，或者根本没有旧图，就回到模板卡——更早的图不会被翻出来。在用的不是记忆图卡的词不受影响（包括图卡已经被管理员撤下的词）。撤回之后想再上，重新导入即可。

`studio/` 里的文件本身是普通的 git 文件：改坏了一张图或一句话，用 git 找回。

## 8. 字体许可

字母字形来自 **Andika Bold**（版本 6.101，© 2004–2022 SIL International），许可是 **SIL Open Font License 1.1**，全文在 `studio/fonts/OFL.txt`。OFL 允许把字形转成路径嵌进图里，也允许商用；字体文件随仓库分发时必须带着许可全文（就是这个 `OFL.txt`），不能单独出售字体本身；「Andika」「SIL」是保留字体名，改过的字体不能再叫这个名字（我们没有改字体）。App 的许可页和 `ATTRIBUTION.md` 里各有一条说明。

工具里的字体文件名是常量：`studio/tools/letters.py` 的 `DEFAULT_FONT`。这一代图卡（`memo-1`）的所有字母都出自这一个文件——换字体等于换画法版本，`check` 也会把旧图全部判为「不是这个字形」。

## 9. 没有收进仓库的东西

下面这些留在归档里：`/Users/sqin/word-dance-memory-cards/studio-20261112.tgz`（约 52 MB，2026-11-12 晚的完整制作现场；在仓库之外，记得和别的备份一起保存）。

- **渲染图**（`png/`、`clean/`、人物设定图的 PNG）：随时可以用 `tools/check` 重新生成。
- **每张图的生成脚本**（归档里的 `work/<词>/`）：10 张样例各有一个 Python 脚本，是当时反复修改的工作稿；定稿以 `studio/cards/*.svg` 为准。
- **试画 A（晨光水彩）、C（叠层剪纸）** 的全部文件，以及试画 B（光影动画）的图和脚本——仓库里只留了 B 的技术配方 `pilots/B/STYLE.md`。
- **人物设定的生成脚本**（`cast/build.py`、`mkmd.py`、`variants.py`、`mdtest.py`）和另外两张测试图（卡片尺寸测试、服装变体）：`CAST.md` 和 `sheet.svg` 是它们的产物，已在仓库里。
- **过程材料**：10 个词的资料（`briefs/`）、被替换的旧图（`old/`）、评审返修之前的初版（`v1/`）、每张图的制作记录和返修记录（`results.json`、`fixes.json`——清单里的三句话就是从这两个文件加上评审后的改稿 `gallery_meta.json` 合出来的）、样例总览页。样例总览页发布在 https://claude.ai/artifact/3acU1BTa31mKCYExE3tDyu 。
- 选字体时试过的其他字体文件。

既不在仓库、也不在归档里的：评审时各自重新渲染的图和校验输出（当时的 `review/` 目录，都能重新生成；评审的结论已经落在返修记录、`STYLE.md` 和定稿的图里），以及 11-13 批量画法试验的现场和前 100 个词的工作文件——它们在做图的那个工作区的 `studio/tmp/` 下（不进 git，见 §2、§3）；试验的结论已经写在 §3 和 `LESSONS.md` 里。
