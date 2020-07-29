#!/usr/bin/python3

import RPi.GPIO as GPIO
import time
import math
import os
from threading import Timer
from queue import Queue, Empty
from lcd import lcd_init, lcd_byte, lcd_string, LCD_CMD, LCD_CHR, LCD_LINE_1
from temp import current_temperature

MODE_FILE=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'mode.txt')
CLICK_FILE=os.path.join(os.path.dirname(os.path.realpath(__file__)), 'click')

EVENT_LONG_PRESS = 'long-press'
EVENT_CLICK = 'click'
EVENT_DOUBLE_CLICK = 'double-click'

EVENT_SMALL_TANK_FLOAT_ON = 'small-tank-float-on'
EVENT_SMALL_TANK_FLOAT_OFF = 'small-tank-float-off'
EVENT_LARGE_TANK_BOTTOM_FLOAT_ON = 'large-tank-bottom-float-on'
EVENT_LARGE_TANK_BOTTOM_FLOAT_OFF = 'large-tank-bottom-float-off'
EVENT_LARGE_TANK_TOP_FLOAT_ON = 'large-tank-top-float-on'
EVENT_LARGE_TANK_TOP_FLOAT_OFF = 'large-tank-top-float-off'
EVENT_TRANSFER_PUMP_OFF = 'transfer-pump-off'
EVENT_MISTING_PUMP_OFF = 'misting-pump-off'
EVENT_COOLING_STOP = 'cooling-stop'

EVENT_WANT_TO_MIST = 'want-to-mist'
EVENT_DONT_WANT_TO_MIST = 'dont-want-to-mist'

EVENT_BUTTON_DOWN = 'btn-down'
EVENT_BUTTON_UP = 'btn-up'

EVENT_SINGLE_CLICK_TIMEOUT = 'single-click-timeout'
EVENT_LONG_PRESS_TIMEOUT = 'long-press-timeout'

EVENT_REVERT_TEXT='revert-text'
EVENT_IDLE='idle'
EVENT_DISPLAY_LINE='disp-line'
EVENT_FLASH_LED='flash-led'
EVENT_RESET_DISPLAY='reset-display'

MODE_ALWAYS_OFF = 0
MODE_VENTING = 1
MODE_ALWAYS_ON = 2
MODE_THERMOSTAT = 3

GPIO_SMALL_TANK_FLOAT = 25
GPIO_LARGE_TANK_TOP_FLOAT = 7
GPIO_LARGE_TANK_BOTTOM_FLOAT = 8
GPIO_BUTTON = 24
GPIO_LED_1 = 18
GPIO_LED_2 = 23
GPIO_TRANSFER_PUMP = 11
GPIO_MISTING_PUMP = 14

TIMESECS_IDLE_EVENT = 10
TIMESECS_LINE_1 = 5
TIMESECS_LINE_2 = 1.5
TIMESECS_LINE_3 = 1.5
TIMESECS_LED_FLASH = 0.5
TIMESECS_TRANSFER_PUMP = 10
TIMESECS_MISTING_PUMP = 30
TIMESECS_VENTING_PUMP = 120
TIMESECS_SHOW_MESSAGE = 5
TIMESECS_DOUBLE_CLICK = 0.5
TIMESECS_LONG_PRESS = 2
TIMESECS_RESET_DISPLAY = 45
TIMESECS_COOLING_TIME = 300

CUSTOM_CHAR_DEGREE = chr(0x01)
CUSTOM_CHAR_UPARROW = chr(0x02)
CUSTOM_CHAR_DNARROW = chr(0x03)
CHAR_DATA = [
        0b00000,
        0b00000,
        0b00000,
        0b00000,
        0b00000,
        0b00000,
        0b00000,
        0b00000,

        0b00110,
        0b01001,
        0b01001,
        0b00110,
        0b00000,
        0b00000,
        0b00000,
        0b00000,

        0b00100,
        0b01110,
        0b10101,
        0b00100,
        0b00100,
        0b00100,
        0b00100,
        0b00000,

        0b00100,
        0b00100,
        0b00100,
        0b00100,
        0b10101,
        0b01110,
        0b00100,
        0b00000,
]

