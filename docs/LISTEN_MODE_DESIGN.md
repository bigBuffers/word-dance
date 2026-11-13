# word-Dance：「磨耳朵」—— 只靠听也能学今日词汇（设计稿 v0.1）

> 日期：2026-11-12 · 代码基线：`main` @ `bba38fd` · 应 sqin 的要求由 Claude 撰写 · 状态：**v0.1，已按本文实现（分支 `listen-mode`，未提交）并回写了实现时的修订（文中标「修订」）；独立评审确认的 16 处问题和真机浏览器实测发现的 1 处（重启后头几秒的 `audio_zh`）也已改完并回写（同样标「修订」，其中一处只记为已知限制：§7.10）；2026-11-13 sqin 确认：「用磨耳朵 上线」——D1 定为「磨耳朵」，D2–D6 按默认值**。发布说明：`docs/releases/2026-11-listen-mode.md`
>
> 你的话：针对今日词汇，增加一种以播放听力为主的学习方式，比如增加一个跟「继续学习」并行的按钮「听力学习」（名字可以给更好的建议），点击后自动播放今日词汇，每个单词播放一个例句，英文中文先后播放，让学习者在只能听的情况下可以继续学习；并且可以选择去掉例句跟中文播放，这样就变成默写模式。
>
> 代码事实来自对 `backend/wd` 与 `frontend/src` 的只读核对（四份摸底报告，文中给出文件与行号）。「已实测」指 2026-11-12 在这台 Mac 上跑过。

## 0. 一页结论

- **入口**：今日页「开始学习 / 继续学习」下面加一个按钮 **「磨耳朵」**，进入 `/listen`。有今日词汇就显示，今天学完了也显示（修订：今天的词全都已掌握或已移出生词库时不显示——点进去会是空列表，§3.1）。
- **两档**：**跟着听**（单词 → 中文意思 → 例句 → 例句中文，例句和中文各有开关）和 **听写**（只读单词，默认读两遍、每遍后留 5 秒，屏幕不显示单词，播完给「对答案」清单）。你说的「默写模式」在这里叫「听写」。
- **不改学习记录**：磨耳朵不打分、不动复习间隔、不算连续学习天数。数据库没有任何变更。
- **中文从哪来**：今天服务器的发音接口只收英文，家里的鸿蒙平板又没有任何本机语音，所以**中文必须由服务器读**。本期给 `GET /media/audio` 加 `accent=zh-CN`，在这台 Mac 上用系统自带的中文语音 Tingting（已实测可用，约 0.5 秒一条）。
- **连播靠什么**：磨耳朵优先播服务器的音频（一个 `<audio>` 连着播，各设备声音一致，手机锁屏后浏览器里也能继续）；服务器给不出某一段时退回设备自己的语音，都读不了就跳过这一段，不卡住；修订：连不上服务器、设备自己也读不了时不跳，停在当前这个词并提示「连不上服务器，点播放再试一次」（否则剩下的词会在一两秒内被跳完，听写会提前跳到对答案）。
- **已知限制**（§7）：局域网 `http://` 下浏览器不允许网页保持屏幕常亮，平板会按系统设置熄屏；熄屏后 APK 里是否继续播放没有在真机上验证过。本期不改 APK。修订（评审后）：iPhone / iPad 的浏览器里，服务器不读中文时轮到手机自己的语音，而 iOS 不让网页在点击之外开始朗读——这些中文段没有声音，直到有一下点击把朗读解锁（§7.10；这台 Mac 自己读中文，今天只在一条中文音频失败之后才会碰到）。

## 1. 需要你决定的事（都有默认值，不拦着开发）—— 2026-11-13 已定：D1「磨耳朵」，其余按默认

| # | 事项 | 默认 | 备选 |
|---|---|---|---|
| D1 | 按钮名字 | **磨耳朵**（家长圈对「听英语」的常用说法） | 听着学 / 随身听 / 听力学习 |
| D2 | 播哪些词 | 今日词汇里的复习、新词、加练；一个词只播一次；推荐词（还没进生词库）不播；已标「掌握」的不播（修订：按词现在的状态——已掌握、已认识、已移出生词库的都不播，§3.2）；今天已经学过的照样播 | 只播还没学的 |
| D3 | 跟着听的顺序 | 单词 → 中文意思 → 例句 → 例句中文 | 结尾再读一遍单词 |
| D4 | 听写的节奏 | 每词读 2 遍，每遍后停 5 秒（可选 1–3 遍、3 / 5 / 8 / 12 秒） | — |
| D5 | 是否计入学习 | 不计入 | 计入「今日听了 N 个词」（需要加表，另做） |
| D6 | 选项存哪 | 存在这台设备上（平板和手机可以各用各的） | 跟账号走（需要数据库加列） |

## 2. 现状（代码事实）

