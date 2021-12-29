
from snapy import snapy
import pandas as pd
import matplotlib.pyplot as plt
import time

snapy = snapy.Snapy(x =9, y=10, offset=1, jog=500, sleep=0.4)

curr_pos = snapy.get_current_pos()
print("[+] Current position: {}".format(curr_pos))

x = 0
y = 0

pos = None
fwd = True
while y < snapy.get_y_max_steps():
    x = 0
    pos = snapy.get_current_pos()
    snapy.record(pos)
    while x < snapy.get_x_max_steps():     
      x += 1
      snapy.step(fwd=fwd, axis_x=True, x=x, y=y)
    y +=1
    fwd = not fwd
    snapy.step(fwd=fwd, axis_x=False, x=x, y=y)

pos = snapy.get_current_pos()
print("[+] End position: {}".format(pos))
snapy.go_start_position(pos, curr_pos)

snapy.f.close()
read_file = pd.read_csv (r'coords.csv')
read_file.to_excel (r'coords.xlsx', index = None, header=True)

snapy.device.close()