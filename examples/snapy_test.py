
from snapy import snapy

snapy = snapy.Snapy(x =10, y=10, offset=0.1, jog=1500, sleep=0.5)
curr_pos = snapy.get_current_pos()
print("[+] Current position: {}".format(curr_pos))

pos = snapy.start()
print("[+] End position: {}".format(pos))

snapy.go_start_position(pos, curr_pos)

start_pos = snapy.get_current_pos()
print("[+] Start position: {}".format(start_pos))

snapy.device.close()