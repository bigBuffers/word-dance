// wx.request wrapper: JSON in / out, the CSRF header every word-Dance POST carries (API.md §1), the error envelope turned into a rejection
// `{status, code, message, details}` so the pages can map a code to a toast.
const config = require('../config.js');

function request(method, path, data) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: config.apiBase + path,
      method,
      data: data || undefined,
      header: { 'Content-Type': 'application/json', 'X-WD-Request': '1' },
      timeout: 15000,
      success(res) {
        const body = res.data && typeof res.data === 'object' ? res.data : {};
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(body);
          return;
        }
        const err = body.error || {};
        reject({ status: res.statusCode, code: err.code || 'http_error', message: err.message || '请求失败', details: err.details || {} });
      },
      fail(e) {
        reject({ status: 0, code: 'network', message: '网络不可用，请稍后再试', details: { raw: e && e.errMsg } });
      },
    });
  });
}

// The zh text for a failed scan / confirmation (API.md §1.1 codes the bridge answers with; the 409 `invalid_transition` reasons of 115 / 116
// — `scanned_elsewhere`, `wrong_state` — and `identity_taken` get their own wording instead of the catalogue's generic sentence).
function errorText(err) {
  if (!err) return '请求失败';
  if (err.status === 404) return '二维码已过期，请在网页上刷新';
  if (err.status === 429) return '操作太频繁，请稍后再试';
  if (err.status === 502) return '微信服务暂时不可用，请稍后再试';
  if (err.code === 'invalid_identity_token') return '确认已超时，请重新扫码';
  if (err.code === 'provider_unconfigured') return '该登录方式尚未开启';
  if (err.code === 'identity_taken') return '该微信已绑定其他账号';
  if (err.code === 'invalid_transition') {
    const reason = err.details && err.details.reason;
    if (reason === 'scanned_elsewhere') return '这个二维码已被另一个微信扫过，请在网页上刷新';
    if (reason === 'wrong_state') return '这个请求已经处理过了';
  }
  if (err.code === 'validation_error' && err.details && err.details.fields && err.details.fields.js_code) return err.details.fields.js_code;
  return err.message || '请求失败';
}

function toast(text) {
  wx.showToast({ title: text, icon: 'none', duration: 2600 });
}

module.exports = { request, errorText, toast };
