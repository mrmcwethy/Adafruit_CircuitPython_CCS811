# The MIT License (MIT)
#
# Copyright (c) 2017 Dean Miller for Adafruit Industries.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

"""
`CCS811` - CCS811 air quality sensor
====================================================
This library supports the use of the CCS811 air quality sensor in CircuitPython.

Author(s): Dean Miller for Adafruit Industries

**Notes:**

#. `Datasheet <https://cdn-learn.adafruit.com/assets/assets/000/044/636/original/CCS811_DS000459_2-00-1098798.pdf?1501602769>`_
"""
from micropython import const
from adafruit_bus_device.i2c_device import I2CDevice
from adafruit_register import i2c_bit
from adafruit_register import i2c_bits
import time
import math

CCS811_ALG_RESULT_DATA = const(0x02)
CCS811_RAW_DATA = const(0x03)
CCS811_ENV_DATA = const(0x05)
CCS811_NTC = const(0x06)
CCS811_THRESHOLDS = const(0x10)

# CCS811_BASELINE = 0x11
# CCS811_HW_ID = 0x20
# CCS811_HW_VERSION = 0x21
# CCS811_FW_BOOT_VERSION = 0x23
# CCS811_FW_APP_VERSION = 0x24
# CCS811_ERROR_ID = 0xE0

CCS811_SW_RESET = const(0xFF)

# CCS811_BOOTLOADER_APP_ERASE = 0xF1
# CCS811_BOOTLOADER_APP_DATA = 0xF2
# CCS811_BOOTLOADER_APP_VERIFY = 0xF3
# CCS811_BOOTLOADER_APP_START = 0xF4

CCS811_DRIVE_MODE_IDLE = const(0x00)
CCS811_DRIVE_MODE_1SEC = const(0x01)
CCS811_DRIVE_MODE_10SEC = const(0x02)
CCS811_DRIVE_MODE_60SEC = const(0x03)
CCS811_DRIVE_MODE_250MS = const(0x04)

CCS811_HW_ID_CODE = const(0x81)
CCS811_REF_RESISTOR = const(100000)

