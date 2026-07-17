# *****************************************************************************
# * | File        :	  Pico_CapTouch_ePaper_Test_2in9.py
# * | Author      :   Waveshare team
# * | Function    :   Electronic paper driver
# * | Info        :
# *----------------
# * | This version:   V1.0
# * | Date        :   2020-06-02
# # | Info        :   python demo
# -----------------------------------------------------------------------------
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documnetation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to  whom the Software is
# furished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#

from machine import Pin, SPI, I2C
import framebuf
import utime

# Display resolution
EPD_WIDTH       = 128
EPD_HEIGHT      = 296
  
WF_PARTIAL_2IN9 = [
    0x0,0x40,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x80,0x80,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x40,0x40,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x0,0x80,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x0A,0x0,0x0,0x0,0x0,0x0,0x0,  
    0x1,0x0,0x0,0x0,0x0,0x0,0x0,
    0x1,0x0,0x0,0x0,0x0,0x0,0x0,
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x22,0x22,0x22,0x22,0x22,0x22,0x0,0x0,0x0,
    0x22,0x17,0x41,0xB0,0x32,0x36,
]

WF_PARTIAL_2IN9_Wait = [
0x0,0x40,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,
0x80,0x80,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,
0x40,0x40,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,
0x0,0x80,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,
0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,
0x0A,0x0,0x0,0x0,0x0,0x0,0x2,  
0x1,0x0,0x0,0x0,0x0,0x0,0x0,
0x1,0x0,0x0,0x0,0x0,0x0,0x0,
0x0,0x0,0x0,0x0,0x0,0x0,0x0,
0x0,0x0,0x0,0x0,0x0,0x0,0x0,
0x0,0x0,0x0,0x0,0x0,0x0,0x0,
0x0,0x0,0x0,0x0,0x0,0x0,0x0,
0x0,0x0,0x0,0x0,0x0,0x0,0x0,
0x0,0x0,0x0,0x0,0x0,0x0,0x0,
0x0,0x0,0x0,0x0,0x0,0x0,0x0,
0x0,0x0,0x0,0x0,0x0,0x0,0x0,
0x0,0x0,0x0,0x0,0x0,0x0,0x0,
0x22,0x22,0x22,0x22,0x22,0x22,0x0,0x0,0x0,
0x22,0x17,0x41,0xB0,0x32,0x36,
]

WS_20_30 = [					
0x80,0x66,0x0,0x0,0x0,0x0,0x0,0x0,0x40,0x0,0x0,0x0,
0x10,0x66,0x0,0x0,0x0,0x0,0x0,0x0,0x20,0x0,0x0,0x0,
0x80,0x66,0x0,0x0,0x0,0x0,0x0,0x0,0x40,0x0,0x0,0x0,
0x10,0x66,0x0,0x0,0x0,0x0,0x0,0x0,0x20,0x0,0x0,0x0,
0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,
0x14,0x8,0x0,0x0,0x0,0x0,0x2,
0xA,0xA,0x0,0xA,0xA,0x0,0x1,
0x0,0x0,0x0,0x0,0x0,0x0,0x0,
0x0,0x0,0x0,0x0,0x0,0x0,0x0,
0x0,0x0,0x0,0x0,0x0,0x0,0x0,
0x0,0x0,0x0,0x0,0x0,0x0,0x0,
0x0,0x0,0x0,0x0,0x0,0x0,0x0,
0x0,0x0,0x0,0x0,0x0,0x0,0x0,
0x14,0x8,0x0,0x1,0x0,0x0,0x1,
0x0,0x0,0x0,0x0,0x0,0x0,0x1,
0x0,0x0,0x0,0x0,0x0,0x0,0x0,
0x0,0x0,0x0,0x0,0x0,0x0,0x0,
0x44,0x44,0x44,0x44,0x44,0x44,0x0,0x0,0x0,
0x22,0x17,0x41,0x0,0x32,0x36
]

Gray4 = [						
0x00,0x60,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,
0x20,0x60,0x10,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,
0x28,0x60,0x14,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,
0x2A,0x60,0x15,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,
0x00,0x90,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,
0x00,0x02,0x00,0x05,0x14,0x00,0x00,
0x1E,0x1E,0x00,0x00,0x00,0x00,0x01,
0x00,0x02,0x00,0x05,0x14,0x00,0x00,
0x00,0x00,0x00,0x00,0x00,0x00,0x00,
0x00,0x00,0x00,0x00,0x00,0x00,0x00,
0x00,0x00,0x00,0x00,0x00,0x00,0x00,
0x00,0x00,0x00,0x00,0x00,0x00,0x00,
0x00,0x00,0x00,0x00,0x00,0x00,0x00,
0x00,0x00,0x00,0x00,0x00,0x00,0x00,
0x00,0x00,0x00,0x00,0x00,0x00,0x00,
0x00,0x00,0x00,0x00,0x00,0x00,0x00,
0x00,0x00,0x00,0x00,0x00,0x00,0x00,
0x24,0x22,0x22,0x22,0x23,0x32,0x00,0x00,0x00,
0x22,0x17,0x41,0xAE,0x32,0x28		
]	

