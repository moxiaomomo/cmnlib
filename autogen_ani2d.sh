#!/bin/bash
# This script generates the ani2d.h header file from the ani2d.c source file.

show_usage="args: [-i , -o , -f] [--input=, --output=, --frameRate=]"

inputPath=""
outputPath=""
frameRate=30

while [ $# -gt 0 ]
do
    case "$1" in
      -i|--input)
        inputPath="$2"
        shift 2
        ;;
      -i=*|--input=*)
        inputPath="${1#*=}"
        shift
        ;;
      -o|--output)
        outputPath="$2"
        shift 2
        ;;
      -o=*|--output=*)
        outputPath="${1#*=}"
        shift
        ;;
      -f|--frameRate)
        frameRate="$2"
        shift 2
        ;;
      -f=*|--frameRate=*)
        frameRate="${1#*=}"
        shift
        ;;
      -h|--help)
        echo "$show_usage"
        exit 0
        ;;
      --)
        shift
        break
        ;;
      *)
        echo "未知参数: $1"
        echo "$show_usage"
        exit 1
        ;;
    esac
done

if [ -z "$inputPath" ] || [ -z "$outputPath" ]; then
    echo "input 和 output 不能为空"
    echo "$show_usage"
    exit 1
fi

if [ ! -f "$inputPath" ]; then
    echo "$inputPath 文件不存在"
    exit 1
fi

tmpPath=".tmp_ani2d_frames"
mkdir -p ${tmpPath}
rm -rf ${tmpPath}/*
mkdir -p ${tmpPath}/jpgs
mkdir -p ${tmpPath}/webps

echo "正在从 $inputPath 提取帧..."
ffmpeg -i "$inputPath" -vf fps=$frameRate -q:v 2 "${tmpPath}/jpgs/%03d.jpg"

echo "正在将帧转换为 WebP 格式...,源中间文件夹：${tmpPath}/jpgs/"
./swift/removebg 1 "${tmpPath}/jpgs/" "${tmpPath}/webps/" --outputFmt webp --webpQuality 100

echo "正在生成 ${outputPath}..."
rm -f "$outputPath"
python ./ani2d/ani2d_tool.py encode \
  --inputImgs "${tmpPath}/webps/%03d.webp" \
  --stateNames default \
  --fps $frameRate \
  --sizeMode auto \
  --atlasOptimize auto \
  --aniFile "$outputPath" \
  --rawFrameFormat webp \
  --workers 8

rm -rf ${tmpPath}/*