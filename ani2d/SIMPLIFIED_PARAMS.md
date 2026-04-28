# ani2d 简化参数语法指南

## --inputImgs 参数支持的格式

### 1. 单个文件
```bash
python ani2d_tool.py encode --inputImgs img.png
```

### 2. 多个文件逗号分隔
```bash
python ani2d_tool.py encode --inputImgs img1.png,img2.png,img3.png
```

### 3. **%Nd 模式序列（新增）**
对于有序命名的图片序列，可以使用 `%Nd` 格式代替逐一列举：
```bash
# 自动展开为: idle_00.png, idle_01.png, idle_02.png, ...
python ani2d_tool.py encode --inputImgs "folder/idle_%02d.png"
```

**格式说明：**
- `%02d` - 2位零填充整数 (00, 01, 02, ...)
- `%03d` - 3位零填充整数 (000, 001, 002, ...)
- `%d`   - 无填充整数 (0, 1, 2, ...)

支持的宽度从 1 到任意数字，例如 `%4d` 表示 4 位。

### 4. 混合单个文件和模式
```bash
# 先添加 idle_00.png，然后自动展开整个序列
python ani2d_tool.py encode --inputImgs "idle_00.png,folder/idle_%02d.png"
```

---

## 多状态示例

### 传统方式（逐一列举所有文件）
```bash
python ani2d_tool.py encode \
  --stateNames idle,run,jump,attack \
  --inputImgs \
    "idle_00.png,idle_01.png,idle_02.png" \
    "run_00.png,run_01.png,run_02.png" \
    "jump_00.png,jump_01.png" \
    "attack_00.png,attack_01.png,attack_02.png,attack_03.png"
```

### **优化方式（使用 %02d 模式）**
```bash
python ani2d_tool.py encode \
  --stateNames idle,run,jump,attack \
  --fps 10 --padding 2 \
  --inputImgs \
    "anim/idle/idle_%02d.png" \
    "anim/run/run_%02d.png" \
    "anim/jump/jump_%02d.png" \
    "anim/attack/attack_%02d.png"
```

---

## 工作原理

1. **模式检测**：参数中包含 `%Nd` 格式时触发自动展开
2. **文件查找**：
   - 首先用 glob 模式查找所有匹配文件
   - 如果 glob 无结果，尝试按序列号直接查找（0, 1, 2, ...）
3. **排序**：按提取的序列号排序，确保顺序正确
4. **停止**：当某个序列号的文件不存在时停止查找

---

## 示例工作流

已有文件结构：
```
ani2d/tmp/test4/
├── idle/
│   ├── idle_00.png
│   ├── idle_01.png
│   └── ...
├── run/
│   ├── run_00.png
│   ├── run_01.png
│   └── ...
└── ...
```

**一行命令生成 4 状态动画：**
```bash
python ani2d/ani2d_tool.py encode \
  --stateNames idle,run,jump,attack \
  --fps 12 --padding 2 --maxAtlasWidth 512 --maxAtlasHeight 512 \
  --durationsMs 80 80 80 ... \
  --inputImgs \
    "ani2d/tmp/test4/idle/idle_%02d.png" \
    "ani2d/tmp/test4/run/run_%02d.png" \
    "ani2d/tmp/test4/jump/jump_%02d.png" \
    "ani2d/tmp/test4/attack/attack_%02d.png"
```

---

## 测试脚本

- `ani2d/gen_test4_a2d.py` - 传统逐一列举方式生成测试文件
- `ani2d/gen_test4_simplified.py` - 使用 %02d 模式生成相同文件
- `ani2d/demo_simplified_params.py` - 演示各种用法