class CCS811:
	"""CCS811 gas sensor driver.

	:param ~busio.I2C i2c: The I2C bus.
	:param int addr: The I2C address of the CCS811.
	"""
	#set up the registers
	error = i2c_bit.ROBit(0x00, 0)
	"""True when an error has occured."""
	data_ready = i2c_bit.ROBit(0x00, 3)
	"""True when new data has been read."""
	app_valid = i2c_bit.ROBit(0x00, 4)
	fw_mode = i2c_bit.ROBit(0x00, 7)

	hw_id = i2c_bits.ROBits(8, 0x20, 0)

	int_thresh = i2c_bit.RWBit(0x01, 2)
	interrupt_enabled = i2c_bit.RWBit(0x01, 3)
	drive_mode = i2c_bits.RWBits(3, 0x01, 4)

	temp_offset = 0.0
	"""Temperature offset."""

	def __init__(self, i2c, addr=0x5A):
		self.i2c_device = I2CDevice(i2c, addr)

		#check that the HW id is correct
		if self.hw_id != CCS811_HW_ID_CODE:
			raise RuntimeError("Device ID returned is not correct! Please check your wiring.")

		#try to start the app
		buf = bytearray(1)
		buf[0] = 0xF4
		with self.i2c_device as i2c:
			i2c.write(buf, end=1, stop=True)
		time.sleep(.1)

		#make sure there are no errors and we have entered application mode
		if self.error:
			raise RuntimeError("Device returned a error! Try removing and reapplying power to the device and running the code again.")
		if not self.fw_mode:
			raise RuntimeError("Device did not enter application mode! If you got here, there may be a problem with the firmware on your sensor.")

		self.interrupt_enabled = False

		#default to read every second
		self.drive_mode = CCS811_DRIVE_MODE_1SEC

		self._eCO2 = None
		self._TVOC = None

	@property
	def error_code(self):
		"""Error code"""
		buf = bytearray(2)
		buf[0] = 0xE0
		with self.i2c_device as i2c:
			i2c.write(buf, end=1, stop=False)
			i2c.read_into(buf, start=1)
		return buf[1]

	def _update_data(self):
		if self.data_ready:
			buf = bytearray(9)
			buf[0] = CCS811_ALG_RESULT_DATA
			with self.i2c_device as i2c:
				i2c.write(buf, end=1, stop=False)
				i2c.read_into(buf, start=1)

			self._eCO2 = (buf[1] << 8) | (buf[2])
			self._TVOC = (buf[3] << 8) | (buf[4])

			if self.error:
				raise RuntimeError("Error:" + str(self.error_code))

	@property
	def TVOC(self):
		"""Total Volatile Organic Compound in parts per billion."""
		self._update_data()
		return self._TVOC

	@property
	def eCO2(self):
		"""Equivalent Carbon Dioxide in parts per million. Clipped to 400 to 8192ppm."""
		return self._eCO2

	@property
	def temperature(self):
		"""Temperature based on optional thermistor in Celsius."""
		buf = bytearray(5)
		buf[0] = CCS811_NTC
		with self.i2c_device as i2c:
			i2c.write(buf, end=1, stop=False)
			i2c.read_into(buf, start=1)

		vref = (buf[1] << 8) | buf[2]
		vntc = (buf[3] << 8) | buf[4]

		# From ams ccs811 app note 000925
		# https://download.ams.com/content/download/9059/13027/version/1/file/CCS811_Doc_cAppNote-Connecting-NTC-Thermistor_AN000372_v1..pdf
		rntc = float(vntc) * CCS811_REF_RESISTOR / float(vref)

		ntc_temp = math.log(rntc / 10000.0)
		ntc_temp /= 3380.0
		ntc_temp += 1.0 / (25 + 273.15)
		ntc_temp = 1.0 / ntc_temp
		ntc_temp -= 273.15
		return ntc_temp - self.temp_offset

	def set_environmental_data(self, humidity, temperature):
		"""Set the temperature and humidity used when computing eCO2 and TVOC values.

		:param int humidity: The current relative humidity in percent.
		:param float temperature: The current temperature in Celsius."""
		# Humidity is stored as an unsigned 16 bits in 1/512%RH. The default
		# value is 50% = 0x64, 0x00. As an example 48.5% humidity would be 0x61,
		# 0x00.
		hum_perc = int(humidity) << 1

		# Temperature is stored as an unsigned 16 bits integer in 1/512 degrees
		# there is an offset: 0 maps to -25C. The default value is 25C = 0x64,
		# 0x00. As an example 23.5% temperature would be 0x61, 0x00.
		parts = math.fmod(temperature)
		fractional = parts[0]
		temperature = parts[1]

		temp_high = ((temperature + 25) << 9)
		temp_low = ((fractional / 0.001953125) & 0x1FF)

		temp_conv = (temp_high | temp_low)

		buf = bytearray([CCS811_ENV_DATA, hum_perc, 0x00,((temp_conv >> 8) & 0xFF), (temp_conv & 0xFF)])

		with self.i2c_device as i2c:
			i2c.write(buf)

	def set_interrupt_thresholds(self, low_med, med_high, hysteresis):
		"""Set the thresholds used for triggering the interrupt based on eCO2.
		The interrupt is triggered when the value crossed a boundary value by the
		minimum hysteresis value.

		:param int low_med: Boundary between low and medium ranges
		:param int med_high: Boundary between medium and high ranges
		:param int hysteresis: Minimum difference between reads"""
		buf = bytearray([CCS811_THRESHOLDS, ((low_med >> 8) & 0xF), (low_med & 0xF), ((med_high >> 8) & 0xF), (med_high & 0xF), hysteresis ])
		with self.i2c_device as i2c:
			self.i2c_device.write(buf)

	def reset(self):
		"""Initiate a software reset."""
		#reset sequence from the datasheet
		seq = bytearray([CCS811_SW_RESET, 0x11, 0xE5, 0x72, 0x8A])
		with self.i2c_device as i2c:
			self.i2c_device.write(seq)
