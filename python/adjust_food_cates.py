import json

target_fcid = 'fcname_en'
file_path = '../data/food_cates.json'

# 注意：这里用的是 json.load()，直接接收文件对象
with open(file_path, 'r', encoding='utf-8') as f:
    data_list = json.load(f)

fcids = set()
# 遍历列表获取每项的某个字段
for item in data_list:
    value = item.get(target_fcid, 'unknown')
    fcids.add(value)
cidIndex = 1
for fcid in fcids:
    for item in data_list:
        if item.get(target_fcid, 'unknown') == fcid:
            item['fcid'] = cidIndex
    cidIndex += 1
print(json.dumps(data_list, ensure_ascii=False, indent=4))