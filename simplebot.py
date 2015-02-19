#!/usr/bin/python
import multiprocessing
import pyfirmata
import termios
import threading
import time
import types

SPEED = 10

LED_FRONTRIGHT = 0
LED_BACKRIGHT  = 1
LED_BACKLEFT   = 2
LED_FRONTLEFT  = 3
LEDS_LEFT      = (2,3)
LEDS_RIGHT     = (0,1)
LEDS_FRONT     = (0,3)
LEDS_BACK      = (1,2)

COLOUR_BLACK  = (0,   0,   0  )
COLOUR_RED    = (255, 0,   0  )
COLOUR_GREEN  = (0,   255, 0  )
COLOUR_BLUE   = (0,   0,   255)
COLOUR_YELLOW = (255, 200, 0  )
COLOUR_VIOLET = (255, 0,   200)
COLOUR_WHITE  = (255, 200, 200)

###
### Controller classes
###

class led_controller():
    indicating = False
    leds = [] # Current state of each led
    def __init__(self, board, num_leds):
        self.board = board # The pyfirmata board instance
        for i in range(num_leds):
            self.leds.append(0)
    def reset(self):
        self.indicate(None)
        for i in range(len(self.leds)):
            self.set(i, COLOUR_BLACK)
        self.push()
    def set(self, led, colour):
        assert led < len(self.leds) and led >= 0
        assert type(colour) == tuple and len(colour) == 3
        assert type(colour[0]) == int and type(colour[1]) == int and type(colour[2]) == int

        # The data sent to the Arduino needs to be an string of numbers that represent 3 bytes of binary for the RGB value
        # with every character separated by spaces for some reason
        self.leds[led] = (colour[0]<<16)+(colour[1]<<8)+colour[2]
    def push(self):
        self.board.send_sysex(0x71, '{ a : 0 }')
        for led in range(len(self.leds)):
            data = '{ %d :%s}' % (led, str(self.leds[led]).replace('', ' '))
            self.board.send_sysex(0x71, data)
        self.board.send_sysex(0x71, '{ s }')

    def _indicator(self, leds):
        state = False
        last_time = 0
        while True:
            if time.time() > last_time + 0.3:
                if  state == False:
                    for i in leds:
                        self.set(i, COLOUR_YELLOW)
                    state = True
                elif state == True:
                    for i in leds:
                        self.set(i, COLOUR_BLACK)
                    state = False
                else:
                    raise Exception('WTF')
                self.push()
                last_time = time.time()
    def indicate(self, leds):
        assert leds == None or (leds[0] < len(self.leds) and leds[0] >= 0 and leds[1] < len(self.leds) and leds[1] >= 0)
        print 'indicating'
        if self.indicating == True:
            print 'terminating'
            self._indicator_process.terminate() # Stop any indicator process currently running
            self.set(self._indicator_process._args[0][0], COLOUR_BLACK) # Reset the state of the LED that process was flashing
            self.set(self._indicator_process._args[0][1], COLOUR_BLACK) # Reset the state of the LED that process was flashing
            self.push()
            self.indicating = False
        if leds != None:
            self.indicating = True
            self._indicator_process = multiprocessing.Process(target=self._indicator, args=[leds], name='indicator %d %d' % leds)
            self._indicator_process.start()

class movement_controller():
    def __init__(self, board, left_pin, right_pin, left_stop=90, right_stop=90):
        self.board       = board
        self.left_stop   = left_stop
        self.right_stop  = right_stop
        self.left_wheel  = board.digital[left_pin]
        self.right_wheel = board.digital[right_pin]
        board.servo_config(self.left_wheel.pin_number,  angle=self.left_stop)
        board.servo_config(self.right_wheel.pin_number, angle=self.right_stop)
    def stop(self):
        self.left_wheel.write(self.left_stop)
        self.right_wheel.write(self.right_stop)
    def forward(self, speed):
        self.left_wheel.write(self.left_stop   + speed)
        self.right_wheel.write(self.right_stop - speed)
    def backward(self, speed):
        self.left_wheel.write(self.left_stop   - speed)
        self.right_wheel.write(self.right_stop + speed)
    def left(self, speed):
        self.left_wheel.write(self.left_stop   - speed)
        self.right_wheel.write(self.right_stop - speed)
    def right(self, speed):
        self.left_wheel.write(self.left_stop   + speed)
        self.right_wheel.write(self.right_stop + speed)

