const Encrypt  = require('./rsa.min.js');

let cryptFirst = new Encrypt.JSEncrypt();

function initKey(curApp) {
  cryptFirst.setPublicKey(curApp.globalData.dataSecId);
}

function encrypt(data) {
  return cryptFirst.encrypt(data);
}

function decrypt(encData) {
  return cryptFirst.decrypt(encData);
}

module.exports = {
  encrypt: encrypt,
  decrypt: decrypt,
  initKey: initKey,
}