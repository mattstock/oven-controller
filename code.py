import time
import board
import digitalio
import busio
import rotaryio
from adafruit_max31855 import MAX31855
from adafruit_debouncer import Debouncer
from sparkfun_serlcd import Sparkfun_SerLCD_I2C

pinsetup = {
  'therm0': board.D12,
  'therm1': board.D11,
  'relay0': board.D5,
  'relay1': board.D6,
  'r': board.D13,
  'g': board.D9,
  'b': board.D10,
  'encoderA': board.A3,
  'encoderB': board.A2,
  'button': board.A0
  }

def init_hw():
    # Display
    i2c = busio.I2C(board.SCL, board.SDA)
    display = Sparkfun_SerLCD_I2C(i2c)
    display.clear()
    
    # Thermocouples
    spi = busio.SPI(board.SCK, MOSI=board.MOSI, MISO=board.MISO)
    therm0 = MAX31855(spi, digitalio.DigitalInOut(pinsetup['therm0']))
    therm1 = MAX31855(spi, digitalio.DigitalInOut(pinsetup['therm1']))

    # Relays (high to enable because we go through the transistor switch)
    relay0 = digitalio.DigitalInOut(pinsetup['relay0'])
    relay0.direction = digitalio.Direction.OUTPUT
    relay0.value = False
    relay1 = digitalio.DigitalInOut(pinsetup['relay1'])
    relay1.direction = digitalio.Direction.OUTPUT
    relay1.value = False

    # Encoder setup
    enc = rotaryio.IncrementalEncoder(pinsetup['encoderA'], pinsetup['encoderB'])
    pb = digitalio.DigitalInOut(pinsetup['button'])
    pb.direction = digitalio.Direction.INPUT
    pb.pull = digitalio.Pull.DOWN
    switch = Debouncer(pb)
    
    # RGB on dial (low to enable)
    r = digitalio.DigitalInOut(pinsetup['r'])
    r.direction = digitalio.Direction.OUTPUT
    r.value = True
    g = digitalio.DigitalInOut(pinsetup['g'])
    g.direction = digitalio.Direction.OUTPUT
    g.value = True
    b = digitalio.DigitalInOut(pinsetup['b'])
    b.direction = digitalio.Direction.OUTPUT
    b.value = True
    
    return (display, therm0, therm1, relay0, relay1, enc, switch, (r,g,b))