# e-Paper
RST_PIN         = 12
DC_PIN          = 8
CS_PIN          = 9
BUSY_PIN        = 13

# TP
TRST    = 16
INT     = 17

# key
KEY0 = 2
KEY1 = 3
KEY2 = 15

class config():
    def __init__(self, i2c_addr):
        self.reset_pin = Pin(RST_PIN, Pin.OUT)
        self.busy_pin = Pin(BUSY_PIN, Pin.IN)
        self.cs_pin = Pin(CS_PIN, Pin.OUT)

        self.trst_pin = Pin(TRST, Pin.OUT)
        self.int_pin = Pin(INT, Pin.IN)

        self.key0 = Pin(KEY0, Pin.IN, Pin.PULL_UP)
        self.key1 = Pin(KEY1, Pin.IN, Pin.PULL_UP)
        self.key2 = Pin(KEY2, Pin.IN, Pin.PULL_UP)
        
        self.spi = SPI(1)
        self.spi.init(baudrate=4000_000)
        self.dc_pin = Pin(DC_PIN, Pin.OUT)

        self.address = i2c_addr
        self.i2c = I2C(1, scl=Pin(7), sda=Pin(6), freq=100_000)

    def digital_write(self, pin, value):
        pin.value(value)

    def digital_read(self, pin):
        return pin.value()

    def delay_ms(self, delaytime):
        utime.sleep(delaytime / 1000.0)

    def spi_writebyte(self, data):
        self.spi.write(bytearray(data))

    def i2c_writebyte(self, reg, value):
        wbuf = [(reg>>8)&0xff, reg&0xff, value]
        self.i2c.writeto(self.address, bytearray(wbuf))

    def i2c_write(self, reg):
        wbuf = [(reg>>8)&0xff, reg&0xff]
        self.i2c.writeto(self.address, bytearray(wbuf))

    def i2c_readbyte(self, reg, len):
        self.i2c_write(reg)
        rbuf = bytearray(len)
        self.i2c.readfrom_into(self.address, rbuf)
        return rbuf

    def module_exit(self):
        self.digital_write(self.reset_pin, 0)
        self.digital_write(self.trst_pin, 0)