class StateMachine:

    def __init__(self):

        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(GPIO_LED_1, GPIO.OUT)
        GPIO.setup(GPIO_LED_2, GPIO.OUT)
        GPIO.setup(GPIO_MISTING_PUMP, GPIO.OUT)
        GPIO.setup(GPIO_TRANSFER_PUMP, GPIO.OUT)
        GPIO.setup(GPIO_BUTTON, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        GPIO.setup(GPIO_SMALL_TANK_FLOAT, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(GPIO_LARGE_TANK_TOP_FLOAT, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(GPIO_LARGE_TANK_BOTTOM_FLOAT, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        self.event_queue = Queue()
        self.button_presses = [ None ] * 100 # big enough that a user can't click the button this many times within the long press timeout
        self.button_press_counter = 0

        try:
            with open(MODE_FILE, 'r') as mode_file:
                self.mode = int(mode_file.readline())
                if self.mode != MODE_ALWAYS_OFF and self.mode != MODE_VENTING and self.mode != MODE_ALWAYS_ON:
                    raise ValueError
        except:
            self.mode = MODE_VENTING

        self.thermostat_temp = 0
        self.small_tank_float = False
        self.large_tank_bottom_float = False
        self.large_tank_top_float = False
        self.transfer_pump = False
        self.misting_pump = False
        self.want_to_mist = False
        self.venting = False
        self.show_text = None
        self.showing_line = 0
        self.flash_led_on = True
        self.current_text = ''
        self.button_pressed = False
        self.cooling_count = 0

        GPIO.add_event_detect(GPIO_BUTTON, GPIO.BOTH, callback=self.button_changed, bouncetime=100)

        lcd_byte(0x40, LCD_CMD)
        for byte in CHAR_DATA:
            lcd_byte(byte, LCD_CHR)

        self.express_state()
        self.post_event(EVENT_DISPLAY_LINE)
        self.post_event(EVENT_FLASH_LED)
        self.post_event(EVENT_RESET_DISPLAY)

    def button_changed(self, channel):
        wait_till_stable = 0.5
        while True:
            button_state = GPIO.input(GPIO_BUTTON)
            if button_state != self.button_pressed or wait_till_stable <= 0:
                break
            time.sleep(0.01)
            wait_till_stable -= 0.01

        if button_state == self.button_pressed:
            return

        self.button_pressed = button_state
        self.post_event(EVENT_BUTTON_DOWN if button_state else EVENT_BUTTON_UP, time.time())

    def update_display(self):
        if self.show_text:
            message = self.show_text

        elif self.button_pressed:
            # don't change the display while button is pressed - it's confusing
            return

        elif self.mode == MODE_ALWAYS_OFF:
            if self.showing_line == 1:
                message = 'Off'
            elif self.showing_line == 2:
                message = 'Please empty'
            else:
                message = 'Water buckets'

        elif self.mode == MODE_VENTING:
            if self.venting:
                message = 'Venting'
            else:
                if self.showing_line == 1:
                    message = 'Standby'
                else:
                    message = 'Temp now %.1f%sC' % (current_temperature(), CUSTOM_CHAR_DEGREE)
        else:
            if self.showing_line == 1:
                if not self.large_tank_bottom_float:
                    message = 'No water in tank'
                else:
                    message = 'Misting active'
            else:
                message = 'Temp now %.1f%sC' % (current_temperature(), CUSTOM_CHAR_DEGREE)

        if message != self.current_text:
            lcd_string(message, LCD_LINE_1)
            print(message)
            self.current_text = message

    def express_state(self):
        if self.mode == MODE_ALWAYS_OFF:
            GPIO.output(GPIO_LED_1, False)
            GPIO.output(GPIO_MISTING_PUMP, False)
            GPIO.output(GPIO_LED_2, False)
            GPIO.output(GPIO_TRANSFER_PUMP, False)
        else:
            GPIO.output(GPIO_LED_1, self.misting_pump and (self.flash_led_on or not self.venting))
            GPIO.output(GPIO_MISTING_PUMP, self.misting_pump)
            GPIO.output(GPIO_LED_2, self.transfer_pump)
            GPIO.output(GPIO_TRANSFER_PUMP, self.transfer_pump)

        self.update_display()

    def validate_state(self):
        if os.path.isfile(CLICK_FILE):
            os.remove(CLICK_FILE)
            self.post_event(EVENT_CLICK)

        if not GPIO.input(GPIO_SMALL_TANK_FLOAT) and self.small_tank_float:
            self.post_event(EVENT_SMALL_TANK_FLOAT_OFF)

        if GPIO.input(GPIO_SMALL_TANK_FLOAT) and not self.small_tank_float:
            self.post_event(EVENT_SMALL_TANK_FLOAT_ON)

        if not GPIO.input(GPIO_LARGE_TANK_TOP_FLOAT) and self.large_tank_top_float:
            self.post_event(EVENT_LARGE_TANK_TOP_FLOAT_OFF)

        if GPIO.input(GPIO_LARGE_TANK_TOP_FLOAT) and not self.large_tank_top_float:
            self.post_event(EVENT_LARGE_TANK_TOP_FLOAT_ON)

        if not GPIO.input(GPIO_LARGE_TANK_BOTTOM_FLOAT) and self.large_tank_bottom_float:
            self.post_event(EVENT_LARGE_TANK_BOTTOM_FLOAT_OFF)

        if GPIO.input(GPIO_LARGE_TANK_BOTTOM_FLOAT) and not self.large_tank_bottom_float:
            self.post_event(EVENT_LARGE_TANK_BOTTOM_FLOAT_ON)

        last_want_to_mist = self.want_to_mist
        self.want_to_mist = self.mode == MODE_ALWAYS_ON

        if last_want_to_mist != self.want_to_mist:
            self.post_event(EVENT_WANT_TO_MIST if self.want_to_mist else EVENT_DONT_WANT_TO_MIST)

    def post_event(self, event, data = None):
        self.event_queue.put((event,data))

    def event_loop(self):
        while True:
            try:
                eventData = self.event_queue.get(timeout=TIMESECS_IDLE_EVENT)
                event = eventData[0]
                data = eventData[1]
                self.handle_event(event, data)
            except Empty:
                self.handle_event(EVENT_IDLE, None)
            self.express_state()

    def popup_text(self, text):
        self.show_text = text
        Timer(TIMESECS_SHOW_MESSAGE, self.post_event, (EVENT_REVERT_TEXT, text)).start()

    def handle_event(self, event, data):
        if event != EVENT_FLASH_LED and event != EVENT_DISPLAY_LINE:
            print(event, data)

        if event == EVENT_IDLE:
            self.validate_state()
            return

        if event == EVENT_DISPLAY_LINE:
            self.showing_line += 1
            if self.showing_line == 4:
                self.showing_line = 1;

            Timer({
                1: TIMESECS_LINE_1,
                2: TIMESECS_LINE_2,
                3: TIMESECS_LINE_3}[self.showing_line], self.post_event, (EVENT_DISPLAY_LINE,)).start()

        if event == EVENT_RESET_DISPLAY:
            lcd_init()
            self.current_text = None
            Timer(TIMESECS_RESET_DISPLAY, self.post_event, (EVENT_RESET_DISPLAY,)).start()

        if event == EVENT_FLASH_LED:
            self.validate_state()
            self.flash_led_on = not self.flash_led_on
            Timer(TIMESECS_LED_FLASH, self.post_event, (EVENT_FLASH_LED,)).start()

        if event == EVENT_BUTTON_DOWN:
            previous_press_counter = self.button_press_counter
            self.button_press_counter = (self.button_press_counter + 1) % len(self.button_presses)
           
            elapsed_secs_since_click = time.time() - data

            if self.button_presses[previous_press_counter]: # not yet decided previous press - this must be a double click
                self.button_presses[previous_press_counter] = None
                self.post_event(EVENT_DOUBLE_CLICK, self.button_press_counter)
            else:
                self.button_presses[self.button_press_counter] = [ True ]
                Timer(TIMESECS_DOUBLE_CLICK - elapsed_secs_since_click, self.post_event, (EVENT_SINGLE_CLICK_TIMEOUT,self.button_press_counter)).start()
                Timer(TIMESECS_LONG_PRESS - elapsed_secs_since_click, self.post_event, (EVENT_LONG_PRESS_TIMEOUT,self.button_press_counter)).start()
            return

        if event == EVENT_BUTTON_UP:
            elapsed_secs_since_click = time.time() - data

            # If the click operation is not yet decided and the click timeout has fired
            if self.button_presses[self.button_press_counter] and not self.button_presses[self.button_press_counter][0]:
                self.button_presses[self.button_press_counter] = None
                self.post_event(EVENT_CLICK)

        if event == EVENT_SINGLE_CLICK_TIMEOUT:
            if self.button_presses[data]:
                if not GPIO.input(GPIO_BUTTON):
                    self.button_presses[data] = None
                    self.post_event(EVENT_CLICK)
                else:
                    self.button_presses[data] = [ False ]  # record the fact that the timeout has passed
            return

        if event == EVENT_LONG_PRESS_TIMEOUT:
            if self.button_presses[data]:
                self.button_presses[data] = None
                self.post_event(EVENT_LONG_PRESS)
            return

        if event == EVENT_SMALL_TANK_FLOAT_ON:
            self.small_tank_float = True
            self.transfer_pump = True
            return

        if event == EVENT_SMALL_TANK_FLOAT_OFF:
            self.small_tank_float = False
            Timer(TIMESECS_TRANSFER_PUMP, self.post_event, (EVENT_TRANSFER_PUMP_OFF,)).start()
            return

        if event == EVENT_TRANSFER_PUMP_OFF and not self.small_tank_float:
            self.transfer_pump = False
            return

        if event == EVENT_LARGE_TANK_BOTTOM_FLOAT_ON:
            self.large_tank_bottom_float = True
            if self.want_to_mist:
                self.misting_pump = True
            return

        if event == EVENT_LARGE_TANK_BOTTOM_FLOAT_OFF:
            self.large_tank_bottom_float = False
            Timer(TIMESECS_MISTING_PUMP, self.post_event, (EVENT_MISTING_PUMP_OFF,)).start()
            return

        if event == EVENT_LARGE_TANK_TOP_FLOAT_ON:
            self.large_tank_top_float = True
            self.venting = True
            self.misting_pump = True
            return

        if event == EVENT_LARGE_TANK_TOP_FLOAT_OFF:
            self.large_tank_top_float = False
            Timer(TIMESECS_VENTING_PUMP, self.post_event, (EVENT_MISTING_PUMP_OFF,)).start()
            return

        if event == EVENT_MISTING_PUMP_OFF:
            self.venting = False
            if not self.large_tank_bottom_float:
                self.misting_pump = False
            else:
                self.misting_pump = self.want_to_mist
            return

        if event == EVENT_WANT_TO_MIST:
            if self.large_tank_bottom_float:
                self.misting_pump = True
            return

        if event == EVENT_DONT_WANT_TO_MIST:
            self.misting_pump = False
            return

        if event == EVENT_LONG_PRESS:
            if self.mode == MODE_ALWAYS_OFF:
                self.mode = MODE_VENTING
                self.popup_text('Mode: Venting')
            else:
                self.mode = MODE_ALWAYS_OFF
                self.popup_text('Mode: Disabled')

        if event == EVENT_CLICK:
            if self.mode == MODE_VENTING:
                self.mode = MODE_ALWAYS_ON
                self.popup_text('Mode: Cooling')
                Timer(TIMESECS_COOLING_TIME, self.post_event, (EVENT_COOLING_STOP,self.cooling_count)).start()
            elif self.mode == MODE_ALWAYS_ON:
                self.post_event(EVENT_COOLING_STOP, self.cooling_count)
            return

        if event == EVENT_COOLING_STOP and self.mode == MODE_ALWAYS_ON and self.cooling_count == data:
            self.post_event(EVENT_MISTING_PUMP_OFF)
            self.mode = MODE_VENTING
            self.cooling_count += 1
            self.popup_text('Mode: Venting')
            return

        if event == EVENT_REVERT_TEXT and self.show_text == data:
            self.show_text = None
            self.showing_line = 1
            return

if __name__ == '__main__':
    try:
        app = StateMachine()
        app.event_loop()
    except KeyboardInterrupt:
        pass
    finally:
        with open(MODE_FILE, 'w') as mode_file:
            mode_file.write(str(app.mode))

        lcd_byte(0x01, LCD_CMD)
        lcd_string("Goodbye!",LCD_LINE_1)
        GPIO.cleanup()
        