1. **今日页**（`frontend/src/pages/TodayPage.tsx:214-228`）：主按钮是一个 `<Link>`，文案 `counts.done > 0 ? 继续学习 : 开始学习`，学完后换成「今日完成」卡片；没有批次时没有学习按钮。
2. **词汇数据**（`backend/wd/services/batches.py:538-607`）：`GET /api/today` 一次返回全部条目和内容（释义、2–4 个例句及中文）。条目可能重复（推荐词点了「不熟悉」后会再追加一条 `new`），顺序是学习顺序。
3. **释义文本不是为朗读写的**：`meaning_zh` 形如 `v. 分享；共用 n. 一份；股份`、`adv./prep. 在船(飞机、车)上`、`国内生产总值（gross domestic product 的缩写）`；没有内容时回退到词典行 `n. 能力, 才干`（`backend/wd/ai/content.py:238-312`、`backend/wd/ai/dance.py:44-99`）。
4. **发音三条路**（`frontend/src/hooks/useSpeech.ts`）：原生插件 / 浏览器语音 / 服务器音频，都只认 `en-US`、`en-GB`；浏览器语音这条路没有「读完了」的信号（`pronounce` 立即返回），没法直接用来连播。
5. **服务器音频**（`backend/wd/audio.py`、`routers/audio.py`）：`TEXT_RE` 只放行拉丁字母，中文 400；`ACCENTS = ("en-US","en-GB")`；每用户每分钟 60 次未命中、2 个合成槽。顺序连播一分钟约 20–30 次未命中，不会被限流；一次性预取会。
6. **已实测（这台 Mac，macOS 26）**：
   - 中文语音只有 `Tingting`（`zh_CN`，普通档）；`say -v Tingting` 读「你好，世界」得到 62 KB 的 AIFF。
   - 英文语音读中文不报错，输出 4608 字节的空音频（`Ava (Premium)` 读「月亮」）。现有的 `MIN_CLIP_BYTES = 256` 拦不住。
   - `Tingting` 恰好是系统的回退语音，所以现有的「和不存在的语音名比较」的探测（`say_resolves`）会把它判成「没解析到」。
   - 最短的真实音频：「好」19 KB、英文 `a` 17 KB。
7. **设备**（`docs/MOBILE_APP.md`、`docs/releases/2026-11-server-audio.md`）：鸿蒙平板的 APK 容器里原生语音永远 `UNAVAILABLE`、WebView 没有 `speechSynthesis`，只有服务器音频能出声；Capacitor 的 WebView 播放不需要手势（`Bridge.java:592`）；站点 CSP 没有 `media-src`，音频只能是同源 URL；没有 Wake Lock、Media Session、后台播放的任何代码；网页 Wake Lock 需要 https。

## 3. 产品规格

### 3.1 入口
- 今日页有批次、且批次里至少有一个不是推荐词并且仍在生词库里的条目时（`batch.items.some(it => it.kind !== 'screen' && (it.mine?.state === 'new' || it.mine?.state === 'learning'))`，和 §3.2 播放列表同一条规则：看词现在的状态，不看评分。修订：原先按 `counts.review + counts.new + counts.extra > 0` 判断，这三个计数是按条目数的，今天的词全部标了「掌握」时入口还在、点进去是空列表），在主按钮下方显示次级按钮「磨耳朵」（`btn--secondary btn--lg btn--block`），链接 `/listen`；「今日完成」卡片里也有一个。
- `/listen` 是 `RequireOnboarded` 下的整屏页面（和 `/study` 一样进 `BARE_ROUTES`，不显示底部导航）。

### 3.2 播放列表
- 今天的批次（`building` / `ready` / `published`），沿用今日页的过期条目规则（`hide_stale`）。
- 只取 `review` / `new` / `extra`；词现在已不在生词库里的不取（`user_words.state` 不是 `new` / `learning`：已掌握、已认识、已移出。修订：原先写的是「`result == 'master'` 的不取」，现在看词当前的状态、不看条目的评分——评完分之后又在单词页标「已掌握」或移出的词也不播；重新加回生词库的词回到列表，`done` 照它的条目）；按 `position, id` 排序；同一个 `word_id` 只保留第一条。
- 每个词给出：要读的英文（`spoken_en`）、屏幕上的释义（`meaning_zh`）、能读出来的中文短释义（`gloss_zh`）、一个例句和它的中文。

### 3.3 跟着听
- 每个词依次：**单词**（英文）→ **中文意思**（开了「中文」且有 `gloss_zh`）→ **例句**（开了「例句」且有例句）→ **例句中文**（两个开关都开且有译文）。
- 段与段之间停 350 ms，词与词之间停 900 ms。
- 屏幕显示当前单词、音标、释义、例句和译文，正在读的那一段高亮。
- 两个开关都关 = 只连读单词（不留书写时间，屏幕仍显示单词）。

### 3.4 听写
- 每个词：读单词，停 `间隔` 秒；共读 `遍数` 遍。不读中文，不读例句。
- 屏幕**不显示单词**，只显示「第 i / n 个」和提示。
- 播完进入「对答案」：序号、单词（可点读）、释义；按钮「再听写一遍」「回到今日」（修订：沿用已有文案 `common.backToToday`，不另加一条）。修订：这一遍里单词一次都没有完整读出来的词（读不出来、没有 `spoken_en`、被「下一个」跳过）带灰色标记「没读」（`listen.unread`），对答案的人知道纸上该跳过哪一行；失败过一次、后来又读出来的不带。
- 遍数 1 / 2 / 3（默认 2），间隔 3 / 5 / 8 / 12 秒（默认 5）。

### 3.5 控制
- 进入页面后自动开始。浏览器因为没有手势而拒绝播放时（iOS Safari），停在暂停状态并提示「点一下开始播放」。修订：浏览器自己把声音停掉时（来电、别的 App 抢走音频焦点、拔耳机）同样停在这个状态，点一下从当前词重新读——原先页面一直显示「暂停」，却没有声音（§7.11）。
- 修订：连不上服务器而设备自己也读不了时，停在当前词（暂停状态，不计入「没能读出来」）并提示「连不上服务器，点播放再试一次」；普通的服务重启（2–3 秒）由重试自动度过，不需要点（§6.1）。
- 修订：加载失败的页面保留顶栏的「回到今日」（整屏页面没有导航，否则只剩「重试」）。
- 修订：播完时如果键盘焦点因为控制条消失而落到 `<body>`，焦点移到结束页的标题（「对答案」/「听完了」）；焦点还在模式、遍数 / 间隔上时不动。
- 上一个 / 播放·暂停 / 下一个；进度「i / n」和进度条；「重新开始」。
- 暂停后继续 = 从当前词的第一段重新读。切换模式或选项 = 从当前词重新读。
- 键盘：空格 播放·暂停，← / → 上一个 / 下一个。
- 耳机线控和锁屏控件：有 Media Session 的浏览器里注册 play / pause / previoustrack / nexttrack（听写模式下标题不写单词）。
- 播放期间申请屏幕常亮（`navigator.wakeLock`，有才用，页面回到前台时重新申请）。
- 离开页面时停止播放。页面切到后台时**不**暂停。

