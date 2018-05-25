#!/bin/bash

# 日志每一行包含三列: file_name file_sha1 file_size
# 将日志文件按行记录中的文件大小值进行分割， 每部分不超过120TB

curdir="/www/xxx/"
# 119.999TB
rows=$(cat $1 | awk 'BEGIN{l=1;cnt=0;}{if(s+$3>131940295821492){a[cnt++]=l;s=0;};l+=1;s+=$3;}END{for(i in a)print a[i]}' | sort -n)

last=""
cnt=0
for var in  ${rows[*]}
do
    cntfmt=$(printf "%02d" $cnt)
    if [[ $last == "" ]];
    then
        head -n $var $1 > ${curdir}/$1_${cntfmt}
    else
        st=`expr $var - $last`
        head -n $var $1 | tail -n $st > ${curdir}/$1_${cntfmt}
    fi
    last=$var
    let cnt=cnt+1
    echo $last,$cnt
done

lines=$(wc -l $1 | awk '{print $1}')
tline=`expr $lines - $last`
cntfmt=$(printf "%02d" $tline)
echo $last,$tline
tail -n $tline $1 > ${curdir}/$1_${cntfmt}
