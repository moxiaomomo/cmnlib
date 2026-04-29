from manim import *
import numpy as np


class HyperboloidOfOneSheet(ThreeDScene, MovingCamera):
    def construct(self):
        # ========== 1. 配置3D相机视角 ==========
        # 设置初始相机角度（方位角、仰角、距离）
        self.set_camera_orientation(phi=75 * DEGREES, theta=-60 * DEGREES, zoom = 0.45, focal_distance=300)

        # 开启相机旋转动画（全程缓慢旋转视角）
        self.begin_ambient_camera_rotation(rate=0.1)

        # ========== 2. 绘制3D坐标轴 ==========
        axes = ThreeDAxes(
            x_range=(-4, 4, 1),  # x轴范围
            y_range=(-4, 4, 1),  # y轴范围
            z_range=(-4, 4, 1),  # z轴范围
            axis_config={"color": GRAY, "stroke_width": 2},
        )
        # 添加坐标轴标签
        axes_labels = axes.get_axis_labels(
            x_label=Tex("x").scale(2),
            y_label=Tex("y").scale(2),
            z_label=Tex("z").scale(2),
        )
        self.add(axes, axes_labels)
        self.wait(0.5)

            # ========== 3. 核心：自定义小蛮腰形状的参数方程 ==========
        def canton_tower_func(u, theta):
            """
            模拟小蛮腰的参数方程（打破标准单叶双曲面的对称性）：
            - u: 对应z轴，范围[-4,4]（映射到z=-8到8）
            - theta: 绕z轴旋转，0~2π
            - 径向因子：底部（u=-4）半径最大，中间（u=0）最小，顶部（u=4）中等
            """
            # 第一步：将u映射到z（拉长纵向范围）
            z = u * 2  # u∈[-4,4] → z∈[-8,8]
            
            # 第二步：设计径向缩放因子（核心：非对称半径）
            # 基础径向因子：中间细，上下宽（用二次函数+双曲函数组合）
            # 底部（u=-4）：半径≈5；中间（u=0）：半径≈1；顶部（u=4）：半径≈2.5
            radial_base = 0.15 * (u **2) + 1  # 二次函数：中间最小（u=0时1）
            # # 底部额外加宽（u<0时增加径向因子）
            if u < 0:
                radial_base += np.abs(u) * 0.1  # 底部越往下，半径越大
            # if u < 0:
            #     radial_base += np.abs(u) * 0.6  # 底部越往下，半径越大
            # elif u >= 0 and u<1:
            #     radial_base += (np.abs(u)+u/1) * 0.125  # 缓冲
            # # 顶部适度收窄（u>0时减少径向因子）
            # elif u >= 1:
            #     radial_base += u * 0.125  # 顶部越往上，半径缓慢增加（但远小于底部）

            # 第三步：计算x/y/z坐标（绕z轴旋转）
            scale = 0.65 #* (u*u+1)/(u*u*u+1)
            x = radial_base * np.cos(theta) * scale
            y = radial_base * np.sin(theta) * scale
            return np.array([x, y, z])

        # ========== 3. 定义单页双曲面的参数方程 ==========
        def hyperboloid_func(u, theta):
            """
            单页双曲面参数方程
            u: 纵向参数（-3到3），theta: 旋转参数（0到2π）
            """
            scale = 0.4 #* (u*u+1)/(u*u*u+1)
            x = np.cosh(u) * np.cos(theta) * scale
            y = np.cosh(u) * np.sin(theta) * scale
            z = np.sinh(u)
            return np.array([x, y, z])

        # ========== 4. 绘制单页双曲面 ==========
        hyperboloid = Surface(
            lambda u, theta: hyperboloid_func(u, theta),
            u_range=[-3, 3],  # u的范围（控制曲面高度）
            v_range=[0, 2 * PI],  # theta对应v_range（Manim的Surface用v表示第二个参数）
            resolution=(30, 30),  # 分辨率（越高越平滑，渲染越慢）
            fill_color=BLUE,  # 填充色
            fill_opacity=0.6,  # 透明度（0-1，半透明更易看3D结构）
            stroke_color=WHITE,  # 轮廓线颜色
            stroke_width=0.3,  # 轮廓线宽度
        )
        
        # ========== 绘制小蛮腰形状的曲面（模拟塔身） ==========
        canton_tower = Surface(
            lambda u, theta: canton_tower_func(u, theta),
            u_range=[-3, 3],       # 控制纵向高度（底部，顶部）
            v_range=[0, 2 * PI],   # 绕z轴旋转一周
            resolution=(40, 40),   # 提高分辨率，让轮廓更平滑
            fill_color=BLUE,  # 填充色
            # fill_color=color_gradient([BLUE_D, BLUE, TEAL_C], length_of_output=3),  # 渐变蓝，模拟塔身玻璃
            fill_opacity=0.7,
            stroke_color=WHITE,
            stroke_width=0.3
        )

        # ========== 5. 添加动画效果 ==========
        # 渐现动画（替代Create，更柔和）
        self.play(FadeIn(hyperboloid), run_time=2)
        self.wait(1)

        # ========== 6. 添加方程标注（3D场景中跟随视角） ==========
        equation = Tex(
            r"x \^ 2 + y \^ 2 - z \^ 2 = 1", font_size=24, color=YELLOW  # 单页双曲面方程
        ).to_corner(
            UL
        )  # 放在左上角
        # 让标注始终面向相机（3D场景必备）
        # equation.add_updater(lambda m: m.look_at(self.camera.get_location()))
        self.add_fixed_orientation_mobjects(equation)
        self.play(Write(equation), run_time=1)

        # ========== 7. 保持动画，展示旋转效果 ==========
        self.wait(5)
        
        self.play(Transform(hyperboloid, canton_tower))
        self.wait(5)

        # 停止相机旋转
        self.stop_ambient_camera_rotation()
        # 重置相机视角
        self.set_camera_orientation(phi=75 * DEGREES, theta=-60 * DEGREES, zoom = 0.45, focal_distance=300)
        self.wait(2)
