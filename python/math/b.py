from manim import *
from functools import reduce

def init_config(obj,config):
    for k in config.keys():
        try:
            getattr(obj,k)
        except Exception as e:
            print('set', k, config[k])
            setattr(obj,k,config[k])

def rotate(points, angle=np.pi, axis=OUT):
    if axis is None:
        return points
    matrix = rotation_matrix(angle, axis)
    points = np.dot(points, np.transpose(matrix))
    return points

class FractalCurve(VMobject):
    init_data = {
        "radius": 3,
        "order": 5,
        "colors": [RED, GREEN],
        "num_submobjects": 20,
        "monochromatic": False,
        "order_to_stroke_width_map": {
            2: 3,
            3: 3,
            4: 2.5,
            5: 2.3,
            6: 2.1,
            7: 1.9,
            8: 1.7,
            9: 1.5,
            10: 1.3,
            11: 1.1,
        },
    }

    def __init__(self,order=5, **kwargs):
         FractalCurve.init_data.update(kwargs)
         init_config(self,FractalCurve.init_data)
         super(FractalCurve, self).__init__(**kwargs)


    def generate_points(self):
        points = self.get_anchor_points()
        self.set_points_as_corners(points)
        # 这里主要是为去曲线填上渐变色做准备，把曲线打散成20个对象
        if not self.monochromatic:
            alphas = np.linspace(0, 1, self.num_submobjects)
            for alpha_pair in zip(alphas, alphas[1:]):
                submobject = VMobject()
                submobject.pointwise_become_partial(
                    self, *alpha_pair
                )
                self.add(submobject)
            self.set_points(np.zeros((0, 3)))

    init_points = generate_points

    def init_colors(self):
        VMobject.init_colors(self)
        self.set_color_by_gradient(*self.colors)
        # 低阶曲线，线宽可以粗一点，高阶把线宽改细
        for order in sorted(self.order_to_stroke_width_map.keys()):
            if self.order>= order:
                self.set_stroke(width=self.order_to_stroke_width_map[order])

    def get_anchor_points(self):
        raise Exception("Not implemented")

# 自相似的空间填充曲线计算
class SelfSimilarSpaceFillingCurve(FractalCurve):
    # 自相似的基本规则可以在子类中继承并修改
    init_data = {
        "offsets": [],
        # keys must awkwardly be in string form...
        "offset_to_rotation_axis": {},
        "scale_factor": 2,
        "radius_scale_factor": 0.5,
    }

    def __init__(self,**kwargs):
         SelfSimilarSpaceFillingCurve.init_data.update(kwargs)
         init_config(self,SelfSimilarSpaceFillingCurve.init_data)
         super(SelfSimilarSpaceFillingCurve, self).__init__(**kwargs)

    # 每一个点的分形处理，根据曲线规则，复制出来，该反转的就翻转，然后缩小并移动到合适的位置
    def transform(self, points, offset):
        """
        How to transform the copy of points shifted by
        offset.  Generally meant to be extended in subclasses
        """
        copy = np.array(points)
        if str(offset) in self.offset_to_rotation_axis:
            copy = rotate(
                copy,
                axis=self.offset_to_rotation_axis[str(offset)]
            )
        copy /= self.scale_factor,
        copy += offset * self.radius * self.radius_scale_factor
        return copy

    # 整体分形，将上一阶每一个关键点，根据曲线规则，计算出下一阶位置，最后将这些计算出的点全部收集起来
    def refine_into_subparts(self, points):
        transformed_copies = [
            self.transform(points, offset)
            for offset in self.offsets
        ]

        return reduce(
            lambda a, b: np.append(a, b, axis=0),
            transformed_copies
        )

    def get_anchor_points(self):
        # 初始化点在原点
        points = np.zeros((1, 3))
        # 每一阶计算一遍，扩充曲线完整的所有关键点信息
        for count in range(self.order):
            points = self.refine_into_subparts(points)
        return points

    def generate_grid(self):
        raise Exception("Not implemented")

class HilbertCurve(SelfSimilarSpaceFillingCurve):
    # 希尔伯特曲线基本规则在此，包括子部件位置，顺序和翻转信息
    init_data = {
        "offsets": [
            LEFT + DOWN,
            LEFT + UP,
            RIGHT + UP,
            RIGHT + DOWN,
        ],
        "offset_to_rotation_axis": {
            str(LEFT + DOWN): RIGHT + UP,
            str(RIGHT + DOWN): RIGHT + DOWN,
        },
    }

    def __init__(self,**kwargs):
         HilbertCurve.init_data.update(kwargs)
        #  print(&#39;HilbertCurve:data&#39;,HilbertCurve.init_data)
         init_config(self,HilbertCurve.init_data)
         super(HilbertCurve, self).__init__(**kwargs)

class HilbertCurve_Scene(Scene):
    def construct(self):
        # 从一阶希尔伯特曲线开始
        last_curve = HilbertCurve(order = 1)
        self.add(last_curve)
        self.wait(1)

        # 开始从第一阶到第十一阶的动画效果
        for i in range(1,10):
            # 准备好下一阶的曲线备用
            order_next_curve = HilbertCurve(order = (i+1))
            # 准备当前阶的曲线三份备用，放在画面右上，左下，右下三个位置
            mini_curves = [
                HilbertCurve(order = i).scale(0.5).shift(1.5*vect)
                for vect in [
                    LEFT+DOWN,
                    RIGHT+UP,
                    RIGHT+DOWN
                ]
            ]

            # 一边把当前阶的曲线缩小到左上位置
            # 一边让右上，左下，右下三个位置淡入
            self.play(*list(map(FadeIn, mini_curves)),
                    last_curve.animate(run_time = 1).scale(0.5).shift(1.5*(LEFT+UP)),
                    run_time = 1.1,
                    rate_func=smooth)

            # 左上位置的曲线加入队伍整体
            mini_curves.insert(1, last_curve)

            # 左下和右下两个曲线翻转一下
            self.play(*[
                ApplyMethod(curve.rotate, np.pi, axis)
                for curve, axis in [
                    (mini_curves[0], UP+RIGHT),
                    (mini_curves[3], UP+LEFT)
                ]
            ], run_time = 1, rate_func=smooth)

            # 用下一阶的曲线快速取代整体现有四个曲线集合
            self.play(FadeIn(order_next_curve, run_time = 0.1))
            self.play(*list(map(FadeOut, mini_curves)), run_time = 0.1)

            last_curve = order_next_curve

        self.wait(2)
        
# if __name__ == "__main__":
#     scene = HilbertCurve_Scene()
#     scene.render()