class EPD_2in9:
    def __init__(self):
        self.config = config(0x48)

        self.width = EPD_WIDTH
        self.height = EPD_HEIGHT

        self.black = 0x00
        self.white = 0xff
        self.darkgray = 0xaa
        self.grayish = 0x55
        
        self.lut = WF_PARTIAL_2IN9
        self.lut_l = WF_PARTIAL_2IN9_Wait

        self.buffer_4Gray = None
        self.image4Gray = None
        self.buffer = None
        self.image1Gray_Portrait = None
        

    # Hardware reset
    def reset(self):
        self.config.digital_write(self.config.reset_pin, 1)
        self.config.delay_ms(50) 
        self.config.digital_write(self.config.reset_pin, 0)
        self.config.delay_ms(2)
        self.config.digital_write(self.config.reset_pin, 1)
        self.config.delay_ms(50)   

    def send_command(self, command):
        self.config.digital_write(self.config.dc_pin, 0)
        self.config.digital_write(self.config.cs_pin, 0)
        self.config.spi_writebyte([command])
        self.config.digital_write(self.config.cs_pin, 1)

    def send_data(self, data):
        self.config.digital_write(self.config.dc_pin, 1)
        self.config.digital_write(self.config.cs_pin, 0)
        self.config.spi_writebyte([data])
        self.config.digital_write(self.config.cs_pin, 1)

    def send_data_buffer(self, data):
        """Send an existing bytes-like buffer without per-byte allocations."""
        self.config.digital_write(self.config.dc_pin, 1)
        self.config.digital_write(self.config.cs_pin, 0)
        self.config.spi.write(data)
        self.config.digital_write(self.config.cs_pin, 1)
        
    def ReadBusy(self):
        # print("e-Paper busy")
        while(self.config.digital_read(self.config.busy_pin) == 1):      #  0: idle, 1: busy
            self.config.delay_ms(10) 
        # print("e-Paper busy release")  

    def TurnOnDisplay(self):
        self.send_command(0x22) # DISPLAY_UPDATE_CONTROL_2
        self.send_data(0xF7)
        self.send_command(0x20) # MASTER_ACTIVATION
        self.ReadBusy()

    def TurnOnDisplay_Partial(self):
        self.send_command(0x22) # DISPLAY_UPDATE_CONTROL_2
        self.send_data(0x0F)
        self.send_command(0x20) # MASTER_ACTIVATION
        self.ReadBusy()

    def TurnOnDisplay_4Gray(self):
        self.send_command(0x22) # DISPLAY_UPDATE_CONTROL_2
        self.send_data(0xC7)
        self.send_command(0x20) # MASTER_ACTIVATION
        self.ReadBusy()

    def delay_ms(self, delaytime):
        utime.sleep(delaytime / 1000.0)

    def SendLut(self, isQuick):
        self.send_command(0x32)
        if(isQuick):
            lut = self.lut    
        else:
            lut = self.lut_l

        for i in range(0, 153):
            self.send_data(lut[i])
        self.ReadBusy()

    def SetWindow(self, x_start, y_start, x_end, y_end):
        self.send_command(0x44) # SET_RAM_X_ADDRESS_START_END_POSITION
        # x point must be the multiple of 8 or the last 3 bits will be ignored
        self.send_data((x_start>>3) & 0xFF)
        self.send_data((x_end>>3) & 0xFF)
        self.send_command(0x45) # SET_RAM_Y_ADDRESS_START_END_END_POSITION
        self.send_data(y_start & 0xFF)
        self.send_data((y_start >> 8) & 0xFF)
        self.send_data(y_end & 0xFF)
        self.send_data((y_end >> 8) & 0xFF)

    def SetCursor(self, x, y):
        self.send_command(0x4E) # SET_RAM_X_ADDRESS_COUNTER
        # x point must be the multiple of 8 or the last 3 bits will be ignored
        self.send_data((x>>3) & 0xFF)
        
        self.send_command(0x4F) # SET_RAM_Y_ADDRESS_COUNTER
        self.send_data(y & 0xFF)
        self.send_data((y >> 8) & 0xFF)
        self.ReadBusy()

    def SetLut(self, lut):
        self.send_command(0x32)
        for i in range(0, 153):
            self.send_data(lut[i])
        self.ReadBusy()
        self.send_command(0x3f)
        self.send_data(lut[153])
        self.send_command(0x03);	# gate voltage
        self.send_data(lut[154])
        self.send_command(0x04);	# source voltage
        self.send_data(lut[155])	# VSH
        self.send_data(lut[156])	# VSH2
        self.send_data(lut[157])	# VSL
        self.send_command(0x2c);		# VCOM
        self.send_data(lut[158])

    def init(self):
        # EPD hardware init start     
        self.reset()

        self.ReadBusy()   
        self.send_command(0x12)  #SWRESET
        self.ReadBusy()   

        self.send_command(0x01) #Driver output control      
        self.send_data(0x27)
        self.send_data(0x01)
        self.send_data(0x00)
    
        self.send_command(0x11) #data entry mode       
        self.send_data(0x03)

        self.SetWindow(0, 0, self.width-1, self.height-1)

        self.send_command(0x21) #  Display update control
        self.send_data(0x00)
        self.send_data(0x80)	
    
        self.SetCursor(0, 0)
        self.ReadBusy()
        # EPD hardware init end
        return 0
    
    def init_4Gray(self):
        self.reset()

        self.ReadBusy()
        self.send_command(0x12)  #SWRESET
        self.ReadBusy() 

        self.send_command(0x01) #Driver output control      
        self.send_data(0x27)
        self.send_data(0x01)
        self.send_data(0x00)
    
        self.send_command(0x11) #data entry mode       
        self.send_data(0x03)
        
        self.SetWindow(8, 0, self.width, self.height-1)

        self.send_command(0x3C)
        self.send_data(0x04)
    
        self.SetCursor(8, 0)
        self.ReadBusy()

        self.SetLut(Gray4)
        # EPD hardware init end
        return 0

    def display(self, image):
        if (image == None):
            return            
        self.send_command(0x24) # WRITE_RAM
        self.send_data_buffer(image)
        self.TurnOnDisplay()

    def display_Base(self, image):
        if (image == None):
            return   
        self.send_command(0x24) # WRITE_RAM
        self.send_data_buffer(image)
        self.send_command(0x26) # WRITE_RAM
        self.send_data_buffer(image)
        self.TurnOnDisplay()
        
    def display_Partial(self, image):
        if (image == None):
            return
            
        self.config.digital_write(self.config.reset_pin, 0)
        self.config.delay_ms(0.2)
        self.config.digital_write(self.config.reset_pin, 1) 
        
        self.SendLut(1)
        self.send_command(0x37)
        self.send_data(0x00)
        self.send_data(0x00)  
        self.send_data(0x00)  
        self.send_data(0x00) 
        self.send_data(0x00)  	
        self.send_data(0x40)  
        self.send_data(0x00)  
        self.send_data(0x00)   
        self.send_data(0x00)  
        self.send_data(0x00)

        self.send_command(0x3C) #BorderWavefrom
        self.send_data(0x80)

        self.send_command(0x22) 
        self.send_data(0xC0)   
        self.send_command(0x20) 
        self.ReadBusy()

        self.SetWindow(0, 0, self.width - 1, self.height - 1)
        self.SetCursor(0, 0)
        
        self.send_command(0x24) # WRITE_RAM
        self.send_data_buffer(image)
        self.TurnOnDisplay_Partial()


    def display_4Gray(self, image):
        self.send_command(0x24)
        for i in range(0, 4736):
            temp3=0
            for j in range(0, 2):
                temp1 = image[i*2+j]
                for k in range(0, 2):
                    temp2 = temp1&0x03 
                    if(temp2 == 0x03):
                        temp3 |= 0x00   # white
                    elif(temp2 == 0x00):
                        temp3 |= 0x01   # black
                    elif(temp2 == 0x02):
                        temp3 |= 0x00   # gray1
                    else:   # 0x01
                        temp3 |= 0x01   # gray2
                    temp3 <<= 1

                    temp1 >>= 2
                    temp2 = temp1&0x03 
                    if(temp2 == 0x03):   # white
                        temp3 |= 0x00
                    elif(temp2 == 0x00):   # black
                        temp3 |= 0x01
                    elif(temp2 == 0x02):
                        temp3 |= 0x00   # gray1
                    else:   # 0x01
                        temp3 |= 0x01   # gray2
                    
                    if (( j!=1 ) | ( k!=1 )):
                        temp3 <<= 1
                    temp1 >>= 2
            self.send_data(temp3)
            
        self.send_command(0x26)	       
        for i in range(0, 4736):
            temp3=0
            for j in range(0, 2):
                temp1 = image[i*2+j]
                for k in range(0, 2):
                    temp2 = temp1&0x03 
                    if(temp2 == 0x03):
                        temp3 |= 0x00   # white
                    elif(temp2 == 0x00):
                        temp3 |= 0x01   # black
                    elif(temp2 == 0x02):
                        temp3 |= 0x01   # gray1
                    else:   # 0x01
                        temp3 |= 0x00   # gray2
                    temp3 <<= 1

                    temp1 >>= 2
                    temp2 = temp1&0x03
                    if(temp2 == 0x03):   # white
                        temp3 |= 0x00
                    elif(temp2 == 0x00):   # black
                        temp3 |= 0x01
                    elif(temp2 == 0x02):
                        temp3 |= 0x01   # gray1
                    else:   # 0x01
                        temp3 |= 0x00   # gray2  
                    if(j!=1 or k!=1):                    
                        temp3 <<= 1
                    temp1 >>= 2
            self.send_data(temp3)

        self.TurnOnDisplay_4Gray()

    def Clear(self, color):
        self.send_command(0x24) # WRITE_RAM
        for i in range(0, self.height * int(self.width/8)):
            self.send_data(color)
        self.TurnOnDisplay()

    def sleep(self):
        self.send_command(0x10) # DEEP_SLEEP_MODE
        self.send_data(0x01)
        
        self.config.delay_ms(2000)
        self.config.module_exit()


