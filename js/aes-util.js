var CryptoJS = require('./aes.min.js') //引用文件

//AES-128-CBC加密模式，key需要为16位，key和iv可以一样
/*
 * [encrypt 加密]
 * 返回base64格式字符串
 */
function Encrypt(content, key) {
  var key = CryptoJS.enc.Utf8.parse(key); //abcdefghigkliopk密码，16位
  var encryptResult = CryptoJS.AES.encrypt(content, key, {
    iv: CryptoJS.enc.Utf8.parse("0102030405060708"), //0102030405060708偏移量，16位
    mode: CryptoJS.mode.ECB, //aes加密模式ecb
    padding: CryptoJS.pad.Pkcs7 //填充
  });
  var result = String(encryptResult); //把object转化为string
  return result
}

/*
 * [decrypt 解密]
 */

function Decrypt(content, key) {
  var key = CryptoJS.enc.Utf8.parse(key);
  var bytes = CryptoJS.AES.decrypt(content.toString(), key, {
    iv: CryptoJS.enc.Utf8.parse("0102030405060708"),
    mode: CryptoJS.mode.ECB,
    padding: CryptoJS.pad.Pkcs7
  });
  var decryptResult = bytes.toString(CryptoJS.enc.Utf8);
  return decryptResult
}

function DecryptArrayBuffer(content, key) {
  var key = CryptoJS.enc.Utf8.parse(key);
  var i8a = new Uint8Array(content); // is of type ArrayBuffer
  var wordArray = CryptoJS.lib.WordArray.create(i8a);
  var bytes = CryptoJS.AES.decrypt(wordArray, key, {
    iv: CryptoJS.enc.Utf8.parse("0102030405060708"),
    mode: CryptoJS.mode.ECB,
    padding: CryptoJS.pad.Pkcs7
  });

  var decryptResult = bytes.toString(CryptoJS.enc.Utf8);
  return decryptResult
}

function DecryptUint8Array(i8a, key) {
  var key = CryptoJS.enc.Utf8.parse(key);
  var wordArray = CryptoJS.lib.WordArray.create(i8a);
  var bytes = CryptoJS.AES.decrypt(wordArray, key, {
    iv: CryptoJS.enc.Utf8.parse("0102030405060708"),
    mode: CryptoJS.mode.ECB,
    padding: CryptoJS.pad.Pkcs7
  });
  console.log(bytes)
  var decryptResult = bytes.toString(CryptoJS.enc.Utf8);
  return decryptResult
}

function DecryptBase64(buf2b64, key) {
  var bytes = CryptoJS.AES.decrypt(buf2b64, key, {
    iv: CryptoJS.enc.Utf8.parse("0102030405060708"),
    mode: CryptoJS.mode.ECB,
    padding: CryptoJS.pad.Pkcs7
  })
  var decryptResult = bytes.toString(CryptoJS.enc.Utf8);
  return decryptResult
}

module.exports = {
  encrypt: Encrypt,
  decrypt: Decrypt,
  decryptArrayBuffer: DecryptArrayBuffer,
  decryptBase64: DecryptBase64,
  decryptUint8Array: DecryptUint8Array
}