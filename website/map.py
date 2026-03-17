import time
import math
from pymavlink import mavutil
import matplotlib.pyplot as plt
import time
import tkinter as tk
from tkinter import simpledialog
import requests

PIXHAWK_CONNECTION_PORT = "/dev/ttyACM2"
PIXHAWK_BAUDRATE = 115200
PIXHAWK = None
PIXHAWK_stream_id = mavutil.mavlink.MAV_DATA_STREAM_ALL
PIXHAWK_rate_hz = 10

#Map config
plt.ion()
fig, ax = plt.subplots(figsize=(8,8))
ax.set_xlim(-10,10) # longitude
ax.set_ylim(-10,10) # latitude
ax.set_title("Rover navigation path")
ax.set_xlabel("Longitude")
ax.set_ylabel("Latitude")

#helper functions
def get_destination_coordinates():
    root = tk.Tk()
    root.withdraw()

    lat = simpledialog.askfloat("Input", "Enter the destination latitude:")
    lon = simpledialog.askfloat("Input", "Enter the destination longitude:")

    root.destroy()
    return lon, lat



try:
    print(f"Connecting to Pixhawk on {PIXHAWK_CONNECTION_PORT}...")
    PIXHAWK = mavutil.mavlink_connection(PIXHAWK_CONNECTION_PORT, baud=PIXHAWK_BAUDRATE)
    PIXHAWK.wait_heartbeat()
    print("Pixhawk connected! Heartbeat received.")
    PIXHAWK.mav.request_data_stream_send(
            PIXHAWK.target_system,
            PIXHAWK.target_component,
            PIXHAWK_stream_id,
            PIXHAWK_rate_hz,
            1
    )
    print(f"Requested data stream {PIXHAWK_stream_id} at {PIXHAWK_rate_hz} Hz.")
except Exception as e:
    print(f"Failed to connect to Pixhawk: {e}")


def read_gps():
    try:
        print("Reading GPS Values")

        while True:
            gps_raw_int_msg = PIXHAWK.recv_match(type='GPS_RAW_INT', blocking=True, timeout=0.1)
            gps_raw_int = None

            if gps_raw_int_msg:
                data = gps_raw_int_msg.to_dict()
                lat = data['lat'] / 1e7
                lon = data['lon'] / 1e7
                alt = data['alt'] / 1e3
                gps_raw_int = [lat, lon, alt]
                #print("read gps!!!")
                return lon, lat
    except Exception as e:
        print("Error happened while reading GPS values")


# Data
rover_path = []
destination = get_destination_coordinates()

#plot destination
if destination:
    ax.plot(destination[0], destination[1], 'ro', label='Destination')
    ax.legend()

increment = 0.1

while True:

    #simulated GPS data
    current_location = read_gps() 
    rover_path.append(current_location)

    #update plot
    if current_location:
        lons, lats = zip(*rover_path)
        ax.plot(lons, lats, '-b', label="Path" if len(rover_path) == 1 else "")
    else:
        print("Corrupted GPS value from the endpoint")

    plt.pause(0.1)
    time.sleep(0.5)

    increment += 0.1

plt.ioff()
plt.show()

