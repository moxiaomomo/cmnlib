import os
import socket
import hashlib
import random
import uuid
import time

def gen_uuid():
    tsms = int(time.time()*1000)
    rstr = str(uuid.uuid4())

    try:
       pid = os.getpid()
       hostname = socket.gethostname()
    except Exception as e:
       pid = 10000
       hostname = "defaulthostname"

    # 字符串(长度为8):16进制时间戳
    tssec = hex(int(time.time()))[2:]
    # 字符串md5值(长度为32): md5(当前毫秒时间戳, 进程ID, Hostname, 随机字符串)
    postfix = hashlib.md5("{}{}{}{}".format(tsms, pid, hostname, rstr).encode('utf-8')).hexdigest()

    if len(tssec) < 8:
        tssec += ''.join(random.sample('fedcba1234567890', 8-len(tssec)))
    elif len(tssec) > 8:
        tssec = tssec[:8]

    # 40位字符串
    return ("%s%s" % (tssec, postfix))[:40]


# for testing
if __name__ == "__main__":
   with open('tmp_ossid.txt', 'a') as fd:
       for i in range(0, 20000000):
           ossid = gen_ossid()
           fd.write("%s\n" % ossid)
