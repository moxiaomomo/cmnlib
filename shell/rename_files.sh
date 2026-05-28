#!/bin/bash

# 检查是否传入了目录参数
if [ -z "$1" ]; then
    echo "用法: $0 <目标目录路径>"
    exit 1
fi

TARGET_DIR="$1"
PREFIX="hant_"

# 检查目录是否存在
if [ ! -d "$TARGET_DIR" ]; then
    echo "错误: 目录 '$TARGET_DIR' 不存在或不是一个目录"
    exit 1
fi

# 遍历目录下的所有项
# 使用双引号包裹 "$TARGET_DIR"/* 以支持带空格的文件名
for file in "$TARGET_DIR"/*; do
    # 检查是否是普通文件（排除目录、软链接等，如果需要包含软链接可将 -f 改为 -L）
    if [ -f "$file" ]; then
        # 提取文件名 (例如从 /path/to/file.txt 提取 file.txt)
        filename=$(basename "$file")
        
        # 提取目录路径 (例如从 /path/to/file.txt 提取 /path/to)
        dirpath=$(dirname "$file")

        # 检查文件是否已经包含了指定前缀，防止重复执行导致变成 hant_hant_file.txt
        if [[ "$filename" == "$PREFIX"* ]]; then
            echo "跳过: '$filename' (已经包含前缀)"
            continue
        fi

        # 构造新的文件路径
        newfile="$dirpath/${PREFIX}${filename}"

        # 执行重命名操作
        # -n 选项表示 --no-clobber，如果目标文件已存在则不覆盖，防止误删
        # 如果你想强制覆盖，可以把 -n 去掉
        if mv -n "$file" "$newfile"; then
            echo "成功: '$filename' -> '${PREFIX}${filename}'"
        else
            echo "失败: 无法重命名 '$filename' (可能目标文件已存在)"
        fi
    fi
done

echo "批量重命名完成！"
