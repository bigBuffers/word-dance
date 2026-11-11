// 今日一句: seven static sentence pairs, one per weekday (owner decision D8: static content only).
const SENTENCES = [
  { en: 'A journey of a thousand miles begins with a single step.', zh: '千里之行，始于足下。' },
  { en: 'Practice makes perfect.', zh: '熟能生巧。' },
  { en: 'Little by little, one travels far.', zh: '不积跬步，无以至千里。' },
  { en: 'Reading is to the mind what exercise is to the body.', zh: '读书之于头脑，犹如锻炼之于身体。' },
  { en: 'Every word you learn is a window you open.', zh: '每学一个词，就多开一扇窗。' },
  { en: 'The best time to plant a tree was twenty years ago; the second best time is now.', zh: '种树最好的时间是二十年前，其次是现在。' },
  { en: 'Rest is part of the work.', zh: '休息也是学习的一部分。' },
];

Page({
  data: { sentence: SENTENCES[0] },
  onShow() {
    this.setData({ sentence: SENTENCES[new Date().getDay()] });
  },
  goPair() {
    wx.navigateTo({ url: '/pages/pair/pair' });
  },
});