### 3.6 语速
英文沿用 `DEFAULT_RATE = 0.92`，中文 1.0。本期没有语速选项。

### 3.7 文案（`zh.ts` 新增 `listen` 块，`today` 加一项）
`today.listen: '磨耳朵'`；`listen.title: '磨耳朵'`、`modes: { follow: '跟着听', dictation: '听写' }`、`optSentence: '例句'`、`optZh: '中文'`、`optRepeat: '每词读'`、`repeats(n) => `${n} 遍``、`optGap: '间隔'`、`gaps(n) => `${n} 秒``、`play: '播放'`、`pause: '暂停'`、`prev: '上一个'`、`next: '下一个'`、`restart: '重新开始'`、`position(i, n) => `${i} / ${n}``、`dictationIndex(i) => `第 ${i} 个``、`dictationHint: '听到单词后写下来'`、`tapToStart: '点一下开始播放'`、`finished: '听完了'`、`again: '再听一遍'`、`answers: '对答案'`、`dictateAgain: '再听写一遍'`、`empty: '今天还没有可以听的词'`、`noVoice: '这台设备现在读不出声音'`、`noZh: '这台设备读不了中文，只播放英文'`、`offline: '连不上服务器，点播放再试一次'`（修订，§3.5）、`skipped(n) => `有 ${n} 段没能读出来``、`unread: '没读'`（修订，§3.4）、`goStudy: '去学习'`。实现时可以微调措辞，但 `zh.ts` 与 FRONTEND §8 必须一致。

## 4. 接口与契约

### 4.1 `GET /media/audio`（76）扩展
- `accent` 接受 `en-US`（默认）、`en-GB`、**`zh-CN`**。`zh-CN` 选中文语音；学习者的口音设置（`user_settings.accent`）仍只有两个英文值。
- `zh-CN` 的文本规则：空白折叠后 1–300 个字符，**至少一个汉字**，只含汉字、中文标点（，。！？；：、（）《》「」『』【】…—～·“”‘’）、六个数量符号 `℃ ° ％ ￥ ¥ 〇`（修订：已实测 Tingting 把它们读成对应的词，「30℃」与「30摄氏度」逐字节相同，「￥20」即「20元」，「二〇〇八年」即「二零零八年」——原先带这些符号的例句译文会整句被丢掉；它们不算汉字，文本里仍须另有至少一个汉字；`+` `=` `~` 仍然拒绝——语音会吞掉或跳过它们，§4.3 的短释义也靠这条规则丢掉 `A+级` 这样的义项）以及英文规则允许的字符（译文里会夹 `Tom`、`GDP`、数字）。不满足 → 400 `validation_error`（`details.fields.text`）。
- 服务器没有中文语音（或提供方不支持中文）→ 503 `audio_unavailable {reason: "failed"}`；`cache` 提供方没有这条 → `{reason: "missing"}`（现有语义）。
- 缓存键不变：`sha256(provider \n voice \n accent \n text)`，`accent` 为 `zh-CN`。
- 限流不变（未命中计入 `audio:user:<id>`，60 次 / 分钟）。

### 4.2 `ServerFlags.audio_zh: boolean`
`GET /media/audio` 现在能读中文：提供方是 `say` 且中文语音已解析到名字，或者还没解析完。修订（真机浏览器实测后；原先是「解析尚未完成时为 `false`」）：解析尚未完成（启动后的头两三秒）时按乐观值给 `true`，除非本进程已缓存的 `say -v '?'` 列表里已经看得出没有可用的语音（没有 Eloquence 以外的 `zh_CN` 语音，或 `WD_AUDIO_SAY_VOICE_ZH` 不是列表里的中文语音）——页面只在加载时读一次 `/me`，鸿蒙平板没有本机语音，这几秒里读到 `false` 就整场没有中文。不阻塞 `/me`，也不调用 `say`。代价：没有中文语音的 Mac 上，这几秒里打开的页面会要一次中文、得到 503 `failed`，之后本次会话不再向服务器要中文。解析完成后就是确定值；其他提供方本期恒为 `false`。

### 4.3 新接口 123 `GET /api/today/playlist`（auth `O`，无副作用）
```ts
export interface ListenItem {
  item_id: number; word_id: number; kind: ItemKind; done: boolean;   // kind: review | new | extra (推荐词 are not listened to); done: the item has its final grade
  display: string; phonetic: string | null;
  spoken_en: string | null;             // what to speak for the headword (`sb.` / `sth.` spelled out); null when endpoint 76 would refuse the text
  meaning_zh: string;                   // shown on the player and on the 听写 answer sheet: content.meaning_zh, else the dictionary's main sense ('' when neither exists)
  gloss_zh: string | null;              // speakable Chinese gloss: at most two senses, no part-of-speech labels, no brackets; null when none can be derived
  sentence_en: string | null; sentence_zh: string | null;   // one example sentence endpoint 76 accepts, and its translation (null when it cannot be spoken); both null without content
}
export interface ListenPlaylist { batch_id: number | null; local_date: string; items: ListenItem[] }   // endpoint 123: today's review / new / extra words in batch order, one row per word, without the words that have left the bank since (已掌握 / 已认识 / removed — the word's state now, not the item's grade); batch_id null = no batch today
```
`frontend/src/api/types.ts` 已经含有以上两个接口和 `ServerFlags.audio_zh`（2026-11-12 先行写入）；`docs/API.md` §9 必须与它逐字一致，`backend/wd/schemas.py` 的模型字段与之对应。`frontend/src/api/endpoints.ts` 已有 `// #123 GET /api/today/playlist` 的 `getListenPlaylist`。

