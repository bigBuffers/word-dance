// wx.login → the js_code the server exchanges for the openid (code2Session, endpoint 115). A js_code is single use and lives five
// minutes: fetch a fresh one right before every scan request.
function login() {
  return new Promise((resolve, reject) => {
    wx.login({
      success(res) {
        if (res.code) resolve(res.code);
        else reject({ status: 0, code: 'wx_login', message: '微信登录失败，请重试' });
      },
      fail() {
        reject({ status: 0, code: 'wx_login', message: '微信登录失败，请重试' });
      },
    });
  });
}

module.exports = { login };
