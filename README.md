# Logger-Board

## Logger Board

The Logger Board will monitor our CAN
bus for faults, errors, sensor data etc.
The goal of the board is to capture messages
on our car, log them to an SD card, and transmit
data wirelessly to a laptop app!

## Introduction

The logger board is a project for the external
communication section of UMSAE formula electric
to add logging capabilities to the vehicle built
by the team each year. This will be our low
cost and fast solution to this problem and will
allow for more efficent debugging of the car.

*This project was completed in windows 10 other operating systems may need extra setup*

## ESP32 CAN bus data logger
 - ESP32 Wroom 32D
 - CAN transceiver (SN65HVD232)
 - SD card

## Installation



## Post-Installation

To get the Arduino libraries to work for the esp32 we need to add some
libraries for CAN and SD card functionality. Since some of these libraries are out 
of date we need to change some of the drivers for these to the new versions.

Updating the CAN library:
1. Install Arduino library *CAN* in the library manager

2. Go to the install location likely at: 
    - /Arduino/libraries/CAN/src/ESP32SJA1000.cpp
3. add include for drivers
    - "esp32/rom/gpio.h"
4. change to new driver for esp32 
    - "esp_intr_alloc.h"

Downloading the SD card library:
1. download zip for the [micro-sd card library](https://github.com/nhatuan84/esp32-micro-sdcard)

2. unzip contents into the libraries folder in the directory:
    - Users/yourName/AppData/local/Arduino15/libraries
    
3. To test that its working change the include of the SD examples built into Arduino IDE from
SD.h to mySD.h. This should fix mounting issues with the SD card. 
