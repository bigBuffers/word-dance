-- mini_stardict.sql — 110 verbatim rows of ECDICT stardict.db (release 1.0.28, MIT; data/licenses/ECDICT-LICENSE) with the real DDL,
-- for backend/tests/unit/test_seedbuild_build.py: `sqlite3.connect(':memory:').executescript(text)` gives build.Ecdict a database.
-- Rows cover every head/variant/phrase of the mini lists that must resolve, the PLAN §6 S3 set (Mr / Mr. / hot dog / hotdog / hot-dog /
-- excited / the Bund / humourous) and the exchange shapes R2 relies on (be, has 0:have/1:3, children 0:child/1:s, an 0:a).
-- Values are plain SQL string literals except the one CR byte ECDICT holds (row 7909 `a`, translation `…第一的\r\nart. …`): it is
-- spelled char(13, 10) so the file stays LF-only (.editorconfig) and a text-mode read (universal newlines) still loads the verbatim value.
CREATE TABLE "stardict" (
"id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL UNIQUE,
"word" VARCHAR(64) COLLATE NOCASE NOT NULL UNIQUE,
"sw" VARCHAR(64) COLLATE NOCASE NOT NULL,
"phonetic" VARCHAR(64),
"definition" TEXT,
"translation" TEXT,
"pos" VARCHAR(16),
"collins" INTEGER DEFAULT(0),
"oxford" INTEGER DEFAULT(0),
"tag" VARCHAR(64),
"bnc" INTEGER DEFAULT(NULL),
"frq" INTEGER DEFAULT(NULL),
"exchange" TEXT,
"detail" TEXT,
"audio" TEXT
);
CREATE INDEX "sd_1" ON stardict (word collate nocase);
CREATE UNIQUE INDEX "stardict_1" ON stardict (id);
CREATE UNIQUE INDEX "stardict_2" ON stardict (word);
CREATE INDEX "stardict_3" ON stardict (sw, word collate nocase);
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (7909, 'a', 'a', 'ei', 'n. the 1st letter of the Roman alphabet
n. the blood group whose red cells carry the A antigen', '第一个字母 A; 一个; 第一的' || char(13, 10) || 'art. [计] 累加器, 加法器, 地址, 振幅, 模拟, 区域, 面积, 汇编, 组件, 异步', 'a:99/t:1', 5, 1, 'zk gk', 5, 5, 's:some', '""', '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (8272, 'a bit', 'abit', '', '', '一点儿；有一点儿', '', NULL, 1, '', 0, 0, '', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (8282, 'a bit of', 'abitof', '', '', '一点', '', NULL, NULL, '', 0, 0, '', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (10879, 'a lot of', 'alotof', '', '', '许多的', '', NULL, NULL, '', 0, 0, '', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (15081, 'a.m.', 'am', '', 's before noon
r before noon', '上午, 午前', '', 2, NULL, '', 0, 0, NULL, NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (16425, 'abandon', 'abandon', 'ә''bændәn', 'n. the trait of lacking restraint or control; reckless freedom from inhibition or worry
v. forsake, leave behind
v. give up with the intent of never claiming again
v. stop maintaining or insisting on; of ideas or claims', 'vt. 放弃, 抛弃, 遗弃, 使屈从, 沉溺, 放纵
n. 放任, 无拘束, 狂热', 'n:4/v:96', 3, 1, 'gk cet4 cet6 ky toefl gre', 2057, 2182, 'd:abandoned/p:abandoned/i:abandoning/3:abandons/s:abandons', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (31028, 'according', 'according', 'ә''kɒ:diŋ', 's. (followed by `to'') in agreement with or accordant with
s. (followed by `to'') as reported or stated by', 'a. 相符的, 根据...而定的
adv. 相应地', 'i:99/c:1', NULL, NULL, '', 35013, 478, '0:accord/1:i/s:accordings', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (31032, 'according to', 'accordingto', '', '', '根据, 按照；取决于；据…所说', '', 5, 1, '', 0, 0, '', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (50800, 'add ... to', 'addto', NULL, NULL, 'na. 增加
[网络] 增添；增进；添加', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (110856, 'although', 'although', 'ɒ:l''ðou', 'conj. Grant all this; be it that; supposing that;
   notwithstanding; though.', 'conj. 虽然, 尽管', 'c:100', 5, 1, 'zk gk cet4 ky', 197, 378, '', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (113907, 'AM', 'am', 'æm', 'n a radioactive transuranic metallic element; discovered by bombarding uranium with helium atoms
n a master''s degree in arts and sciences
n modulation of the amplitude of the (radio) carrier wave
v have the quality of being; (copula, used with an adjective or a predicate noun)
v be identical to; be someone or something
v occupy a certain position or area; be somewhere
v have an existence, be extant
v happen, occur, take place; this was during the visit to my parents'' house"
v be identical or equivalent to
v form or compose
v work in a specific place, with a specific subject, or in a specific function
v represent, as of a character on stage
v spend or use time
v have life, be alive
v to remain unmolested, undisturbed, or uninterrupted -- used only in infinitive form
v be priced at', 'be的单数第一人称
[计] 存取管理程序, 寻址方式, 地址标记, 变址数, 调幅, 辅助存储器', 'r:100', NULL, NULL, 'gk', 3465, 1192, 's:ams', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (126858, 'an', 'an', 'æn', 'n an associate degree in nursing', 'art. 一', '', NULL, NULL, '', 30, 0, '0:a/s:some', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (178889, 'are', 'are', 'ɑ:', 'n. a unit of surface area equal to 100 square meters', 'be的现在时复数或第二人称单数', '', NULL, NULL, 'gk', 0, 0, 's:ares', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (207821, 'at first', 'atfirst', '', '', '起先', '', NULL, 1, '', 0, 0, '', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (207934, 'at last', 'atlast', '', '', '终于', '', NULL, NULL, '', 0, 0, '', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (282768, 'bce', 'bce', '', 'r. of the period before the Common Era; preferred by some writers who are not Christians', 'abbr. 化学工程学士（Bachelor of Chemical Engineering ）；土木工程学士（Bachelor of Civil Engineering）；公元前（ before common era）', '', NULL, NULL, '', 0, 0, '', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (283098, 'be', 'be', 'bi:', 'v. have the quality of being; (copula, used with an adjective or a predicate noun)
v. be identical to; be someone or something
v. occupy a certain position or area; be somewhere
v. happen, occur, take place; this was during the visit to my parents'' house"', 'v. 是, 表示, 在
[计] 后端, 总线允许', 'v:100', 5, 1, 'zk gk', 2, 2, 'p:was/3:is/d:been/i:being/s:bes', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (291490, 'bean curd', 'beancurd', '', '', '豆腐', '', NULL, NULL, '', 0, 0, 's:bean curds', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (297126, 'been', 'been', 'bi:n', 'v have the quality of being; (copula, used with an adjective or a predicate noun)
v be identical to; be someone or something
v occupy a certain position or area; be somewhere
v have an existence, be extant
v happen, occur, take place; this was during the visit to my parents'' house"
v be identical or equivalent to
v form or compose
v work in a specific place, with a specific subject, or in a specific function
v represent, as of a character on stage
v spend or use time
v have life, be alive
v to remain unmolested, undisturbed, or uninterrupted -- used only in infinitive form
v be priced at', 'be的过去分词', '', NULL, NULL, '', 0, 0, '1:d/0:be/s:beens', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (299769, 'Beijing opera', 'beijingopera', NULL, NULL, '[网络] 京剧；国戏；京戏', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (299849, 'being', 'being', '''bi:iŋ', 'n. the state or fact of existing', 'n. 存在, 性质, 生命, 人, 生物, be的现在分词', 'n:100', 3, NULL, 'gk cet4 ky', 1956, 1676, '1:i/0:be/s:beings', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (364643, 'book', 'book', 'buk', 'n. a written work or composition that has been published (printed on pages bound together)
n. physical objects consisting of a number of pages bound together
n. a collection of playing cards satisfying the rules of a card game
n. a collection of rules or prescribed standards on the basis of which decisions are made', 'n. 书, 书籍, 帐簿, 名册, 工作簿
v. 登记, 预订
[计] 工作簿', 'v:2/n:98', 5, 1, 'zk gk ielts', 235, 241, 's:books/d:booked/p:booked/i:booking/3:books', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (365610, 'bookshelf', 'bookshelf', '''bukʃelf', 'n. a shelf on which to keep books', 'n. 书架', 'n:100', 1, NULL, 'gk ielts', 22136, 11170, 's:bookshelves', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (387015, 'breakdown', 'breakdown', '''breikdaun', 'n. a mental or physical breakdown
n. a cessation of normal operation
n. an analysis into mutually exclusive categories', 'n. 崩溃, 故障
[化] 事故; 击穿', 'n:100', NULL, NULL, 'cet6 ky toefl ielts', 4096, 5147, 's:breakdowns', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (413972, 'bund', 'bund', 'bʌnd, bʌnt', 'n. League; confederacy; esp. the confederation of German states.
n. An embankment against inundation.', '(政治上的)同盟, 联盟', 'n:100', NULL, NULL, '', 39231, 32488, 's:bunds', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (425854, 'by bus', 'bybus', '', '', '乘公共汽车', '', NULL, NULL, '', 0, 0, '', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (426219, 'by plane', 'byplane', '', '', '乘飞机', '', NULL, NULL, '', 0, 0, '', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (426514, 'by train', 'bytrain', '', '', '乘火车', '', NULL, NULL, '', 0, 0, '', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (433870, 'cafe', 'cafe', 'kɑ:''fei', 'n. a small restaurant where drinks and snacks are sold', 'n. 咖啡馆, 酒店', 'n:100', 2, NULL, 'cet4 cet6 ky ielts', 5986, 5837, 's:cafes', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (480843, 'catch a cold', 'catchacold', '', '', '感冒', '', NULL, NULL, '', 0, 0, '', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (480904, 'catch cold', 'catchcold', 'kætʃ kəuld', '', ' 感冒, 受凉, 伤风; 受寒; 着凉', '', NULL, NULL, '', 0, 0, '', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (528453, 'child', 'child', 'tʃaild', 'n. a young person of either sex
n. a human offspring (son or daughter) of any age
n. an immature childish person
n. a member of a clan or tribe', 'n. 孩子, 产物, 追随者
[医] 儿童', 'n:100', 5, 1, 'zk gk ielts', 114, 115, 's:children', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (528987, 'children', 'children', '''tʃildrәn', 'n a young person of either sex
n a human offspring (son or daughter) of any age
n an immature childish person
n a member of a clan or tribe', 'pl. 孩子, 孩子们', '', NULL, NULL, 'ielts', 23840, 0, '0:child/1:s/s:childrens', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (529037, 'Children''s Day', 'childrensday', NULL, NULL, 'n. 儿童节(基督教会浸礼的节日,通常在六月的第二个星期日)', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (530422, 'China', 'china', '''tʃainә', 'n. a communist nation that covers a vast territory in eastern Asia; the most populous country in the world
n. high quality porcelain originally made only in China', 'n. 中国, 瓷器
a. 中国的', 'n:100', 2, NULL, 'zk gk', 1973, 7946, 's:chinas', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (530992, 'Chinese', 'chinese', 'tʃai''ni:z', 'n. any of the Sino-Tibetan languages spoken in China; regarded as dialects of a single language (even though they are mutually unintelligible) because they share an ideographic writing system
n. a native or inhabitant of Communist China or of Nationalist China
a. of or pertaining to China or its peoples or cultures', 'n. 中文, 中国话, 中国人
a. 中国的, 中国话的', 'j:96/n:4', NULL, NULL, 'zk gk ielts', 2214, 1218, 's:chineses', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (600656, 'color', 'color', '''kʌlә', 'n. a visual attribute of things that results from the light they emit or transmit or reflect
n. interest and variety and intensity
n. the timbre of a musical sound', 'n. 颜色, 面色, 颜料, 外貌
vt. 把...涂上颜色, 粉饰, 使脸红, 歪曲
vi. 变色', 'v:9/n:91', NULL, NULL, 'cet4 ky ielts', 24372, 697, 's:colors/i:coloring/p:colored/3:colors/d:colored/f:colors', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (602255, 'colour', 'colour', '''kʌlә', 'n any material used for its color
n a race with skin pigmentation different from the white race (especially Blacks)
n (physics) the characteristic of quarks that determines their role in the strong interaction
n interest and variety and intensity
n the timbre of a musical sound
n a visual attribute of things that results from the light they emit or transmit or reflect
n an outward or token appearance or form that is deliberately misleading
n the appearance of objects (or light sources) described in terms of a person''s perception of their hue and lightness (or brightness) and saturation
v modify or bias
v decorate with colors
v give a deceptive explanation or excuse for
v affect as in thought or feeling
v add color to
v change color, often in an undesired manner
a having or capable of producing colors', 'n. 颜色, 面色, 颜料, 外貌
vt. 把...涂上颜色, 粉饰, 使脸红, 歪曲
vi. 变色', '', 5, 1, 'zk gk', 642, 0, 's:colours/d:coloured/i:colouring/p:coloured/3:colours', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (865470, 'do', 'do', 'du:', 'n. the syllable naming the first (tonic) note of any major scale in solmization
v. get (something) done
v. proceed or get along
v. create or design, often in a certain way', 'v. 做, 进行, 完成', 'v:100', 5, 1, 'zk gk', 19, 18, 'i:doing/p:did/3:does/d:done/s:does', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (868677, 'does', 'does', 'dʌz; dәz', 'n the federal department responsible for maintaining a national energy policy of the United States; created in 1977
n mature female of mammals of which the male is called `buck''
v engage in
v carry out or perform an action
v get (something) done
v proceed or get along
v give rise to; cause to happen or occur, not always intentionally
v carry out or practice; as of jobs and professions
v be sufficient; be adequate, either in quality or quantity
v create or design, often in a certain way
v behave in a certain manner; show a certain behavior; conduct or comport oneself
v spend time in prison or in a labor camp
v carry on or function
v arrange attractively
v travel or traverse (a distance)', 'v. 做；工作；有用（do的第三人称单数形式）', '', NULL, NULL, 'gk', 0, 0, '0:doe/1:s', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (920652, 'E-MAIL', 'email', '''i:meil', 'v. communicate electronically on the computer', '[计] 电子邮件', 'v:13/n:87', NULL, NULL, '', 0, 0, 's:e-mails/i:e-mailing/p:e-mailed/3:e-mails/d:e-mailed/f:e-mails', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (965943, 'email', 'email', '''i:''meil', 'n (computer science) a system of world-wide electronic communication in which a computer user can compose a message at one terminal that can be regenerated at the recipient''s terminal when the recipient logs in
v communicate electronically on the computer', 'n. 电子信函', '', NULL, 1, 'zk ielts', 0, 0, 's:emails', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1028055, 'exam', 'exam', 'ig''zæm', 'n a set of questions or exercises evaluating skill or knowledge', 'n. 考试, 测验', 'n:100', 2, 1, 'zk ielts', 4174, 4224, 's:exams', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1028090, 'examination', 'examination', 'ig.zæmi''neiʃәn', 'n. the act of examining something closely (as for mistakes)
n. a set of questions or exercises evaluating skill or knowledge
n. the act of giving students or candidates a test (as by questions) to determine what they know or have learned', 'n. 考试, 测验, 审查
[医] 检查, 诊察', 'n:100', 3, 1, 'zk cet4 cet6 ielts', 1531, 3069, 's:examinations', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1030849, 'excited', 'excited', 'ik''saitid', 'a. in an aroused state', 'a. 兴奋的, 已励磁的, 已激发的, 激昂的, 激动的', 'j:100', 2, 1, '', 4106, 3426, '0:excite/1:p', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1106472, 'first', 'first', 'fә:st', 'n. the first or highest in an ordering or series
n. the first element in a countable series
n. an honours degree of the highest class
a. preceding all others in time or space or degree', 'adv. 首先, 第一, 优先
a. 第一的
num. 第一
n. 开始, 第一', 'r:3/m:96/n:1', 5, 1, 'zk gk', 79, 86, 's:firsts', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1261687, 'go', 'go', 'gou', 'n. a time for working (after which you will be relieved by someone else)
n. a board game for two players who place counters on a grid; the object is to surround and so capture the opponent''s counters
v. follow a procedure or take a course
v. move away from a place into another direction', 'vi. 去, 走, 达到, 运转, 查阅, 消失, 结束, 放弃, 花费, 流传, 趋于, 打算, 剩下
vt. 以...打赌, 对付, 忍受, 出产, 为被捕者出(保释金)
n. 去, 尝试, 进行', 'v:100', 5, 1, 'zk gk ielts', 44, 35, 'i:going/p:went/d:gone/3:goes/s:goes', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1337422, 'has', 'has', 'hæz', 'n (astronomy) the angular distance of a celestial point measured westward along the celestial equator from the zenith crossing; the right ascension for an observer at a particular location and time of day
v have or possess, either in a concrete or an abstract sense
v have as a feature
v go through (mental or physical states or experiences)
v have ownership or possession of
v cause to move; cause to be in a certain position or condition
v serve oneself to, or consume regularly
v have a personal or business relationship with someone
v organize or be responsible for
v have left
v be confronted with
v undergo
v suffer from; be ill with
v cause to do; cause to act in a specified manner
v receive willingly something given or offered
v get something; come into possession of
v undergo (as of injuries and illnesses)
v achieve a point or goal
v cause to be born
v have sex with; archaic use', 'have的第三人称单数现在式', '', NULL, NULL, '', 0, 0, '1:3/0:have', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1340151, 'have', 'have', 'hæv', 'v. have or possess, either in a concrete or an abstract sense
v. have as a feature
v. have a personal or business relationship with someone
v. have left', 'vt. 有, 怀有, 拿, 进行
aux. 已经', 'n:1/v:99', 5, 1, 'zk gk', 8, 8, 'i:having/p:had/3:has/d:had/s:haves', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1415083, 'hot dog', 'hotdog', 'hɔt dɔɡ', '', 'n. <口>热狗（一种中间夹有熏红肠并配有芥菜, 作料等的面包）', '', 1, NULL, '', 0, 0, 's:hot dogs', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1415634, 'hot pot', 'hotpot', 'hɔt pɔt', '', 'n. 火锅', '', NULL, NULL, '', 0, 0, 's:hot pots', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1416503, 'hot-dog', 'hotdog', '', 'v perform intricate maneuvers while skiing', ' （在滑雪、滑雪板运动或冲浪中）表演技巧, 表演高难动作', 'j:100', NULL, NULL, '', 0, 0, 's:hot-dogs', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1417098, 'hotdog', 'hotdog', '', 'n. someone who performs dangerous stunts to attract attention to himself
n. a frankfurter served hot on a bun', 'v. 卖弄', 'n:100', NULL, NULL, 'zk', 0, 26201, 's:hotdogs', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1425658, 'humorous', 'humorous', '''hju:mәrәs', 'a. full of or characterized by humor', 'a. 富幽默感的, 滑稽的, 诙谐的', 'j:100', 1, 1, 'zk gk cet4 cet6 ky toefl', 9475, 9877, '', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1425709, 'humourous', 'humourous', '''hju:mәrәs', 'a full of or characterized by humor', 'a. 富幽默感的, 滑稽的', '', NULL, NULL, '', 42902, 0, '', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1447825, 'I', 'i', 'ai', 'n. the 9th letter of the Roman alphabet', 'pron. 我
[计] 电流, 中断, 指令, 指示符', 'p:100', 5, 1, 'zk gk', 4624, 11, 's:is', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1451887, 'ice cream', 'icecream', '', '', '冰淇淋
[化] 冰淇淋', '', 2, 1, 'zk', 0, 0, 's:ice creams', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1452498, 'ice-cream', 'icecream', '''aiskri:m', '', 'a. 冰淇淋的, 乳白色的', 'n:100', NULL, NULL, 'cet4', 0, 0, 's:ice-creams', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1475182, 'in hospital', 'inhospital', NULL, NULL, '[网络] 住院；在医院；生病住院', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1555476, 'is', 'is', 'iz', 'v have the quality of being; (copula, used with an adjective or a predicate noun)
v be identical to; be someone or something
v occupy a certain position or area; be somewhere
v have an existence, be extant
v happen, occur, take place; this was during the visit to my parents'' house"
v be identical or equivalent to
v form or compose
v work in a specific place, with a specific subject, or in a specific function
v represent, as of a character on stage
v spend or use time
v have life, be alive
v to remain unmolested, undisturbed, or uninterrupted -- used only in infinitive form
v be priced at', 'be的现在式第三人称
[计] 加下标次序, 信息系统, 国际标准, 中间系统', '', NULL, NULL, '', 24648, 0, '0:be/1:3', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1638342, 'kung fu', 'kungfu', 'kjŋ''fu:', '', 'n. 中国功夫', '', NULL, NULL, '', 0, 0, 's:kung fus', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1753735, 'lots of', 'lotsof', '', '', '许多的..., 大量的...', '', NULL, NULL, '', 0, 0, '', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1810225, 'manner', 'manner', '''mænә', 'n. how something is done or how it happens
n. a way of acting or behaving
n. a kind', 'n. 样子, 礼貌, 风格
[法] 方式, 方法, 样式', 'n:100', 3, 1, 'gk cet4 cet6 ky', 1366, 1818, 's:manners', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1810277, 'manners', 'manners', '''mænәs', 'n. social deportment', 'n. 礼貌', '', NULL, NULL, '', 27358, 0, '0:manner/1:s/s:mannerss', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1832828, 'math', 'math', 'mæθ', 'n a science (or group of related sciences) dealing with the logic of quantity and shape and arrangement', 'n. 数学', 'n:100', 1, NULL, 'zk', 36820, 2983, 's:maths', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1833198, 'mathematics', 'mathematics', '.mæθә''mætiks', 'n. a science (or group of related sciences) dealing with the logic of quantity and shape and arrangement', 'n. 数学
[机] 数学', 'n:100', 2, 1, 'zk cet4 cet6 toefl ielts', 3593, 4257, NULL, NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1833372, 'maths', 'maths', 'mæθs', 'n a science (or group of related sciences) dealing with the logic of quantity and shape and arrangement
n a science (or group of related sciences) dealing with the logic of quantity and shape and arrangement', 'n. 数学', 'n:100', 1, NULL, 'cet4 cet6 ky', 5774, 38684, '0:math/s:mathss', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1839381, 'may', 'may', 'mei', 'n. the month following April and preceding June', 'n. 五月
aux. 愿能, 可以, 愿意', 'v:100', 4, 1, 'zk gk ielts', 83, 119, 's:mays', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1914609, 'miss', 'miss', 'mis', 'n. a failure to hit (or meet or find etc)
n. a form of address for an unmarried woman
v. fail to perceive or to catch with the senses or the mind
v. feel or suffer from the lack of', 'n. 失误, 避免, 失败, 小姐
vt. 未得到, 未达到, 未听到, 未觉察, 逃脱, 遗漏, 错过, 思念
vi. 失败, 击不中', 'n:3/v:97', 4, 1, 'zk gk', 919, 833, 'd:missed/p:missed/i:missing/3:misses/s:misses', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1931297, 'mom', 'mom', 'mʌm', 'n informal terms for a mother', 'n. 妈妈', 'n:100', 2, 1, 'zk', 13335, 1609, 's:moms', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1932641, 'Monday', 'monday', '''mʌndi', 'n. the second day of the week; the first working day', 'n. 星期一', '', 4, 1, 'zk gk ielts', 1679, 0, 's:mondays', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1948506, 'mother', 'mother', '''mʌðә', 'n. a woman who has given birth to a child (also used as a term of address to your mother)
n. a stringy slimy substance consisting of yeast cells and bacteria; forms during fermentation and is added to cider or wine to produce vinegar
n. a term of address for an elderly woman
n. a term of address for a mother superior', 'n. 母亲, 修女院长
vt. 产生, 照看, 收养', 'v:1/n:99', 5, 1, 'zk gk ielts', 306, 229, 's:mothers/i:mothering/p:mothered/3:mothers/d:mothered', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1956197, 'Mr', 'mr', '''mistә(r)', 'n a form of address for a man', '先生
[计] 存储器回收程序, 多重请求', '', 5, 1, '', 123, 191, 's:mrs', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1956229, 'Mr.', 'mr', '''mistә(r)', 'n a form of address for a man', '阁下, 先生', '', NULL, NULL, 'zk gk', 0, 0, 's:mr.s', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1956439, 'Mrs', 'mrs', '''misiz', 'n. a form of address for a married woman', '太太', '', 5, 1, '', 434, 932, '0:mr/s:mrss', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1956451, 'mrs.', 'mrs', '''mɪsɪz', '', 'na. 夫人
[网络] 太太；女士；某太太', '', NULL, NULL, '', 0, 0, 's:mrs.s', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1956489, 'MS', 'ms', 'miz', 'n. a form of address for a woman', '美国微软公司
[计] 主存储器, 制造系统, 毫秒, 微软公司', '', 5, 1, '', 3849, 1145, '0:m/s:mss', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1956552, 'Ms.', 'ms', 'miz', 'n a form of address for a woman', '女士', '', NULL, NULL, 'zk gk', 0, 0, 's:ms.s', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (1973540, 'mum', 'mum', 'mʌm', 'n. secrecy
s. failing to speak or communicate etc when expected to', 'n. 菊花, 沉默
a. 沉默的
vi. 演哑剧
interj. 别说话', 'n:100', 3, 1, '', 1110, 14080, 's:mums', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (2093307, 'o''clock', 'oclock', 'ә''klɔk', 'r. according to the clock', 'n. ...点钟, 钟头', 'r:100', 3, NULL, '', 0, 4064, '', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (2113853, 'OK', 'ok', '''әu''kei', 'n a state in south central United States
k an endorsement
s being satisfactory or in satisfactory condition
r an expression of agreement normally occurring at the beginning of a sentence', 'a. 好, 不错, 可以
adv. 好, 不错, 可以
n. 批准, 认可
[计] 确定', 'r:100', NULL, 1, 'zk gk', 3743, 830, 's:oks', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (2123717, 'one', 'one', 'wʌn', 'n. the smallest whole number or a numeral representing this number
n. a single person or thing
s. used of a single unit or thing; not two or more
s. having the indivisible character of a unit', 'n. 一(个)
pron. 一, 任何人
num. 一, 一个
a. 一致的, 完整的', 'p:31/m:64/n:5', 5, 1, 'zk gk ielts', 46, 51, 's:ones', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (2183962, 'p.e.', 'pe', 'ˌpiː ˈiː', '', 'n. 排字错误；体育(课)
[网络] 体育课；体育科；聚乙烯', '', NULL, NULL, '', 0, 0, 's:p.e.s', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (2228995, 'PE', 'pe', 'pei', 'n. the 17th letter of the Hebrew alphabet', '[计] 相位编码
[化] 磷脂酰乙醇胺', 'n:100', 1, NULL, '', 36666, 25507, 's:pes', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (2235184, 'peking opera', 'pekingopera', '', '', ' 京剧', '', NULL, NULL, '', 0, 0, '', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (2280084, 'physical education', 'physicaleducation', '', '', '[医] 体育', '', NULL, NULL, '', 0, 0, 's:physical educations', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (2329219, 'policeman', 'policeman', 'pә''li:smәn', 'n. a member of a police force', 'n. 警察
[化] 淀帚', 'n:100', 3, NULL, 'zk gk', 2490, 4754, 's:policemen', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (2329228, 'policemen', 'policemen', '', 'n a member of a police force', 'pl. 警察', '', NULL, NULL, '', 0, 0, '0:policeman/1:s', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (2329238, 'policewoman', 'policewoman', 'pә''li:swumәn', 'n a woman policeman', 'n. 女警察
[法] 女警察', 'n:100', 1, NULL, '', 16690, 26303, 's:policewomen', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (2654756, 'save one''s life', 'saveoneslife', NULL, NULL, '[网络] 挽救某人生命；挽救某人的生命；救某人的命', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (2926694, 'stuck', 'stuck', 'stʌk', 'a. caught or fixed
s. baffled', 'stick的过去式和过去分词', 'j:100', 2, NULL, '', 4727, 9492, '0:stick/1:pd', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (2988257, 'T-shirt', 'tshirt', '''ti:,ʃә:t', 'n a close-fitting pullover shirt', 'n. 圆领汗衫, T恤', 'j:1/n:99', 2, NULL, 'zk', 0, 0, 's:t-shirts', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (3022694, 'television', 'television', '''teli.viʒәn', 'n. broadcasting visual images of stationary or moving objects
n. a telecommunication system that transmits images of objects (stationary or moving) between distant points', 'n. 电视
[电] 电视', 'n:100', 4, 1, 'zk gk ielts', 978, 794, 's:televisions', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (3044812, 'the bund', 'thebund', NULL, NULL, ' 外滩（上海）; [电影]外滩佚事', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (3046857, 'the great wall', 'thegreatwall', NULL, NULL, ' 长城; 万里长城', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (3050993, 'the united kingdom', 'theunitedkingdom', '', '', ' [法]联合王国', '', NULL, NULL, '', 0, 0, '', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (3051000, 'the United States of America', 'theunitedstatesofamerica', '', '', '美国, 美利坚合众国', '', NULL, NULL, '', 0, 0, '', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (3066900, 'though', 'though', 'ðәu', 'r. (postpositive) however', 'adv. 然而, 可是
conj. 虽然, 纵然', 'c:92/r:8', 5, 1, 'zk gk', 377, 245, '', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (3096950, 'tofu', 'tofu', '''tәufu:', 'n cheeselike food made of curdled soybean milk', 'n. 豆腐', 'n:100', NULL, NULL, '', 43551, 10306, 's:tofus', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (3113315, 'toward', 'toward', 'tә''wɒ:d', 'prep. Alt. of Towards
adv. Alt. of Towards
prep. Approaching; coming near.
prep. Readly to do or learn; compliant with duty; not froward;
   apt; docile; tractable; as, a toward youth.
prep. Ready to act; forward; bold; valiant.', 'prep. 向, 对于, 为了
a. 即将来临的, 进行中的', 'i:100', NULL, NULL, 'zk gk cet4 ky', 4712, 384, '', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (3113332, 'towards', 'towards', 'tә''wɔ:dz', 'prep. In the direction of; to.
prep. With direction to, in a moral sense; with respect or
   reference to; regarding; concerning.
prep. Tending to; in the direction of; in behalf of.
prep. Near; about; approaching to.
adv. Near; at hand; in state of preparation.
prep. & adv. See Toward.', 'prep. 向, 对于, 为了', 'i:100', 5, 1, 'cet4 cet6', 317, 2004, '', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (3170213, 'TV', 'tv', '''ti:''vi:', 'n broadcasting visual images of stationary or moving objects
n an electronic device that receives television signals and displays them on a screen', '电视
[计] 电视, 转移向量', '', 4, 1, 'zk gk ky ielts', 1457, 730, 's:tvs', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (3183960, 'UK', 'uk', 'ju: ''kei', 'n a monarchy in northwestern Europe occupying most of the British Isles; divided into England and Scotland and Wales and Northern Ireland; `Great Britain'' is often used loosely to refer to the United Kingdom', 'n. 联合王国', '', NULL, NULL, '', 572, 0, 's:uks', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (3189895, 'UN', 'un', 'ʌn', 'n an organization of independent states formed in 1945 to promote international peace and security', 'pron. 家伙, 东西
[经] 联合国', '', NULL, NULL, '', 2071, 0, 's:uns', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (3204305, 'UNESCO', 'unesco', 'ju:''neskәj', 'n an agency of the United Nations that promotes education and communication and the arts', '联合国教育科学及文化组织, 联合国教科文组织', '', NULL, NULL, '', 17099, 0, 's:unescoes', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (3212345, 'united', 'united', 'ju:''naitid', 'a. characterized by unity; being or joined into a single entity', 'a. 联合的, 团结的, 一致的, 和睦的
[法] 联合的, 统一的, 一致的', 'j:100', 3, 1, 'ielts', 873, 1460, '0:unite/1:p', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (3212456, 'United Nations', 'unitednations', '', '', '联合国
[经] 联合国', '', NULL, NULL, '', 0, 0, 's:united nationss', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (3212508, 'United Nations Educational, Scientific and Cultural Organization', 'unitednationseducationalscientificandculturalorganization', NULL, NULL, '联合国教育、科学及文化组织(简称联合国教科文组织) [略作 UNESCO]', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (3236760, 'USA', 'usa', 'ju: es ''ei', 'n North American republic containing 50 states - 48 conterminous states in North America plus Alaska in northwest North America and the Hawaiian Islands in the Pacific Ocean; achieved independence in 1776
n the army of the United States of America; the agency that organizes and trains soldiers for land warfare', '美国, 美利坚合众国, 美国陆军', '', NULL, NULL, '', 1800, 0, 's:usas', NULL, '');
INSERT INTO stardict(id, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio) VALUES (3305870, 'was', 'was', 'wɒz', 'n a state in northwestern United States on the Pacific
v have the quality of being; (copula, used with an adjective or a predicate noun)
v be identical to; be someone or something
v occupy a certain position or area; be somewhere
v have an existence, be extant
v happen, occur, take place; this was during the visit to my parents'' house"
v be identical or equivalent to
v form or compose
v work in a specific place, with a specific subject, or in a specific function
v represent, as of a character on stage
v spend or use time
v have life, be alive
v to remain unmolested, undisturbed, or uninterrupted -- used only in infinitive form
v be priced at', 'be的过去式', '', NULL, NULL, '', 41040, 0, '0:be', NULL, '');
