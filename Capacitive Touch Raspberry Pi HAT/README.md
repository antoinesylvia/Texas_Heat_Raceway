Bought a MPR121 Pi HAT from Adafruit back in March (https://www.adafruit.com/product/2340), wanted to investigate adding touch capabilities to our setup. 

![Capacitive Touch Raspberry Pi HAT Setup](https://github.com/antoinesylvia/dallas_diecast_labs/blob/9aea386b805420d2079cbb15c74320622cde7e7a/Capacitive%20Touch%20Raspberry%20Pi%20HAT/setup.png)


Before use, you must solder the header pins to the Pi HAT. Once complete you can attach alligator clip test leads to the board as shown on the product page an the other side to an electric conductive item like copper tape.


Run one of these options on the Pi with Python3 installed:

----------------------------------------------------------------
Option 1 - Virtual environment (must repeat/activate environment on boot after 1st run):

    sudo apt install python3-venv
    cd ~/Desktop/hot
    python3 -m venv venv
    source venv/bin/activate
    pip3 install adafruit-blinka adafruit-circuitpython-mpr121
    
    python CapacitiveTouchHAT_MPR121.py

----------------------------------------------------------------
Option 2 - No virtual environment: 

    sudo apt-get update
    sudo apt-get install -y python3-pip python3-dev python3-smbus i2c-tools
    pip3 install --user --break-system-packages -r requirements.txt

    python CapacitiveTouchHAT_MPR121.py

----------------------------------------------------------------
If not using a requirements file then use:

    pip3 install --user --break-system-packages adafruit-blinka adafruit-circuitpython-mpr121 adafruit-circuitpython-busdevice

    python CapacitiveTouchHAT_MPR121.py

---------------------------------------------------------------
Or 1 liner:

    sudo apt-get update && sudo apt-get install -y python3-pip python3-dev python3-venv python3-smbus i2c-tools && pip3 install --user --break-system-packages adafruit-blinka adafruit-circuitpython-mpr121 adafruit-circuitpython-busdevice
    
    python CapacitiveTouchHAT_MPR121.py

----------------------------------------------------------------
Note:

If a SCL error pops up its due to the wrong board library being installed ("module 'board' has no attribute 'SCL'"), use:
    
    pip3 uninstall board --break-system-packages
    pip3 install --user --break-system-packages adafruit-blinka

---------------------------------------------------------------

Once everything is running, simply touch your electrical conductive item and it should register like this:

![Capacitive Touch Raspberry Pi HAT Setup CLI](https://github.com/antoinesylvia/dallas_diecast_labs/blob/9aea386b805420d2079cbb15c74320622cde7e7a/Capacitive%20Touch%20Raspberry%20Pi%20HAT/CLI.png))