**派生规则**（服务端，`backend/wd/services/listen.py`）：
- `spoken_en`：`display` 里的 `sb.` → `somebody`、`sth.` → `something`、`sb's` / `sb.'s` → `somebody's`；经 `audio.normalize_text(…, "en-US")` 通过才给出，否则 `null`。
- `meaning_zh`：`content.meaning_zh`，否则 `dance.dictionary_sense(word)`（按主词性挑词典行），都没有则 `''`。
- `gloss_zh`（修订：顺序与细节以实现为准，`docs/API.md` §9.1 同文）：先去掉各种括号及其内容（`（…）` `(...)` `[…]` `【…】` `<…>`，由内向外；圆括号全角半角混配的一对也算一对（`（…)`、`(…）`。修订：否则会被当成没闭合的括号，把本义项剩下的内容一起删掉）；被 `meaning_zh` 长度上限截断、没有闭合的括号连同它后面的内容一起去掉，到本义项结束）——本节第二个例子要求先去括号再切；再按 `；;`、换行、`，,、`、斜杠 `/` `／`（已实测：Tingting 会把斜杠读成「斜杠」）和词性组边界切成义项；每个义项去掉开头的词性标签：`n.` `v.` `a.`，以及任何 2–7 个小写字母加点的缩写——`vt.` `vi.` `adj.` `adv.` `ad.` `prep.` `conj.` `pron.` `num.` `int.` `interj.` `art.` `aux.` `det.` `abbr.` `pl.`、词典行里的 `na.` `un.` `pref.` `suf.`，以及模型按同样写法写出的其他标签（`phr.` `excl.` 等：全库内容已经生成，标签无法穷举，漏掉一个就会被读成「p h r 照顾」）；含 `adv./prep.`、`vt.vi.` 这种并列；`sb.` / `sth.`、首字母大写的缩写（`Mr.`）和 `a.m.` 不算标签；去掉首尾的标点和符号；中文文本规则不接受的义项（不含汉字，或夹着 `+` `=` 之类的符号）单独丢弃；去重；取前 2 个用「，」连接；总长不超过 40 个字符（超了只留第一个义项，再超则截到 40）；最后必须通过中文文本规则，否则 `null`。
  例：`v. 分享；共用 n. 一份；股份` → `分享，共用`；`adv./prep. 在船(飞机、车)上;上船(车、飞机)` → `在船上，上船`；`国内生产总值（gross domestic product 的缩写）` → `国内生产总值`；`n. 能力, 才干` → `能力，才干`；`pron. 他/她/它的` → `他，她`；`phr. 照顾；照料` → `照顾，照料`；`vt. 使（某人)高兴, 取悦` → `使高兴，取悦`（修订：混配的括号）。
- 例句：`content.examples` 里第一个 `en` 能通过英文规则的；它的 `zh` 能通过中文规则才给 `sentence_zh`。

## 5. 后端实现要点

### 5.1 `backend/wd/audio.py`
- `ZH = "zh-CN"`；`LANGS = (*ACCENTS, ZH)`。`ACCENTS` 的含义不变（英文口音；预生成、`audio-prewarm --accent`、`config.AUDIO_ACCENTS`、`WD_AUDIO_CACHE_VOICES` 的「两个都要有」校验都不动）。
- `normalize_text(text, lang="en-US")`：`lang == ZH` 走中文规则，其余不变（现有调用点不传 `lang`）。
- 中文选音 `say_voice_for(cfg, ZH)`：`WD_AUDIO_SAY_VOICE_ZH`（新配置，默认空）优先；否则在 `say -v '?'` 里 `lang == "zh_CN"` 的语音中挑档位最高的（Premium > Enhanced > 普通），同档按偏好名单（`Lili`、`Lilian`、`Yu-shu`、`Shanshan`、`Tingting`、`Ting-Ting`）再按名字。**不跨语言回退**：英文口音永远不会得到中文语音，反之亦然；`WD_AUDIO_SAY_VOICE` 只管英文。修订：① 不选 Eloquence 语音（`Eddy (中文（中国大陆）)`、Flo、Reed、Rocko、Sandy、Shelley、Grandma、Grandpa）——这台 Mac 把它们也列为 `zh_CN`，带括号的名字按档位会排在 Tingting 前面，而且能通过下面的探测；② `WD_AUDIO_SAY_VOICE_ZH` 还必须是 `say -v '?'` 列出的中文语音（语言标签以 `zh` 开头，台湾的 Meijia、香港的 Sinji 也算）而且不是 Eloquence 语音，不合格就不探测、直接算没有中文语音（503 `failed`）——已实测三种情况光靠大小探测都拦不住：拼错的名字、列表里 `zh_CN` 的 Eloquence 名字（`Flo (中文（中国大陆）)` 等，`say` 并不解析它们）都由回退语音 Tingting 读出来，逐字节相同；Fred / Albert / Kathy 这几个老的英文语音读中文不是空音频，而是 8–11 秒的噪音（评审后的修订：原先只要求「是列出的名字」）。
- 中文探测 `say_speaks_zh(cfg, name)`：用候选语音读 `ZH_PROBE_TEXT = "你好，世界"`，AIFF ≥ `SILENT_AIFF_BYTES = 8192` 才算能读中文（英文语音读中文是 4608 字节的空音频）。不和「不存在的语音名」比较——系统回退语音本身就是中文语音时那种比较会误判。探测结果按 `(name, text)` 缓存，每进程一次。
- 没有中文语音是**已解析的否定结果**（缓存空串），`audio_key` 因此稳定（修订：`say -v '?'` 本身读不出来不算结论，不缓存，下次再试，和英文一致）；`AudioError("failed", …)` 的提示写明去「系统设置 → 辅助功能 → 朗读内容」下载中文语音或设 `WD_AUDIO_SAY_VOICE_ZH`。
- 合成防线：`lang == ZH` 时，`say` 产出的 AIFF 小于 `SILENT_AIFF_BYTES` → `AudioError("failed", "silent clip")`，不写入缓存。
- `warm_up`：英文两个口音之后再解析中文；没有中文语音记一条 INFO（事件 `audio_voice_zh_missing`），不影响英文。修订：选中的中文语音也记一条 INFO，事件 `audio_voice_zh`。
- `voice_key`：`say` 提供方把中文语音（已解析的名字、空串或未解析占位）也算进去（一次性地让浏览器重新下载音频，服务器缓存不受影响）。
- `speaks_zh(cfg) -> bool`：只对 `say`。中文语音已解析为非空 → `True`；已解析为空 → `False`；尚未解析 → `True`（修订，§4.2；原先未解析返回 `False`），除非 `say -v '?'` 的列表已在本进程缓存且其中没有可用的语音（没有 Eloquence 以外的 `zh_CN` 语音；设了 `WD_AUDIO_SAY_VOICE_ZH` 时看它是不是列出的非 Eloquence 中文语音）。不阻塞、不调用 `say`（读列表缓存时不拿 `say_voices` 的锁，那把锁在 `say -v '?'` 运行期间一直被占着）。这时来要中文片段的请求自己完成解析（和英文一样），确实没有就答 503 `failed`。
- `locate`：`cache` / `bailian` / `youdao` 遇到 `zh-CN` 分别给 `missing` / `failed` / `failed`，不得 `KeyError`。
- CLI：`wd audio-voices` 多打一行中文语音（放在最后，不影响退出码）；`wd audio-probe --accent zh-CN "你好"` 可用（不给文本时读「今晚的月亮很亮。」）。`audio-prewarm` / `audio-texts` 本期不产生中文（§8）。
- `wd check providers`（`diag.py`）如有逐口音的输出，补一行中文，缺失不算 FAIL。修订：原来没有逐口音输出，现在除 `off` 外各提供方多一行 `audio zh-CN: …`，只看配置、不调用 `say`，永不 FAIL。

