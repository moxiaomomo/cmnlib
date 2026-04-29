from manimlib import *
from manim import *

import numpy as np

class Scene1(ThreeDScene):
    def construct(self):
        self.set_camera_orientation(zoom = 0.6)
        
        axes = ThreeDAxes()
        cos_graph = axes.plot(lambda x: np.cos(x), color = RED)
        curve = ParametricFunction(lambda x: np.array([np.sin(x), np.cos(x), x/2]), color = BLUE, t_range = (-TAU, TAU))
        
        t = Text("Example").to_edge(UL)
        self.add_fixed_in_frame_mobjects(t)

        self.play(Write(axes), Write(t))
        self.play(Write(cos_graph))
        self.move_camera(phi=60*DEGREES, theta=-45*DEGREES)
        self.play(Write(curve))
        self.move_camera(phi=30*DEGREES, theta=-45*DEGREES)
        self.wait(2)

        g = VGroup(curve, cos_graph, t, axes)
        self.play(Unwrite(g), run_time = 1.5)
        self.wait()

# class SquareToCircle(Scene):
#     def construct(self):
#         circle = Circle()
#         circle.set_fill(BLUE, opacity=0.5)
#         circle.set_stroke(BLUE_E, width=4)
#         square = Square()

#         self.play(ShowCreation(square))
#         self.wait()
#         self.play(ReplacementTransform(square, circle))
#         self.wait()

class AIHistory(Scene):
    def construct(self):
        # Define the history events
        history = [
            "1956: The term 'Artificial Intelligence' is coined at the Dartmouth Conference.",
            "1966: ELIZA, an early natural language processing computer program, is created.",
            "1980: The first AI winter begins, a period of reduced funding and interest in AI research.",
            "1997: IBM's Deep Blue defeats world chess champion Garry Kasparov.",
            "2011: IBM's Watson wins Jeopardy! against human champions.",
            "2016: Google's AlphaGo defeats world champion Go player Lee Sedol.",
            "2020: OpenAI's GPT-3, a powerful language model, is released."
        ]

        # Create a title
        title = Text("AI Development History").scale(1.2)
        self.play(FadeIn(title))
        self.wait(1)
        self.play(title.animate.to_edge(UP))

        # Animate each history event
        for event in history:
            event_text = Text(event, font_size=24)
            self.play(FadeIn(event_text))
            self.wait(2)
            self.play(FadeOut(event_text))

        # End with a thank you message
        thank_you = Text("Thank you for watching!").scale(1.2)
        self.play(FadeIn(thank_you))
        self.wait(2)
        
class CurveDemo(Scene):
    """docstring for CurveDemo"""

    def construct(self):
        curve = PeanoCurve()
        self.play(ShowCreation(curve), run_time=20)

if __name__ == "__main__":
    scene = Scene1() #AIHistory()
    scene.render()