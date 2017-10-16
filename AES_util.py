#!/usr/bin/python
# -*- coding: utf-8 -*-

import base64
from Crypto import Random
from Crypto.Cipher import AES


class MyCrypt(object):

    def __init__(self, key):
        self.bs = 32
        if len(key) >= 32:
            self.key = key[:32]
        else:
            self.key = self._pad(key)

    def encrypt(self, raw):
        raw = self._pad(raw)
        iv = Random.new().read(AES.block_size)
        cipher = AES.new(self.key, AES.MODE_CBC, iv)
        return base64.b64encode(iv + cipher.encrypt(raw))

    def decrypt(self, enc):
        enc = base64.b64decode(enc)
        iv = enc[:AES.block_size]
        cipher = AES.new(self.key, AES.MODE_CBC, iv)
        return self._unpad(cipher.decrypt(enc[AES.block_size:]))

    def encrypt_ecb(self, raw):
        raw = self._pad(raw)
        key = self._str2bin(self.key)
        cipher = AES.new(key, AES.MODE_ECB)
        enc = cipher.encrypt(raw)
        return enc

    def decrypt_ecb(self, enc):
        key = self._str2bin(self.key)
        cipher = AES.new(key, AES.MODE_ECB)
        dec = cipher.decrypt(enc)
        dec = self._unpad(dec)
        return dec

    def encrypt_ecb_for_css(self, raw):
        length = len(raw)
        left = length % AES.block_size
        body = raw[0:length - left]
        tail = raw[length - left:]
        cipher = AES.new(self.key, AES.MODE_ECB)
        return '%s%s' % (cipher.encrypt(body), tail)

    def decrypt_ecb_for_css(self, raw):
        length = len(raw)
        left = length % AES.block_size
        body = raw[:length - left]
        cipher = AES.new(self.key, AES.MODE_ECB)
        return '%s%s' % (cipher.decrypt(body), raw[length - left:])

    def _pad(self, s):
        return s + (self.bs - len(s) % self.bs) * chr(self.bs - len(s) % self.bs)

    def _unpad(self, s):
        return s[:-ord(s[len(s)-1:])]

    def _str2bin(self, s):
        assert len(s) % 2 == 0
        t = []
        for i in range(0, len(s), 2):
            j = s[i] + s[i + 1]
            t.append(chr(int(j, 16)))
        return ''.join(t)

class Base64AESCBC(object):
    def __init__(self, key):
        self.key = key[:32] + '\x00' * (32 - len(key))

    def encrypt(self, iv, raw):
        raw = self._pad_16(raw)
        cipher = AES.new(self.key, AES.MODE_CBC, iv[:16])
        return base64.b64encode(cipher.encrypt(raw))

    def decrypt(self, iv, enc):
        enc = base64.b64decode(enc)
        cipher = AES.new(self.key, AES.MODE_CBC, iv[:16])
        return self._unpad(cipher.decrypt(enc))

    def _pad_16(self, s):
        lfsize = 16 - len(s) % 16
        return s + lfsize * chr(lfsize)

    def _unpad(self, s):
        return s[:-ord(s[len(s)-1:])]


def test_normal(key, tx):
    pc = MyCrypt(key)
    e = pc.encrypt(tx)
    d = pc.decrypt(e)
    print("RAW: %s ENC: %s DEC: %s" % (tx, e, d))
    if tx != d.decode('utf-8'):
        raise Exception('decode result error.')

def test_easy(key, tx):
    pc = Base64AESCBC(key)
    iv = '0' * 17
    e = pc.encrypt(iv, tx)
    d = pc.decrypt(iv, e)
    print("RAW: %s ENC: %s DEC: %s" % (tx, e, d))
    if tx != d.decode('utf-8'):
        raise Exception('decode result error.')


if __name__ == '__main__':
    tx = 'fortest' * 5
    test_normal('testkey', tx)
    test_easy('testkey', tx)
