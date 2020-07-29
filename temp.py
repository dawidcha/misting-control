import board
import busio
import adafruit_mcp9808
import time

i2c = busio.I2C(board.SCL, board.SDA)
mcp = adafruit_mcp9808.MCP9808(i2c)

def current_temperature():
    return mcp.temperature

def main():
    while True:
        print('Temperature: %0.1f\'C' % current_temperature())
        time.sleep(1)
        

if __name__ == '__main__':

  try:
    main()
  except KeyboardInterrupt:
    pass