### 5.2 `backend/wd/routers/audio.py`
`accent not in audio.LANGS` → 400（「只支持 en-US、en-GB 或 zh-CN」）；`normalize_text(text, accent)`；中文文本的错误提示「1–300 个字符，需含汉字」。其余不变。

### 5.3 `backend/wd/services/listen.py`（新）与 `routers/today.py`
`speakable_gloss`、`spoken_headword`、`pick_sentence`、`playlist(conn, user_id, now, *, cfg)`；路由 `GET /api/today/playlist`（`require_onboarded`，`response_model=schemas.ListenPlaylist`）。复用 `batches.visible_items`、`batches.STUDY_KINDS`、`bank.today_batch`、`words.word_row` / `words.active_content`、`dance.dictionary_sense`、`dance._SENSE_SPLIT`（或在 `listen.py` 里放一个扩展了逗号的切分式）。

### 5.4 契约文件
`schemas.py`（`ListenItem`、`ListenPlaylist`、`ServerFlags.audio_zh`、`ENDPOINT_MODELS[123]`）、`routers/auth.py::server_flags`、`docs/API.md`（§2 目录行 123、§7 段落、§8 的 76 段落、§9 类型块、§9.1 字段说明）、`deploy/env.example` 与 `docs/DEPLOY.md` §4（`WD_AUDIO_SAY_VOICE_ZH`）、`backend/wd/config.py`。受这些文件约束的测试：`test_api_schemas.py`、`test_docs_contract.py`、`integration/test_auth.py`（`server` 字典逐项断言）、`test_config.py`。

### 5.5 后端测试
- `test_audio.py`：中文文本规则（通过 / 拒绝表）、中文选音与档位、探测（含「回退语音就是中文语音」的情形）、英文语音读中文被拒、空音频不入缓存、无中文语音时 `audio_key` 稳定、`speaks_zh`、英文口音不回退到中文语音。`conftest.fake_say` 需要能产出「够大」的 AIFF（中文语音读中文）和「空」AIFF（英文语音读中文）。修订：覆盖项必须是列出的非 Eloquence 中文语音（`fake_say(noisy=…)`：读中文写出大文件的英文语音）；六个数量符号放行而 `+` `=` `~` 仍拒绝；`speaks_zh` 未解析时乐观、不调用 `say`、不等正在读的列表。
- `test_audio_api.py`：`accent=zh-CN` 命中 / 未命中、无中文语音 503 `failed`、文本 400、限流照旧；原有「`你好` 被拒」的用例改成「英文口音下被拒」。修订：解析完成之前 `/me` 的 `audio_zh` 为真且不启动任何进程、第一条中文片段 200；没有中文语音时乐观的 `audio_zh` 换来一次 503 `failed`，之后为假。
- 新 `test_listen.py`（unit）：`speakable_gloss` 表（修订：含混配括号的四行）、`spoken_headword`、`pick_sentence`；`playlist`：去重、不含推荐词、不含 `master`（修订：按词当前的状态——评分之后标「已掌握」/ 移出 / 已认识的不在，重新加回的在）、过期条目隐藏、无批次、内容为空时的回退。
- `integration/test_today_flow.py`（或新文件）：123 的鉴权（401 / 409 `onboarding_required`）与形状。

## 6. 前端实现要点

