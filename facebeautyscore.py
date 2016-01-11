#!/usr/bin/python
#coding: utf-8
__author__ = 'moxiaomomo'

import math
import time
from pprint import pformat
from facepp import API
from facepp import File


APIKEY = "6b27e7b6923d7ef083add4da4cb19c6b"
APISCRETE = 'HQSpyUQhzTLEgcCl8Cvn4iaLxbpzvqHz'


# 计算两点之间的距离
def distance(px1,py1,px2,py2):
	return math.sqrt(abs(math.pow(px2 - px1,2)) + abs(math.pow(py2 - py1,2)))


# 分析人脸数据
def analysisPhoto(imgPath):
	face1,face2,results,smile = 0, 0, 0, 0
        api = API(APIKEY, APISCRETE)
        try:
    	    detect_res = api.detection.detect(img=File(imgPath))
        except Exception,e:
            print e
            detect_res = {}

        if not detect_res or not detect_res.get('face'):
            return {'gender':'Unknown', 'age':0, 'score':0}

	landmark_res = api.detection.landmark(face_id=detect_res['face'][0]['face_id'])
	#print detect_res
	#print landmark_res

	smile = int(detect_res['face'][0]['attribute']['smiling']['value'])
        gender = detect_res['face'][0]['attribute']['gender']['value']
        age = detect_res['face'][0]['attribute']['age']['value'] 
	if smile < 20:
		smile = -10
	else:
		smile = int(smile/10)

	if len(landmark_res['result']) <= 0:
		return
	yourface = landmark_res['result'][0]['landmark']

	# 计算两眉头间的距离
	c1 = distance(yourface['left_eyebrow_right_corner']['x'],
				yourface['left_eyebrow_right_corner']['y'],
				yourface['right_eyebrow_left_corner']['x'],
				yourface['right_eyebrow_left_corner']['y'])

	# console.log('计算两眉头间的距离 = ' + c1)
	# 眉毛之间的中点坐标
	c1_x = (yourface['right_eyebrow_left_corner']['x'] - yourface['left_eyebrow_right_corner']['x'])/2 + \
				yourface['left_eyebrow_right_corner']['x']
	c1_y = (yourface['right_eyebrow_left_corner']['y'] - yourface['left_eyebrow_right_corner']['y'])/2 + \
				yourface['left_eyebrow_right_corner']['y']

	# 眉毛中点到鼻子最低处的距离
	c2 = distance(yourface['nose_contour_lower_middle']['x'],
				yourface['nose_contour_lower_middle']['y'],
				c1_x,
				c1_y)

        eyeb_delta = (yourface['right_eyebrow_right_corner']['x'] - yourface['right_eye_right_corner']['x']) + \
             (yourface['left_eyebrow_left_corner']['x'] - yourface['left_eye_left_corner']['x'])
        eye_width = yourface['right_eye_right_corner']['x'] - yourface['left_eye_left_corner']['x']

	# 眼角之间的距离
	# console.log('眼角之间的距离 = ' + c3)
	c3 = distance(yourface['left_eye_right_corner']['x'],
				yourface['left_eye_right_corner']['y'],
				yourface['right_eye_left_corner']['x'],
				yourface['right_eye_left_corner']['y'])

	# 鼻子的宽度
	c4 = distance(yourface['nose_left']['x'],
				yourface['nose_left']['y'],
				yourface['nose_right']['x'],
				yourface['nose_right']['y'])

	# 脸的宽度
	c5 = distance(yourface['contour_left1']['x'],
				yourface['contour_left1']['y'],
				yourface['contour_right1']['x'],
				yourface['contour_right1']['y'])

        # 脸中下部宽度
        face2_width = distance(yourface['contour_left3']['x'],
                                yourface['contour_left3']['y'],
                                yourface['contour_right3']['x'],
                                yourface['contour_right3']['y']) 

	# 下巴到鼻子下方的高度
	c6 = distance(yourface['contour_chin']['x'],
				yourface['contour_chin']['y'],
				yourface['nose_contour_lower_middle']['x'],
				yourface['nose_contour_lower_middle']['y'])

	# 眼睛的大小
	c7_left = distance(yourface['left_eye_left_corner']['x'],
					yourface['left_eye_left_corner']['y'],
					yourface['left_eye_right_corner']['x'],
					yourface['left_eye_right_corner']['y'])
	c7_right = distance(yourface['right_eye_left_corner']['x'],
					yourface['right_eye_left_corner']['y'],
					yourface['right_eye_right_corner']['x'],
					yourface['right_eye_right_corner']['y'])

	# 嘴巴的大小
	c8 = distance(yourface['mouth_left_corner']['x'],
				yourface['mouth_left_corner']['y'],
				yourface['mouth_right_corner']['x'],
				yourface['mouth_right_corner']['y'])

        lip_dis = distance(yourface['mouth_upper_lip_top']['x'],
                           yourface['mouth_upper_lip_top']['y'],
                           yourface['mouth_lower_lip_bottom']['x'],
                           yourface['mouth_lower_lip_bottom']['y'],
        )

	# 嘴巴处的face大小
	c9 = distance(yourface['contour_left6']['x'],
		yourface['contour_left6']['y'],
		yourface['contour_right6']['x'],
		yourface['contour_right6']['y'])

	# 开始计算步骤
	yourmark = 100
	mustm = 0

	# 眼角距离为脸宽的1/5
	mustm += abs((c3/c5)*100 - 25)

	# 鼻子宽度为脸宽的1/5
	mustm += abs((c4/c5)*100 - 25)

        # 上脸比中脸的宽度比相差不超过3%
        mustm += abs((c5/face2_width)*100 - 97)/5

        # 眉毛比眼角宽约5%
        eyeb_per = eyeb_delta/eye_width*100
        print abs((c5/face2_width)*100 - 97)/5, eyeb_per, abs(eyeb_per - 20)/5, (10+abs(eyeb_per))/5
        print abs((c8/c9)*100 - 55), abs((c8/c9)*100 - 45)

        if eyeb_per > 0:
            mustm +=  abs(eyeb_per - 20)/5
        else:
            mustm += (10+abs(eyeb_per))/5

	# 眼睛的宽度，应为同一水平脸部宽度的1/5
	eyepj = (c7_left+c7_right)/2
	mustm += abs(eyepj/c5*100 - 25)

	# 理想嘴巴宽度应为同一脸部宽度的1/2
        if smile < 0:
    	    mustm += abs((c8/c9)*100 - 55)/2;
        else:
            mustm += abs((c8/c9)*100 - 45)/2;

        print smile, lip_dis, c8, lip_dis/c8*100
        lip_per = lip_dis/c8*100
        if smile < 0 and lip_per>=25:
            mustm += abs(lip_per-25)

	# 下巴到鼻子下方的高度 == 眉毛中点到鼻子最低处的距离
	mustm += abs(c6 - c2)

	yourscore_score = yourmark - round(mustm, 2) + smile
	return {'gender': gender, 'score': '%.1f' % yourscore_score, 'age': age}


if __name__ == "__main__":
	print analysisPhoto(imgPath="/data/faceImg/huahua.jpg")
