#!/bin/bash
# This script generates the ani2d.h header file from the ani2d.c source file.

while [[ "$#" -gt 0 ]]
  do
    case $1 in
      -i|--input) inputPath="$2"; shift;;
      -o|--output) outputPath="$2"; shift;;
      -f|--frameRate) frameRate="$2"; shift;;
    esac
    shift
done

if [ ! -f "$inputPath" ]; then
    echo "$inputPath 文件不存在"
    exit 1
fi

tmpPath=".tmp_ani2d"
mkdir -p $tmpPath
rm -rf $tmpPath/*
mkdir -p $tmpPath/jpgs
mkdir -p $tmpPath/webps

ffmpeg -i "$inputPath" -vf fps=$frameRate -q:v 2 "$tmpPath/jpgs/%03d.jpg"

cd swift/
./removebg 1 "$tmpPath/jpgs" "$tmpPath/webps" --outputFmt webp --webpQuality 100

cd ../ani2d/
rm -f "$outputPath"
python ani2d_tool.py encode \
  --inputImgs "$tmpPath/webps/%03d.webp" \
  --stateNames default \
  --fps $frameRate \
  --sizeMode auto \
  --atlasOptimize auto \
  --aniFile "$outputPath" \
  --rawFrameFormat webp \
  --workers 8