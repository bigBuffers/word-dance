// The confirmation page (API.md 115 / 116). Opened by the 小程序码 (`options.scene` = the 26-char ticket → scan with {ticket}) or by the
// pairing page (`options.info` = the WechatScanInfo it already fetched, `options.ref` = the pairing code). Shows the kind, the initiating
// browser (UA summary, masked IP, time) and what confirming would do; 确认 / 取消 → POST /api/auth/wechat/confirm. Nothing about the
// account is stored here — the web poll (113) receives the session.
const api = require('../../utils/api.js');
const { login } = require('../../utils/login.js');

// What confirming would do, by (kind, account) — API.md 115 `WechatScanInfo.account`. A bind ticket whose WeChat is free (`new`) attaches
// it to the web account named by `bind_display_name`; only a login ticket creates an account.
const ACCOUNT_TEXT = {
  bound: { text: '将登录这个微信已绑定的账号', ok: true },
  new: { text: '将为这个微信创建新账号', ok: true },
  closed: { text: '暂停注册，无法创建新账号', ok: false },
  self: { text: '已绑定本账号，确认后不会有变化', ok: true },
  other: { text: '该微信已绑定其他账号', ok: false },
};

function accountState(info) {
  if (info.kind === 'bind' && info.account === 'new') {
    return { text: `将把这个微信绑定到「${info.bind_display_name || ''}」`, ok: true };
  }
  return ACCOUNT_TEXT[info.account] || { text: '', ok: false };
}

function timeText(iso) {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso || '';
  const pad = (n) => (n < 10 ? '0' + n : '' + n);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

Page({
  data: { phase: 'loading', info: null, ref: '', accountText: '', canConfirm: false, createdAtText: '', busy: false, doneTitle: '', doneText: '', errorText: '' },

  async onLoad(options) {
    try {
      if (options.info) {
        const info = JSON.parse(decodeURIComponent(options.info));
        this.show(info, decodeURIComponent(options.ref || ''));
        return;
      }
      if (options.scene) {
        const ticket = decodeURIComponent(options.scene);
        const jsCode = await login();
        const info = await api.request('POST', '/api/auth/wechat/scan', { js_code: jsCode, ticket });
        this.show(info, ticket);
        return;
      }
      this.setData({ phase: 'error', errorText: '请在网页上点「微信登录」，再用微信扫码或输入配对码。' });
    } catch (err) {
      this.setData({ phase: 'error', errorText: api.errorText(err) });
    }
  },

  show(info, ref) {
    const state = accountState(info);
    this.setData({ phase: 'confirm', info, ref, accountText: state.text, canConfirm: state.ok, createdAtText: timeText(info.created_at) });
  },

  async decide(accept) {
    if (this.data.busy) return;
    this.setData({ busy: true });
    try {
      const result = await api.request('POST', '/api/auth/wechat/confirm', { mp_token: this.data.info.mp_token, ticket: this.data.ref, accept });
      if (result.status === 'confirmed') {
        const bound = this.data.info.kind === 'bind';
        this.setData({ phase: 'done', doneTitle: bound ? '已绑定' : '已确认', doneText: bound ? '请回到网页继续。' : '请回到电脑 / 网页继续，网页已登录。' });
      } else {
        this.setData({ phase: 'done', doneTitle: '已取消', doneText: '网页上的登录请求已取消。' });
      }
    } catch (err) {
      api.toast(api.errorText(err));
      if (err.status === 404 || err.code === 'invalid_identity_token') this.setData({ phase: 'error', errorText: api.errorText(err) });
    } finally {
      this.setData({ busy: false });
    }
  },
  accept() { this.decide(true); },
  cancel() { this.decide(false); },
  home() { wx.reLaunch({ url: '/pages/index/index' }); },
});
