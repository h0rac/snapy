
from snapy import snapy
import pandas as pd
import matplotlib.pyplot as plt
from raiden_python import raiden 
import time
raiden = raiden.Raiden(mhz=200, serial_dev="/dev/tty.usbserial-210319A279441", baud= 115200, ticks= True, debug=True) 


snapy = snapy.Snapy(x =9, y=10, offset=1, jog=500, sleep=0.4)

curr_pos = snapy.get_current_pos()
print("[+] Current position: {}".format(curr_pos))

raiden.reset_glitcher()
raiden.arm(0)

print(raiden.get_buildtime())
raiden.set_param(param="CMD_VSTART", value=1)
raiden.set_param(param="CMD_GLITCH_MAX", value= 1)

raiden.set_target_power("off")
time.sleep(1)
raiden.set_target_power("on")
time.sleep(1)

x = 0
y = 0

pos = None

while y < snapy.get_y_max_steps():
    x = 0
    pos = self.get_current_pos()
    snapy.record(pos)
    while x < snapy.get_x_max_steps():     
      x += 1
      raiden.set_target_power("auto")
      raiden.arm(0)  
      raiden.reset_glitcher()     
      raiden.set_param(param="CMD_GLITCH_DELAY", value= 0)
      raiden.set_param(param="CMD_GLITCH_WIDTH", value= 800)
      raiden.set_param(param="CMD_GLITCH_GAP", value= 5)
      raiden.set_param(param="CMD_GLITCH_COUNT", value= 1)
      raiden.set_param(param="CMD_UART_TRIGGER", value= 0x64)
      raiden.set_param(param="CMD_UART_TRIGGER_BAUD", value=0x1c200)
      raiden.arm(1)
      snapy.step(fwd=True, x=True)
      while not raiden.is_finished():
          pass
    y +=1
    snapy.step(fwd=False, x=False)
    print("glitch cycle done")

pos = snapy.get_current_pos()
print("[+] End position: {}".format(pos))
snapy.go_start_position(pos, curr_pos)

read_file = pd.read_csv (r'coords.csv')
read_file.to_excel (r'coords-test.xlsx', index = None, header=True)

snapy.device.close()
snapy.f.close()