class distance_sensor():
    ### I spent hours trying to makes sense of how the node.js code did all this before giving up and just copying magic numbers from what the node.js code did.
    # FIXME: Make sense of this.
    callback = None
    value    = 0
    cm       = 0
    inches   = 0
    def __init__(self, board, pin): # I don't know enough about the firmata code to separate trigpin and echopin
        self.board = board
        self.pin   = pin
        self.board.add_cmd_handler(0x74, self._response)
    def _response(self, *currentBuffer):
        ### I don't understand how any of this math works, I copied it from the Johnny-five node.js code and thankfully Python's syntax seems to be close enough that I was able to translate it without actually understanding.
        durationBuffer = [ (currentBuffer[2] & 0x7F) | ((currentBuffer[3] & 0x7F) << 7), (currentBuffer[4] & 0x7F) | ((currentBuffer[5] & 0x7F) << 7), (currentBuffer[6] & 0x7F) | ((currentBuffer[7] & 0x7F) << 7), (currentBuffer[8] & 0x7F) | ((currentBuffer[9] & 0x7F) << 7) ]
        duration = (durationBuffer[0] << 24) + (durationBuffer[1] << 16) + (durationBuffer[2] << 8) + (durationBuffer[3])

        # These magic numbers I pulled from the tech specs of the HC-SR04 sensor
        # I don't think I have any choice but to use magic numbers, although they should probably go in a config file somewhere.
        self.value  = duration
        self.cm     = duration / 58.0
        self.inches = duration / 148.0
        if self.callback != None:
            try: self.callback(self.value, self.cm, self.inches)
            except: print "Callback failed"
    def pulse(self, value = 1, pulseOut = 0, timeout = 1000000): # None of these arguments are used until I make sense of the magic numbers
#        data = [
#                self.pin,
#                value,
#                pulseOut,
#                timeout,
#                ]
        data = [ self.pin, 1, 0, 0, 0, 0, 0, 0, 5, 0, 0, 0, 15, 0, 66, 0, 64, 0 ]
        self.board.send_sysex(0x74, data)

###
### State classes
###
class state_handler():
    def __init__(self):
        self.gear = 0
        self.current_states = {}
    def add(self, state_class):
        assert type(state_class) == types.ClassType
        state = state_class(self)
        for conflict in state.conflicts:
            if conflict in self.current_states:
                self.remove(conflict)
        if state.enter_state() == True:
            self.current_states.update({state.name: state})
        return self.current_states
    def remove(self, state):
        assert type(state) == types.ClassType or type(state) == str or type(state) == instance
        if   type(state) == types.InstanceType:
            if state not in self.current_states.value():
                return self.current_states
            else:
                state_name = state.name
        elif type(state) == types.ClassType:
            state_name = state.name
        elif type(state) == str:
            state_name = state
        if state_name in self.current_states:
            self.current_states.pop(state_name).leave_state()
        return self.current_states
    def change_gear(self, gear):
        assert type(gear) == int
        if gear > 6:
            gear = 6
        elif gear < -1:
            gear = -1
        self.gear = gear
        for state_name, state in self.current_states.items():
            if state.gear_change() == False:
                self.current_states.pop(state_name)
        return self.gear
    def shutdown(self):
        keys = self.current_states.keys()
        for state in keys:
            self.remove(state)
class state():
    name         = ''
    conflicts    = []
    dependencies = []
    def __init__(self, handler):
        self.handler = handler
    def gear_change(self):
        return self._on_gear_change()
    def enter_state(self):
        return self._on_enter()
    def leave_state(self):
        return self._on_leave()
    def _on_gear_change(self):
        return True
    def _on_enter(self):
        return True
    def _on_leave(self):
        return True
class gear_up(state):
    name         = 'gear_up'
    conflicts    = ['gear_down']
    def _on_enter(self):
        self.handler.change_gear(self.handler.gear+1)
        return False
class gear_down(state):
    name         = 'gear_down'
    conflicts    = ['gear_up']
    def _on_enter(self):
        self.handler.change_gear(self.handler.gear-1)
        return False
class forward(state):
    name         = 'forward'
    conflicts    = ['indicate_left', 'indicate_right', 'left', 'right', 'brake', 'reverse']
    def _on_gear_change(self):
        return self.go()
    def _on_enter(self):
        return self.go()
    def _on_leave(self):
        move.stop()
        return True
    def go(self):
        if   self.handler.gear <  0:
            self.handler.add(reverse)
            return False
        elif self.handler.gear == 0:
            self.leave_state()
            return False
        elif self.handler.gear >  0:
            self.leave_state()
            move.forward(self.handler.gear*SPEED)
            return True
class reverse(state):
    name         = 'reverse'
    conflicts    = ['indicate_left', 'indicate_right', 'left', 'right', 'brake', 'forward']
    def _on_gear_change(self):
        return self.go()
    def _on_enter(self):
        for i in (LEDS_BACK):
            leds.set(i, COLOUR_WHITE)
        leds.push()
        return self.go()
    def _on_leave(self):
        move.stop()
        return True
    def go(self):
        if   self.handler.gear <  0:
            move.backward(self.handler.gear*-SPEED)
            return True
        elif self.handler.gear == 0:
            self.leave_state()
            return False
        elif self.handler.gear >  0:
            self.leave_state()
            self.handler.add(forward)
            return False
