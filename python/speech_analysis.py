import speech_recognition as sr
from pydub import AudioSegment

# ffmpeg -i .\02_noodles.mp4 -vn -acodec pcm_s16le -ar 16000 -ac 1 02_noodles.wav
# D:\Projects\whisper.cpp\build\bin\Release\whisper-cli.exe -f D:\data\egg.wav -m D:\Projects\whisper.cpp\models\ggml-model-whisper-large-q5_0.bin -osrt -l zh -t 4
audio = AudioSegment.from_file("D:\\data\\egg.wav")
r = sr.Recognizer()
with sr.AudioFile("D:\\data\\egg.wav") as source:
    audio_data = r.record(source)
    result = r.recognize_google(audio_data, show_all=True)
    # result 里会包含识别文本和大致时间区间，需解析处理
    print(result)
