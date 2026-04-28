import matplotlib.pyplot as plt
import numpy as np

def sin(start, end):
    x = np.linspace(start, end, num=1000)
    return x, np.sin(x)

start = -10
end = 10
data_x, data_y = sin(start, end)

figure,axes = plt.subplots(figsize=(8, 6))
axes.plot(data_x, data_y, label='sin(x)')
axes.legend()
axes.grid()
axes.set_title('Sine Function')
axes.set_xlabel('x')

plt.show()