class left(state):
    name         = 'left'
    conflicts    = ['indicate_right', 'right', 'brake', 'forward']
    def _on_gear_change(self):
        return self.go()
    def _on_enter(self):
        return self.go()
    def _on_leave(self):
        move.stop()
        return True
    def go(self):
        if   self.handler.gear <  0:
            move.right(self.handler.gear*-SPEED)
            return True
        elif self.handler.gear == 0:
            self.leave_state()
            return False
        elif self.handler.gear >  0:
            move.left(self.handler.gear*SPEED)
            return True
class right(state):
    name         = 'right'
    conflicts    = ['indicate_left', 'left', 'brake', 'forward']
    def _on_gear_change(self):
        return self.go()
    def _on_enter(self):
        return self.go()
    def _on_leave(self):
        move.stop()
        return True
    def go(self):
        if   self.handler.gear <  0:
            move.left(self.handler.gear*-SPEED)
            return True
        elif self.handler.gear == 0:
            self.leave_state()
            return False
        elif self.handler.gear >  0:
            move.right(self.handler.gear*SPEED)
            return True
class brake(state):
    name         = 'brake'
    conflicts    = ['left', 'right', 'forward', 'reverse']
    def _on_enter(self):
        for i in (LEDS_BACK):
            leds.set(i, COLOUR_RED)
        leds.push()
        move.stop()
        return True
    def _on_leave(self):
        for i in (LEDS_BACK):
            leds.set(i, COLOUR_BLACK)
        leds.push()
        return True
class indicate_left(state):
    name         = 'indicate_left'
    conflicts    = ['indicate_right']
    def _on_enter(self):
        print 'starting left indicator'
        leds.indicate(LEDS_LEFT)
        return True
    def _on_leave(self):
        print 'disabling left indicator'
        leds.indicate(None)
        return True
class indicate_right(state):
    name         = 'indicate_right'
    conflicts    = ['indicate_left']
    def _on_enter(self):
        print 'starting right indicator'
        leds.indicate(LEDS_RIGHT)
        return True
    def _on_leave(self):
        print 'disabling right indicator'
        leds.indicate(None)
        return True

###
### Initialisations
###

## Gears
# <0 = reverse speed = gear*-SPEED
#  0 = stationary
# >0 = forward speed = gear*SPEED
gear = 0

board = pyfirmata.Arduino('/dev/ttyS99')
# Start an iterator thread so that pyfirmata can handle reading pin values and avoid the serial buffer from filling up.
it = pyfirmata.util.Iterator(board)
it.setDaemon(True)
it.start()

move = movement_controller(board,9,10,93,94) # 93 & 94 are magic numbers, but they're my magic numbers. These should be set in a config file in /boot
leds = led_controller(board,4)
dist = distance_sensor(board, 8)
stat = state_handler()

if __name__ == '__main__':
    import sys, tty


    bindings = { # This should probably be configurable, but this is reasonable defaults
        'w':     forward,
        's':     brake,
        'a':     left,
        'd':     right,
        'up':    gear_up,
        'down':  gear_down,
        'left':  indicate_left,
        'right': indicate_right,
    }

    def f():
        while True:
            dist.pulse()
            sys.stdout.write("%d %06.2f %s\n" % (stat.gear, dist.cm, stat.current_states.keys()))
            time.sleep(1)
    t = threading.Thread(target=f)
    t.setDaemon(True)
    t.start()

    old_term_settings = termios.tcgetattr(sys.stdin)
    tty.setcbreak(sys.stdin.fileno())

    board.digital[13].write(1) # Turn on the blink LED to let the user know we are ready to go.
    while True:
        key = sys.stdin.read(1)

        if ord(key) == 4: # ^d
            break
        if ord(key) == 27: # Esc
            key = sys.stdin.read(1)
            if ord(key) == 91: # I don't actually understand the numbers now, but all the arrow keys had this next
                key = sys.stdin.read(1)
                if   ord(key) == 65: # up
                    key = 'up'
                elif ord(key) == 66: # down
                    key = 'down'
                elif ord(key) == 67: # right
                    key = 'right'
                elif ord(key) == 68: # left
                    key = 'left'
        if key in bindings.keys():
            stat.add(bindings[key])

    stat.shutdown()
    board.digital[13].write(0)

    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_term_settings)

# python -i -c 'import pyfirmata,simplebot ; b = pyfirmata.Arduino("/dev/ttyS99") ; it = pyfirmata.util.Iterator(b) ; it.setDaemon(True) ; it.start()'