class ICNT_Development():
    def __init__(self):
        self.Touch = 0
        self.TouchGestureid = 0
        self.TouchCount = 0
        
        self.TouchEvenid = [0, 1, 2, 3, 4]
        self.X = [0, 1, 2, 3, 4]
        self.Y = [0, 1, 2, 3, 4]
        self.P = [0, 1, 2, 3, 4]
    

# …（前面的程式碼保持不變）…

class ICNT86():
    def __init__(self):
        self.config = config(0x48)
    
    def ICNT_Reset(self):
        self.config.digital_write(self.config.trst_pin, 1)
        self.config.delay_ms(100)
        self.config.digital_write(self.config.trst_pin, 0)
        self.config.delay_ms(100)
        self.config.digital_write(self.config.trst_pin, 1)
        self.config.delay_ms(100)

    def ICNT_Write(self, Reg, Data):
        self.config.i2c_writebyte(Reg, Data)

    def ICNT_Read(self, Reg, len):
        return self.config.i2c_readbyte(Reg, len)
        
    def ICNT_ReadVersion(self):
        buf = self.ICNT_Read(0x000a, 4)
        print(buf)

    def ICNT_Init(self):
        self.ICNT_Reset()
        self.ICNT_ReadVersion()

    def ICNT_Scan(self, ICNT_Dev, ICNT_Old):
        buf = []
        mask = 0x00
        
        if(ICNT_Dev.Touch == 1):
            ICNT_Dev.Touch = 0
            buf = self.ICNT_Read(0x1001, 1)
            
            if(buf[0] == 0x00):
                self.ICNT_Write(0x1001, mask)
                self.config.delay_ms(1)
                return
            else:
                ICNT_Dev.TouchCount = buf[0]
                
                if(ICNT_Dev.TouchCount > 5 or ICNT_Dev.TouchCount < 1):
                    self.ICNT_Write(0x1001, mask)
                    ICNT_Dev.TouchCount = 0
                    return
                    
                buf = self.ICNT_Read(0x1002, ICNT_Dev.TouchCount*7)
                self.ICNT_Write(0x1001, mask)
                                
                ICNT_Old.X[0] = ICNT_Dev.X[0]
                ICNT_Old.Y[0] = ICNT_Dev.Y[0]
                ICNT_Old.P[0] = ICNT_Dev.P[0]
                
                for i in range(0, ICNT_Dev.TouchCount, 1):
                    ICNT_Dev.TouchEvenid[i] = buf[6 + 7*i] 
                    ICNT_Dev.X[i] = 127 - ((buf[4 + 7*i] << 8) + buf[3 + 7*i])
                    ICNT_Dev.Y[i] = ((buf[2 + 7*i] << 8) + buf[1 + 7*i])
                    ICNT_Dev.P[i] = buf[5 + 7*i]
                # print(ICNT_Dev.Y[0], ICNT_Dev.X[0], ICNT_Dev.P[0])
                return(296 - ICNT_Dev.Y[0], ICNT_Dev.X[0])
        return
    