### 6.1 语音底层
- `audio/serverAudio.ts`：`type SpeechLang = Accent | 'zh-CN'`（`Accent` 仍从 `useSpeech` 来）；`clipUrl` / `playServerAudio` / `diagnose` 的 `accent` 参数放宽为 `SpeechLang`；`setServerAudio(on, key, zh?)` 记录 `audio_zh`；`serverAudioSpeaks(lang)`：英文 = `enabled`，中文 = `enabled && zh && !zhOff`；一条中文音频以 `failed` / `invalid` 失败后本次会话 `zhOff = true`（不再为中文敲服务器）。`AuthContext.loadMe` 传入 `me.server.audio_zh`。现有英文行为与测试不变。修订：`ServerAudioReason` 加 `'paused'`——当前这条音频播放途中元素被浏览器自己暂停（`pause` 事件到达时 `paused` 为真且 `ended` 为假；自然播完前的那次 `pause`、上一条被 `stopServerAudio()` 暂停后迟到的 `pause` 都不算）；`play()` 之后 `STALL_MS = 20 秒` 内没有等到 `playing` 事件就以 `network` 拒绝（请求挂住、既不出声也不报错；不做诊断请求）。原先这两种情况下 `playServerAudio` 的 Promise 永远不结束，页面一直显示「暂停」却没有声音。`useSpeech` 对 `paused` 不弹提示。
- 新 `audio/utter.ts`：`utter(text, lang, rate): Promise<'ended' | 'unspoken' | 'blocked' | 'offline'>`（修订：加了 `'offline'`，见第 4 步）和 `stopUtter()`，给连播用的「读完再返回」：
  1. `serverAudioSpeaks(lang)` → `playServerAudio`；`busy` 等 1.5 秒重试一次；修订：`network`（音频取不到）每 1.5 秒再问一次，只在这一段开始后的 3 秒内问——最多再问两次，普通的服务重启到这时已经结束；挂到 20 秒看门狗才得到的 `network` 不再问；重试用尽之后、直到有一条音频播出来为止，后面的段各只问一次（长时间断网只等一次，不是每段都等）；`blocked`（没有手势）直接返回 `'blocked'`，修订：`paused` 也一样；其他失败落到下一条路。
  2. 原生壳（`isNative()`）→ `speakNative(text, lang, rate)`，拒绝则落到下一条路。
  3. 浏览器语音：英文用现有 `pickVoice`；中文挑 `lang` 以 `zh` 开头的语音（优先 `zh-CN` / `cmn`），列表非空却没有中文语音则不读。用 `onend` / `onerror` 收尾，外加看门狗（`4 s + 每字符 0.35 s`，上限 30 s）；保持对 utterance 的引用防止被回收。
  4. 都不行 → `'unspoken'`；修订：服务器这条路是以 `network` 或 `auth`（401）结束的、设备也没读出来 → `'offline'`（不是这一段读不了，而是服务器问不到：下一段也一样，调用方不该跳过）。设备读出来了照旧是 `'ended'`。
  被 `stopUtter()` 或下一次 `utter` 打断时以 `'ended'` 返回——调用方用自己的代次号判断是否还该继续。
  修订：另有 `utterAvailable(lang)`（现在有没有哪条路可能读这种语言——页面的「读不出声音」状态和 `noZh` 提示用它；原生壳在插件拒绝之前、语音列表还是空的时候都按「可能」算）；插件拒绝过的语言本次会话不再问它（错误码 `UNAVAILABLE` = 没有引擎，两种语言都不再问）；浏览器语音的 `onerror` 为 `not-allowed` 时返回 `'blocked'`，看门狗到点时已经开始读的算 `'ended'`、没开始的算 `'unspoken'`。
- `useSpeech.ts` 的对外行为不变（`SpeakButton`、自动发音照旧走设备优先）。

### 6.2 播放器 `listen/player.ts`（纯 TS，可单测）
- `ListenOptions { mode: 'follow' | 'dictation'; sentence: boolean; zh: boolean; repeat: 1 | 2 | 3; gapSec: 3 | 5 | 8 | 12 }`，默认 `{ follow, true, true, 2, 5 }`；`sanitizeOptions(unknown)`。
- `segmentsFor(item, options)`：跟着听 → `word`、`gloss`、`sentence`、`sentenceZh`（按 §3.3 的条件）；听写 → `word` × `repeat`，每个后面跟 `gapSec`。`spoken_en` 为 `null` 的词没有 `word` 段（跟着听里其余段照播；听写里整词跳过）。
- `class ListenPlayer`：依赖注入 `{ utter, stop, wait(ms, signal), onChange }`；`load(items, options)`、`play()`、`pause()`、`toggle()`、`next()`、`prev()`、`seek(i)`、`restart()`、`setOptions(o)`、`dispose()`；状态 `{ status: 'idle' | 'playing' | 'paused' | 'blocked' | 'finished'; index; segment: 'word' | 'gloss' | 'sentence' | 'sentenceZh' | 'gap' | null; round; unspoken; offline; unread }`（修订：后两项）。代次号保证暂停 / 跳转后旧链条不再推进；`utter` 返回 `'blocked'` → 状态 `blocked`（等用户点播放）。修订：`utter` 返回 `'offline'` → 停在当前词：状态 `paused`、`offline: true`，不计入 `unspoken`，`play()` 从这个词重新读；`offline` 在重新开始播放或播完时复位。`unread`：进入 `finished` 时给出这一遍里单词没有完整读出来过的词的下标——播放器记一个 `heard` 集合（`word` 段以 `ended` 结束时加入，`load()` / `restart()` / 结束页切换模式时清空）取补集，不从 `unspoken` 的集合推（那个集合不会因为后来读出来了而减少）。`setOptions(options, { reread: false })`：只换选项、不重读当前词（下面的修订）。`dispose()` 之后任何入口（上一个 / 下一个 / 跳转 / 改选项）都不再开始播放链——原先只有 `play()` / `restart()` 检查。
- 选项存 `useLocalPref('wd.listen', defaults)`。
- 修订（设计没写到、实现时定下的规则）：注入的 `utter` 是 `(text, 'en' | 'zh')`，口音和语速由页面映射（英文 = `settings.accent` × 0.92，中文 = `zh-CN` × 1.0）；读不出来的段后面不停顿，一个词一段都没读出来就不给词间停顿，听写里读不出来的词不再重读、不留书写时间；`unspoken` 按「不同的段」计数，重读同一个词不重复计，「重新开始」清零；最后一个词上按「下一个」= 播完；播完之后上一个 / 下一个 / 键盘不起作用（对答案页上耳机的播放键也不起作用）；在结束页切换模式回到第一个词但不自动播放，改遍数 / 间隔不收起答案；`setOptions` 只在改动确实影响当前模式读什么时才重读当前词。服务器和设备都读不了中文、而且事先看得出来时（`utterAvailable('zh-CN')` 为假），中文段事先就不进播放链（页面给播放器的 `zh` 为假，并显示 `noZh`），不是逐词尝试再计数。评审后的修订：事先看不出来的情形——App 壳在插件拒绝之前、浏览器的语音列表还是空的、服务器的中文音频中途失败（`zhOff`）——第一段中文会试一次；它失败之后页面显示 `noZh`，并用 `setOptions(effective, { reread: false })` 把不含中文的选项交给播放器：**当前词不重读**（原先会把当前词从头再读一遍，并留下一条「有 1 段没能读出来」），当前词剩下的中文段跳过，已经计入 `unspoken` 的中文段去掉。存下来的「中文」开关不改。

