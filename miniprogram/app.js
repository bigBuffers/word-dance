// 单词之舞 — the WeChat mini program of the word-Dance login bridge (docs/API.md §3.3, endpoints 115 / 116; miniprogram/README.md).
// Content (owner decision D8): the login / bind confirmation plus a static 今日一句. Nothing here keeps a session: the web browser that
// opened the ticket becomes the signed-in party (endpoint 113); the mini program only proves the scan (115) and the decision (116).
App({
  onLaunch() {
    // nothing to prepare: wx.login runs when a scene / pairing code is resolved (utils/login.js)
  },
});