def get_touch_coordinates(tp, icnt_dev, icnt_old):
    """
    檢查觸控中斷並執行觸控掃描，回傳第一個觸碰點的 (x, y) 座標
    若未偵測到觸碰則回傳 None
    """
    # 檢查中斷腳位：低電位表示有觸控
    if tp.config.digital_read(tp.config.int_pin) == 0:
        icnt_dev.Touch = 1
    else:
        icnt_dev.Touch = 0

    # 呼叫原有的觸控掃描函式
    data = tp.ICNT_Scan(icnt_dev, icnt_old)

    # 若偵測到觸控點則回傳第一個觸控點的座標
    if data:
        # print(data)
        return data
    else:
        return None

prev_touch = None
def get_touch_state(tp, icnt_dev, icnt_old):
    """
    偵測觸控向量，回傳 (delta_x, delta_y)。
    每次呼叫會比較前一次觸控點與目前的觸控點，若未偵測到觸碰則回傳 None。
    首次偵測時回傳 (0, 0)。
    """
    global prev_touch
    new_touch = (get_touch_coordinates(tp, icnt_dev, icnt_old), utime.ticks_ms())
    
    if new_touch[0] is None :
        return None
        
    if prev_touch is None:
        prev_touch = new_touch
        return ("Touch", new_touch[0])
    
    # 計算滑動向量
    state = "Drag"
    result = [new_touch[0][0] - prev_touch[0][0], new_touch[0][1] - prev_touch[0][1]]
        
    if abs(result[0]) < 5:
        result[0] = 0
    if abs(result[1]) < 5:
        result[1] = 0
        
    if abs(result[0]) + abs(result[1]) == 0 or new_touch[1] - prev_touch[1] > 200:
        state = "Touch"
        result = new_touch[0]

    # 更新前一次觸控點
    prev_touch = new_touch
        
    return (state, result)


# 將原本的示範/測試程式碼包裝於 __main__ 區塊中
if __name__ == "__main__":
    # 初始化觸控相關物件
    tp = ICNT86()
    icnt_dev = ICNT_Development()
    icnt_old = ICNT_Development()
    
    last_time = -1
    
    # 執行觸控模組初始化（根據原有程式碼）
    tp.ICNT_Init()
    
    while True:
        # 使用範例：
        state = get_touch_state(tp, icnt_dev, icnt_old)
        
        if state is not None:
            print("觸控狀態：", state)
