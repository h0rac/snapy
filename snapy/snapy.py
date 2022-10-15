import serial
import time
import csv
import sys

class Snapy:
  def __init__(self, baud= 115200, dev="/dev/dev_snapy_xyz", x=None, y=None, z=None, offset=None, move=None, jog=200):
    self.baud = baud
    self.device = serial.Serial(dev, baudrate= baud, timeout=3.5, writeTimeout=2.5)
    self.jog_speeds = [3000, 1500, 500, 200]
    self.axis_offsets = [10, 1, 0.1, 0.05]
    if not offset in self.axis_offsets:
      print("[-] Unsupported offset value, please select {}".format(self.axis_offsets))
      return -1
    self.cmd = b''
    self.x = x
    self.y = y
    self.jog = jog
    self.offset = offset
    self.steps = None
    self.max_step_x = None
    self.max_step_y = None
    self.f = open('coords.csv', 'w')
    self.writer = csv.writer(self.f)
    headers = ['X', 'Y', 'Z', 'RESULT']
    self.writer.writerow(headers)


  def _send_gcode_cmd(self, cmd):
    # print(cmd)
    self.device.write(b"G91\n")    
    resp =  self.device.read_until(b'ok')
    # print(resp)
    if b'ok' in resp:
      # print(cmd)
      resp = self.device.write(cmd+b"\n")
      resp =  self.device.read_until(b'ok')
      # print(resp)
      if b'ok' in resp:
         cmd = b"G90"
         # print(cmd)
         resp = self.device.write(cmd+b"\n")
         resp =  self.device.read_until(b'ok')
         # print(resp)
         if not b'ok' in resp:
            print("[-] error on gcode command")
            sys.exit(1)

  def _send_marlin_cmd(self,cmd):   
    # print("cmd", cmd)
    self.device.write(cmd+b"\n")
    raw =  self.device.read_until(b'ok')
    # print("raw", raw)
    if b'ok' in raw:  
      return raw

  def set_chip_params(self, x=None, y=None, offset=1):
    if not offset in self.axis_offsets:
      print("[-] Unsupported offset value, please select {}".format(self.axis_offsets))
      return -1
    self.offset = offset
    self.x = x
    self.y = y

  def _xy_max_steps(self):
    self.max_step_x = float(self.x / self.offset)
    self.max_step_y = float(self.y / self.offset)
    return (self.max_step_x, self.max_step_y)


  def get_current_pos(self):
    cmd = b"M114"
    position = self._send_marlin_cmd(cmd).decode()
    x,y,z = position.split()[0:3]
    x = x.split(':')
    y = y.split(':')
    z = z.split(':')
    temp = x +y + z
    temp =  {temp[i]: temp[i + 1] for i in range(0, len(temp), 2)}
    temp = {k:float(v) for k,v in temp.items()}
    return temp

  def go_start_position(self, curr_pos=None, last_pos=None):
    x =  curr_pos.get('X') - last_pos.get('X')
    y =  curr_pos.get('Y') - last_pos.get('Y')
    z =  curr_pos.get('Z') - last_pos.get('Z')

    cmd = "G0 X-{} Y-{} Z-{} F{}".format(x, y, z, self.jog).encode()
    self._send_gcode_cmd(cmd)
    return {"X":x, "Y": y, "Z":z}


  def go_last_postion(self, pos=None):
    cmd = "G0 X+{} Y+{} Z-{} F{}".format(pos.get('X'), pos.get("Y"), pos.get("Z"), self.jog).encode()
    self._send_gcode_cmd(cmd)


  def get_x_max_steps(self):
    return self._xy_max_steps()[0]

  def get_y_max_steps(self):
    return self._xy_max_steps()[1]

  def record(self, pos, status=0):
    pos["status"] = status
    print(pos)
    self.writer.writerow(pos.values())


  def step(self, z=None, x=None, y=None, fwd=None, axis_x=None, status=0):
    if not self.jog in self.jog_speeds:
      print("[-] Unsupported jog speed, please select {}".format(self.jog_speeds))
      return -1
    self.cmd = b"G0 {}"
    sign = "+"
    if fwd:
      sign = ""
    else:
      sign = "-"
    if axis_x:
      cmd = "G0 X{}{} F{}".format(sign, self.offset, self.jog).encode()
      self._send_gcode_cmd(cmd) 
      pos = self.get_current_pos()
      self.record(pos, status=status) 
    else:
      cmd = "G0 Y{} F{}".format(self.offset, self.jog).encode()
      self._send_gcode_cmd(cmd)  

  def home(self):
    self._send_gcode_cmd(b"G53")
    self._send_gcode_cmd(b"G28")