### 6.3 页面与入口
- `pages/ListenPage.tsx`（+ `.css`、`.test.tsx`）：`useApi(getListenPlaylist)`；骨架屏 / 错误重试 / 空状态；顶栏（返回今日、标题、进度）；模式 `Segmented`；选项（`Switch` × 2 或 `Segmented` × 2）；舞台（跟着听显示词与高亮段，听写只显示序号）；控制条（`useBottomBarOffset`）；结束页；`useKeyboard`；Wake Lock 与 Media Session 的小助手（`listen/screenAwake.ts`、`listen/mediaSession.ts`，特性探测，失败静默）；卸载时 `dispose()`。中文开着但 `!serverAudioSpeaks('zh-CN')` 且设备也没有中文语音时显示 `listen.noZh`。修订：错误重试的页面保留顶栏（「回到今日」）；对答案清单给 `state.unread` 里的行加「没读」标记；`state.offline` 时舞台上显示 `listen.offline`；播完时落到 `<body>` 的焦点移到结束页标题。
- `routes.tsx`：`listen: '/listen'` 与懒加载路由（`RequireOnboarded` 块内）；`AppLayout.BARE_ROUTES` 加 `/listen`；三处「已引导路由」清单同步（`routes.tsx:2-3`、`AuthContext.tsx:215`、FRONTEND §2 上方那句）。
- `TodayPage.tsx`：两处入口（§3.1，修订：按条目判断，不按计数）。
- `components/ui/icons.tsx`：播放、暂停、上一个、下一个。
- `i18n/zh.ts` 与 FRONTEND §8 同步。

### 6.4 前端测试
`audio/utter.test.ts`（路线顺序、回退、`blocked`、看门狗、中文选音）、`audio/serverAudio.test.ts`（`serverAudioSpeaks`、`zhOff`）、`listen/player.test.ts`（两种模式的段序列、暂停 / 继续、上一个 / 下一个、选项变更、读不出时跳过并计数、结束）、`pages/ListenPage.test.tsx`（自动开始、控制、听写不显示单词、对答案、空状态、`blocked` 提示）、`AppLayout.test.tsx`（`/listen` 无外壳）、15 个带 `ServerFlags` 夹具的测试文件按需补 `audio_zh`。修订：`audio/serverAudio.test.ts`（`paused` 及其两个判断条件、20 秒看门狗）、`audio/utter.test.ts` / `utter.server.test.ts`（`network` 重试、`offline`、`paused` → `blocked`、挂住的请求不重试）、`listen/player.test.ts`（`offline` 停在当前词、`unread`、`reread: false`、`dispose` 后各入口）、`pages/ListenPage.test.tsx`（中途发现读不了中文不重读、`offline` 提示、「没读」标记、错误页的「回到今日」、结束页焦点、暂停确实让声音停下）、`pages/TodayPage.test.tsx`（条目夹具，词全部离开生词库时没有入口）、`api/endpoints.test.ts`（123 的路径）。

## 7. 风险与已知限制

