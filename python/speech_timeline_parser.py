import speech_recognition as sr
from pydub import AudioSegment

def parseHMS(timeline):
    timeline = timeline.split(',')[0]
    hms = timeline.split(':')
    return int(hms[0])*3600+int(hms[1])*60+int(hms[2])

def find_time_interval(intervals, target):
    """
    查找目标时间点所在的时间区间
    
    参数:
        intervals: 时间区间列表，每个区间为[start, end]，需按start排序
        target: 要查找的时间点
        
    返回:
        包含目标时间点的区间，如果未找到返回None
    """
    left, right = 0, len(intervals) - 1
    
    while left <= right:
        mid = (left + right) // 2
        start, end = intervals[mid]
        
        # 如果目标时间点小于当前区间的开始，搜索左半部分
        if target < start:
            right = mid - 1
        # 如果目标时间点大于当前区间的结束，搜索右半部分
        elif target > end:
            left = mid + 1
        # 找到包含目标时间点的区间
        else:
            return intervals[mid]
    
    # 未找到匹配的区间
    return None

with open("D:\\data\\02_noodles.wav.srt") as fd:
    lines = fd.readlines()
    start_section = False
    timeline = ''
    sentence = ''
    obj = {
        'intervals': [],
        'sentences': []
    }
    for line in lines:
        line = line.strip()
        if line.isdigit():
            start_section = True
            continue
        elif line == '':
            start_section = True
            continue
        
        if line.find('-->') != -1:
            timeline = line
        else:
            sentence = line
            
            timelines = timeline.split(' --> ')
            # print('{} {} {}'.format(parseHMS(timelines[0]), parseHMS(timelines[1]), sentence))
            obj['intervals'].append([parseHMS(timelines[0]), parseHMS(timelines[1])])
            obj['sentences'].append(sentence)
            
    print(obj)
