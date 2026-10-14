# Vocabulary data attribution

The seed vocabulary (`vocab.jsonl`) is derived from:

1. **ECDICT** — Free English to Chinese Dictionary Database by skywind3000
   https://github.com/skywind3000/ECDICT — MIT License.
   Fields used: word, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange.
   Release used: 1.0.28 (ecdict-sqlite-28.zip).

2. **english-wordlists** by mahavivo — https://github.com/mahavivo/english-wordlists
   Exam-syllabus word lists: 中考英语词汇表.txt, Highschool_edited.txt, CET4_edited.txt, CET6_edited.txt,
   CET_4+6_edited.txt (2016 CET syllabus), 英语六级词汇（星标，1726）.txt. Only the head words are used to
   decide stage membership (初中 / 高中 / CET-4 / CET-6).

Stage codes: `zk` = 初中（中考）, `gk` = 高中（高考）, `cet4` = 大学英语四级, `cet6` = 大学英语六级.
A word's `stages` is the union of the ECDICT exam tag and the official syllabus lists.
`exam_tags` keeps ECDICT's other tags (ky 考研, toefl, ielts, gre). `exchange` codes (ECDICT):
p=过去式, d=过去分词, i=现在分词, 3=第三人称单数, r=比较级, t=最高级, s=复数, 0=原型, 1=原型的变换形式.
