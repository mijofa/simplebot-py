#!/usr/bin/python
import multiprocessing
import time

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

class leds():
    _indicator_process = None
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
        while True:
            self.set(leds[0], COLOUR_YELLOW)
            self.set(leds[1], COLOUR_YELLOW)
            self.push()
            time.sleep(0.3)
            self.set(leds[0], COLOUR_BLACK)
            self.set(leds[1], COLOUR_BLACK)
            self.push()
            time.sleep(0.3)
    def indicate(self, leds):
        assert leds == None or (leds[0] < len(self.leds) and leds[0] >= 0 and leds[1] < len(self.leds) and leds[1] >= 0)
        if self._indicator_process != None:
            self._indicator_process.terminate() # Stop any indicator process currently running
            self.set(self._indicator_process._args[0][0], COLOUR_BLACK) # Reset the state of the LED that process was flashing
            self.set(self._indicator_process._args[0][1], COLOUR_BLACK) # Reset the state of the LED that process was flashing
            self.push()
        if leds != None:
            self._indicator_process = multiprocessing.Process(target=self._indicator, args=[leds], name='indicator %d %d' % leds)
            self._indicator_process.start()

class move():
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

class dist():
    ### I spent hours trying to makes sense of how the node.js code did all this before giving up and just copying magic numbers from what the node.js code did.
    # FIXME: Make sense of this.
    callback = None
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
            try: self.callback()
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

if __name__ == '__main__':
    import sys, tty
    import pyfirmata

    fd = sys.stdin.fileno()
    tty.setcbreak(fd)


    b = pyfirmata.Arduino('/dev/ttyS99')
    m = move(b,9,10,93,94) # 93 & 94 are magic numbers, but they're my magic numbers. These should be set in a config file in /boot
    l = leds(b,4)

    b.digital[13].write(1) # Turn on the blink LED to let the user know we are ready to go.
    while True:
        key = sys.stdin.read(1)
        sys.stdout.write(key)
        if key    == '1':
            l.indicate(None)
        elif key  == 'q':
            l.indicate(LEDS_LEFT)
        elif key == 'w':
            l.indicate(None)
            m.forward(30)
        elif key == 'e':
            l.indicate(LEDS_RIGHT)
        elif key == 'a':
            m.left(30)
        elif key == 's':
            l.indicate(None)
            m.backward(30)
        elif key == 'd':
            m.right(30)
        elif key == ' ':
            m.stop()
            l.indicate(None)
        elif key == '\x04': # ^d
            break

    b.digital[13].write(0)
    l.indicate(None)
    m.stop()