# A simple state machine class.  The active state motifies the function pointer to change the next state as needed.
# The main loop simply runs run(), which calls the state.
class StateMachine(object):
    def __init__(self):
        self.target = 60.0
        self.duration = 180

        self.endtime = 0
        self.state = getattr(self, 'state_start', lambda: 'Invalid state')

        self.last_temp0 = None
        self.last_temp1 = None
        self.last_time = None
        self.waitstart = None
        self.last_position = None

    def run(self):
        self.state()
        
    def state_start(self):
        display.clear()
        display.set_fast_backlight_rgb(255,255,255)
        display.write("Oven Control 1.0")
        display.set_cursor(0,1)
        display.write("Press button")
        self.state = getattr(self, 'state_idle', lambda: 'Invalid state')

    def state_idle(self):
        if switch.rose:
            self.last_position = None
            self.waitstart = time.time()
            self.state = getattr(self, 'state_settemp', lambda: 'Invalid state')

    def state_settemp(self):
        curtime = time.time()
        position = encoder.position
        if self.last_position == None:
            print("initial")
            self.last_position = position
            display.set_fast_backlight_rgb(0,0,255)
            display.clear()
            display.set_cursor(0,1)
            display.write("Duration: {:3}".format(self.duration))
            display.set_cursor(0,0)
            display.write("Target: {:4.1f}C".format(self.target))
            display.blink(True)
        if position != self.last_position:
            self.target += (position - self.last_position)/10.0
            display.set_cursor(8,0)
            display.write("{:4.1f}C".format(self.target))
        self.last_position = position
        if curtime - self.waitstart >= 20:
            self.state = getattr(self, 'state_start', lambda: 'Invalid state')
        if switch.rose:
            self.waitstart = curtime
            self.last_position = None
            self.state = getattr(self, 'state_setduration', lambda: 'Invalid state')
        
    def state_setduration(self):
        position = encoder.position
        curtime = time.time()
        if self.last_position == None:
            display.set_cursor(10,1)
            display.write("{:3}".format(self.duration))
            self.last_position = position      
        if position != self.last_position:
            self.duration += position - self.last_position
            display.set_cursor(10,1)
            display.write("{:3}".format(self.duration))
            self.last_position = position
        if curtime - self.waitstart >= 20:
            self.state = getattr(self, 'state_start', lambda: 'Invalid state')
        if switch.rose:
            display.blink(False)
            self.endtime = curtime + self.duration*60
            self.last_temp = None
            self.last_time = None
            self.state = getattr(self, 'state_checktemp', lambda: 'Invalid state')

    def state_startheat(self):
        curtime = time.time()
        display.set_fast_backlight_rgb(255,0,0)
        display.clear()
        display.set_cursor(0,1)
        display.write("Remaining: ")
        relay0.value = True
        self.waitstart = curtime
        self.state = getattr(self, 'state_heat', lambda: 'Invalid state')

    def state_heat(self):
        curtime = time.time()
        curtemp0 = therm0.temperature
        curtemp1 = therm1.temperature
        if switch.rose:
            relay0.value = False
            relay1.value = False
            self.state = getattr(self, 'state_startcomplete', lambda: 'Invalid state')
        if self.last_temp == None or self.last_temp0 != curtemp0 or self.last_temp1 != curtemp1:
            display.set_cursor(0,0)
            display.write("{:3.1f} / {:3.1f}".format(curtemp0, curtemp1))
            self.last_temp0 = curtemp0
            self.last_temp1 = curtemp1
        if self.last_time == None or self.last_time != curtime:
            display.set_cursor(11,1)
            display.write("{:3}".format(int((self.endtime-curtime)/60)))
            self.last_time = curtime
        # Should think about running shorter cycles when we're close to temp
        if curtime - self.waitstart >= 10:
            self.state = getattr(self, 'state_startsoak', lambda: 'Invalid state')
        
    def state_startsoak(self):
        relay0.value = False
        display.set_fast_backlight_rgb(0,255,0)
        self.waitstart = time.time()
        self.state = getattr(self, 'state_soak', lambda: 'Invalid state')
        
    def state_soak(self):
        curtime = time.time()
        curtemp0 = therm0.temperature
        curtemp1 = therm1.temperature
        if switch.rose:
            relay0.value = False
            relay1.value = False
            self.state = getattr(self, 'state_startcomplete', lambda: 'Invalid state')
        if self.last_temp == None or self.last_temp0 != curtemp0 or self.last_temp1 != curtemp1:
            display.set_cursor(0,0)
            display.write("{:3.1f} / {:3.1f}".format(curtemp0, curtemp1))
            self.last_temp0 = curtemp0
            self.last_temp1 = curtemp1
        if self.last_time == None or self.last_time != curtime:
            display.set_cursor(11,1)
            display.write("{:3}".format(int((self.endtime-curtime)/60)))
            self.last_time = curtime
        if curtime - self.waitstart >= 10:
            self.state = getattr(self, 'state_checktemp', lambda: 'Invalid state')
        
    def state_checktemp(self):
        curtime = time.time()
        relay1.value = True # Turn on light for the toasting cycle
        curtemp0 = therm0.temperature
        curtemp1 = therm1.temperature
        print(self.endtime-curtime)
        if curtime >= self.endtime:
            print("Idling")
            self.state = getattr(self, 'state_start', lambda: 'Invalid state')
        else:
            if (self.target - curtemp0) < 2.0 or (self.target - curtemp1) < 2.0:
                print("Wait another 10s since we're near target temp")
                self.state = getattr(self, 'state_startsoak', lambda: 'Invalid state')
            else:
                print("Not hit target yet, so running another heating cycle")
                self.state = getattr(self, 'state_startheat', lambda: 'Invalid state')

    def state_startcomplete(self):
        curtime = time.time()
        relay1.value = False # Shut off lamp
        self.waitstart = time.time()
        display.clear()
        display.set_fast_backlight_rgb(0,255,255)
        display.write('Finished!')
        self.state = getattr(self, 'state_complete', lambda: 'Invalid state')
    
    def state_complete(self):
        curtime = time.time()
        if curtime - self.waitstart >= 3:
            self.state = getattr(self, 'state_start', lambda: 'Invalid state')
        
(display, therm0, therm1, relay0, relay1, encoder, switch, rgb) = init_hw()
state = StateMachine()

# Need to add simple try/except block to make sure that the controller always disables relays
while True:
    switch.update()
    state.run()
    time.sleep(0.1)
print('end of the world')
