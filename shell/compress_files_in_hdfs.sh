#!/bin/bash
# created at 2017/04/20

files=$(/usr/local/hadoop/bin/hdfs dfs -ls /coststat | grep -v "\.gz" | awk '{print $8}')
for f in $files;
do
    if [ $f == '' ];
    then
        continue
    fi
    lfname=`echo $f | awk '{split($0,arr,"/");print arr[length(arr)];}'`
    echo "to gzip" ${lfname}
    /usr/local/hadoop/bin/hdfs dfs -get $f
    gzip -r ${lfname}
    /usr/local/hadoop/bin/hdfs dfs -put ${lfname}.gz /coststat/
    /usr/local/hadoop/bin/hdfs dfs -rm $f
    rm ${lfname}.gz
done