1. **熄屏**：局域网 `http://` 下 `navigator.wakeLock` 不可用，平板和手机会按系统设置熄屏。熄屏后：手机浏览器里的 `<audio>` 一般继续（定时器会变慢，段间停顿可能变长）；APK 容器里是否继续**未在真机验证**。临时办法是把平板的熄屏时间调长；根治办法是 https（Wake Lock 可用）或给 APK 加常亮 / 前台服务（要重新打包分发），都不在本期。
2. **中文音质**：Tingting 是普通档语音，夹在句子里的英文单词读得生硬。装更好的中文语音后重启服务即可自动换用（旧的中文音频会按新语音重新生成）。
3. **授权**：`say` 的语音（含中文）按 macOS 许可只能非商用，和英文语音同一条限制；商用要走百炼（本期不含百炼的中文）。
4. **首播延迟**：中文音频没有预生成，第一次播放每条约 0.5 秒合成时间；播过一次后走缓存。
5. **`cache` 提供方（将来的 Linux 服务器）**：没有中文音频，`audio_zh` 为假；那时中文只能靠设备语音，鸿蒙平板上会没有中文。上服务器前要先做中文预生成（§8）。
6. **释义朗读的边角**：规则派生的短释义偶尔不自然（如词典回退行）；派生不出来时这一段直接跳过，不会读出词性标签或括号内容。
7. **连播的真机行为**：WebView 里一个 `<audio>` 连续换源播放只从 Capacitor 源码得知，没有在平板上验证过；验收清单里有这一项。
8. **重启后的头几秒**（修订，集成时实测；真机浏览器实测后再修订——这个窗口现在关上了）：服务启动后约 2–3 秒内中文语音还没解析完，`audio_key` 还是占位值。原先这段时间 `audio_zh` 为假，这几秒内打开的页面要刷新一次才有服务器中文；现在 `audio_zh` 按乐观值为 `true`（§4.2），这几秒内打开的页面不用刷新就有服务器中文——第一条中文片段的请求自己把语音解析出来（实测一次约 1.3 秒）。代价只落在没有中文语音的服务器上：这样的页面会要一次中文、得到 503 `failed`，之后本次会话只读英文（设备自己有中文语音的照常由设备读）。`audio_key` 的占位值没有变：这几秒内加载的页面，音频 URL 带的是占位指纹，只影响浏览器缓存的命中，不影响播放。
9. **一条中文失败就整场关掉**（§6.1 的 `zhOff`）：服务器对任何一条中文音频回 `failed`（包括 `say` 偶发超时），这个页面直到刷新都不再向服务器要中文——平板上就是之后只有英文。先按设计保留，真机上出现过再改成「连续两条失败才关」。（修订：关掉时不再把当前词从头重读，也不计数，§6.2。）
10. **iOS 上点击之外的设备朗读**（评审确认的限制，未在真机验证，本期不改代码）：iOS 的 WebKit 只允许在用户点击的调用栈里开始 `speechSynthesis.speak()`（点击之外的 `speak()` 直接丢弃，没有任何事件；同一下点击里开始的 `<audio>` 播放不解除这条限制，只有点击里的一次 `speak()` 才解除）。磨耳朵的那一下点击只覆盖第一条服务器音频，之后轮到设备语音的段都发生在点击之外。也就是说：**服务器不读中文、而 iPhone / iPad 自己有中文语音时**（所以页面不会把中文去掉）——`audio_zh` 为假（没有中文语音的 Mac、`cache` 提供方），或一条中文音频失败之后的 `zhOff`（7.9）——这些中文段在 iPhone 的浏览器里**没有声音**，每段静默等到看门狗（4 秒 + 每字 0.35 秒，约 5–10 秒）后被当作没读出来跳过并计数，直到有一下点击把朗读解锁：本次打开网页后在任何地方点过一次 🔊（学习卡、单词页、对答案清单）之后就正常了。服务器完全没有发音提供方时同理，自动开始不会变成「点一下开始播放」，而是一段一段地超时；点一下暂停再点播放即可（`play()` 在点击里开始第一段朗读）。这台 Mac 自己读中文，重启后的头几秒也已经不再是 `audio_zh` 为假（7.8），所以今天只有 iPhone / iPad Safari 加上 `zhOff` 才会碰到；上 `cache` 提供方的服务器之后，这就是每个 iPhone Safari 用户的常态（见 7.5），那之前必须解决。修法有方案但要真机确认后才能上：在点击里顺手 `speak` 一条空的 `SpeechSynthesisUtterance` 解锁（要确认它不会压低或打断同一下点击里开始的 `<audio>`）；「第一条设备朗读从未开始」时返回 `blocked` 而不是 `unspoken`（必须和前一条一起上，否则会在 blocked → 点击 → 单词 → blocked 之间打转）。桌面 Safari、Chrome、App 壳（走插件）不受影响。
11. **浏览器自己暂停之后**（修订）：页面停在「点一下开始播放」；如果系统随后自己恢复了那个 `<audio>`（短暂的音频焦点丢失：一通很快挂断的电话、语音助手），这条音频剩下的部分会在页面仍显示「播放」时响完一次，然后不再往下读，要点一下——修订之前这种短暂的打断会自己接上，长久的打断（焦点被别的播放器拿走、iOS 上不恢复的打断）则卡死在「暂停」图标上；现在两种都是点一下继续。看门狗只管 20 秒内没有开始播放的音频；已经开始播放的音频中途断流靠浏览器的 `error` 事件，诊断请求本身没有超时。哪些设备会这样暂停没有在真机上确认，只在桌面 Chrome 里模拟过。
12. **连不上服务器时的边角**（修订，§6.1 / §6.2）：重试只覆盖 3 秒（第 0、1.5、3 秒各问一次），重启得比这慢就会停在当前词，点一下播放继续；有英文语音而没有中文语音的浏览器，断网时会停在第一段中文上（原先是只读英文、中文逐段计数）——想只听英文可以关掉「中文」；服务器搬到反向代理后面以后，重启期间代理答的是不带本应用错误信封的 502 / 504，现在会被当成 `failed`（中文还会因此 `zhOff`），到时要把它们映射成 `network`（本期线上是 `wd serve` 直接监听，重启就是连接被拒，不受影响）。

## 8. 本期不做

- 中文音频预生成（`wd audio-prewarm` / `audio-texts` 的中文文本）与 `cache` 提供方的中文。
- 百炼 / 有道的中文语音。
- 计入学习统计或连续天数；听写的批改与错词回写。
- 「昨天的词汇」、生词库任意词表的磨耳朵。
- 语速选项、循环播放、睡眠定时。
- APK 改动（常亮、后台播放、锁屏控件）。

## 9. 验收

- 门禁：`make test`（pytest、契约审计、类型检查、vitest、构建）与 `npm run lint` 全过（这台 Mac 上按惯例排除 `test_deploy_files.py` 和 `test_defaults_without_environment`）。
- 手工清单写入 `docs/qa-study.md`：电脑浏览器、手机浏览器、平板 APK 各走一遍跟着听和听写；平板上确认中文出声、连播不需要再点、熄屏后的表现记下来。
