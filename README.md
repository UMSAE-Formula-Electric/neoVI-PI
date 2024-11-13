# Logger Board
The Logger Board will monitor our CAN bus for faults, errors, sensor data etc. The goal of the board is to capture messages on our car, log them to an SD card, and transmit data wirelessly to a laptop app!

# How to set up ESP32 and SD card adapter using Arduino:
Download the zip file of the the micro-sd card library:
https://github.com/nhatuan84/esp32-micro-sdcard

Unzip the contents and add it into the libraries folder in your directory via... (for Windows)

Users/yourName/AppData/Local/Arduino15/libraries

NOTE: The AppData folder may be hidden, go to (View -> Show -> Hidden Items) to view the folder

The micro-sd card library uses mySD.c instead of SD.c (SD.c causes problems with mounting the SD card) 

Configure arduino to use the ESP32 Dev Module board and the correct COM port for your device.

# Tutorials
This branch includes two tutorials will work if the logger is set up correcty.

