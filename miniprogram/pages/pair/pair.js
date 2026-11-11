// The pairing-code path (API.md 115): six digits → wx.login → POST /api/auth/wechat/scan {js_code, pairing_code} → the confirmation page
// with the WechatScanInfo. The pairing code is what the confirmation (116) names as `ticket`: the mini program never sees the scene.
const api = require('../../utils/api.js');
const { login } = require('../../utils/login.js');

Page({
  data: { code: '', busy: false },
  onInput(e) {
    this.setData({ code: String(e.detail.value || '').replace(/\D/g, '').slice(0, 6) });
  },
  async submit() {
    const code = this.data.code;
    if (code.length !== 6 || this.data.busy) return;
    this.setData({ busy: true });
    try {
      const jsCode = await login();
      const info = await api.request('POST', '/api/auth/wechat/scan', { js_code: jsCode, pairing_code: code });
      wx.redirectTo({ url: '/pages/confirm/confirm?ref=' + encodeURIComponent(code) + '&info=' + encodeURIComponent(JSON.stringify(info)) });
    } catch (err) {
      api.toast(api.errorText(err));
      this.setData({ busy: false });
    }
  },
});
