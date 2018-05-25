#!/bin/bash
# 每行两个要用于对比文件的ip
ipPairs=(
192.168.1.59 192.168.1.60
192.168.1.81 192.168.1.86
192.168.1.82 192.168.1.87
)
# ssh用户/ssh端口/sudo密码
username="yourname"
port="yourport"
sudoPasswd="yourpassword"
# 检查列表长度是否为偶数
if [[ ${#ipPairs[@]}%2 -eq 1 ]];
then
    echo "invalid pair in ipPairs."
    exit
fi
for((i=0;i<${#ipPairs[@]};i+=2))
do
    ipOne=${ipPairs[$i]}
    ipTwo=${ipPairs[$i+1]}
    echo "ip1:" $ipOne "ip2:" $ipTwo
/usr/bin/expect <<-EOF
    set timeout 300
    spawn ssh -t -p $port -l ${username} $ipOne {sudo find /data/ -type f | sort > /tmp/${ipOne}.log}
    expect {
        "(yes/no)? " { send "yes\n" }
        "password for ${username}: " { send "${sudoPasswd}\n" }
    }
    spawn ssh -t -p $port -l ${username} $ipTwo {sudo find /data/ -type f | sort > /tmp/${ipTwo}.log}
    expect {
        "(yes/no)? " { send "yes\n" }
        "password for ${username}: " { send "${sudoPasswd}\n" }
    }
interact
expect eof
EOF
    scp -P $port ${username}@$ipOne:/tmp/${ipOne}.log ${ipOne}.log
    if [ `ls -l ${ipOne}.log | awk '{ print $5 }'` -lt  1 ]
    then
        echo "${ipOne}.log is empty."
    fi
    
    scp -P $port ${username}@$ipTwo:/tmp/${ipTwo}.log ${ipTwo}.log
    if [ `ls -l ${ipTwo}.log | awk '{ print $5 }'` -lt  1 ]
    then
        echo "${ipTwo}.log is empty."
    fi
    # 对比sha1
    sha1sum ${ipOne}.log ${ipTwo}.log
    # 查找差集
    comm -1 -3 ${ipOne}.log ${ipTwo}.log > ${ipTwo}_${ipOne}.log
done
