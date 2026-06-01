#!/bin/bash
# This script generates the ani2d.h header file from the ani2d.c source file.

show_usage="args: [-i, -o, -f, -m] [--input=, --output=, --frameRate=, --mode=, --help]
  -i, --input: 输入视频文件路径
  -o, --output: 输出 ani2d 文件路径
  -f, --frameRate: 输出动画的帧率，默认为 30
  -m, --mode: 检测背景的模式 (vision: 视觉模式，chromaKey: 色度键模式，hybrid: 混合模式，autoChromaKey: 自动色度键模式)，默认为 autoChromaKey
  -h, --help: 显示帮助信息"

inputPath=""
outputPath=""
frameRate=30
mode=""
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
      -m|--mode)
        mode="$2"
        shift 2
        ;;
      -m=*|--mode=*)
        mode="${1#*=}"
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
    echo "[错误] $inputPath 文件不存在"
    exit 1
fi

tmpPath=".tmp_ani2d_frames"
mkdir -p ${tmpPath}
rm -rf ${tmpPath}/*
mkdir -p ${tmpPath}/jpgs
mkdir -p ${tmpPath}/webps

echo "正在从 $inputPath 提取帧..."

videoSize=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0:s=x "$inputPath")
if [ -z "$videoSize" ]; then
  echo "[错误] 无法读取视频分辨率: $inputPath"
  exit 1
fi

videoWidth=${videoSize%x*}
videoHeight=${videoSize#*x}

if [ "$videoWidth" -gt 960 ] || [ "$videoHeight" -gt 960 ]; then
  vfExpr="fps=$frameRate,scale=960:960:force_original_aspect_ratio=decrease"
  echo "检测到原始分辨率 ${videoWidth}x${videoHeight}，将按比例缩放至最长边 960 后抽帧"
else
  vfExpr="fps=$frameRate"
  echo "检测到原始分辨率 ${videoWidth}x${videoHeight}，无需缩放，按原尺寸抽帧"
fi

ffmpeg -i "$inputPath" -vf "$vfExpr" -q:v 5 "${tmpPath}/jpgs/%03d.jpg"

if [ ! -f "${tmpPath}/jpgs/001.jpg" ]; then
    echo "[错误] ${tmpPath}/jpgs/001.jpg 文件不存在，可能是 ffmpeg 提取帧失败了"
    exit 1
fi

echo "正在将帧转换为 WebP 格式...,源中间文件夹：${tmpPath}/jpgs/"
# --bgMode hybrid --greenThreshold 0.12 --greenSoftness 0.20 --greenMinRatio 0.42
if [ "$mode" == "autoChromaKey" ]; then
  ./swift/removebg 1 "${tmpPath}/jpgs/" "${tmpPath}/webps/" --outputFmt webp --webpQuality 70 --bgMode ${mode:-autoChromaKey} --watermarkRemoval on
else
  ./swift/removebg 1 "${tmpPath}/jpgs/" "${tmpPath}/webps/" --outputFmt webp --webpQuality 70 --bgMode ${mode:-hybrid} --greenThreshold 0.12 --greenSoftness 0.20 --greenMinRatio 0.42 --watermarkRemoval on
fi

if [ ! -f "${tmpPath}/webps/001.webp" ]; then
    echo "[错误] ${tmpPath}/webps/001.webp 文件不存在，可能是 removebg 转换失败了"
    exit 1
fi

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

if [ ! -f "$outputPath" ]; then
    echo "[错误] ${outputPath} 文件不存在，可能是 ani2d_tool.py 生成失败了"
    exit 1
fi

#rm -rf ${tmpPath}/*