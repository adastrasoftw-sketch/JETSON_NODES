from flask import render_template, Response, Flask, request, jsonify, send_file    
import random
import cv2
import numpy as np
import pyrealsense2 as rs  # Replaced ZED with RealSense
import time
import math
from pymavlink import mavutil
import matplotlib.pyplot as plt 
import shutil
import os
import json
import io
from PIL import Image
from io import BytesIO
import threading
import serial 

# --- CONFIGURATION ---
SERIAL_PORT = "/dev/ttyACM8"
SERIAL_BAUD = 9600
PIXHAWK_CONNECTION_PORT = "/dev/ttyACM5"
PIXHAWK_BAUDRATE = 115200

app = Flask(__name__)

## --- REALSENSE INITIALIZATION ---
pipeline = rs.pipeline()
config = rs.config()

# Enable ONLY the color stream for RGB video
config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)

# Start the pipeline with the updated config
try:
    pipeline.start(config)
    print("RealSense RGB mode initialized.")
except Exception as e:
    print(f"Startup Error: {e}")

# --- INSTA360 INITIALIZATION ---
# Using the permanent symlink created by your udev rule
cap2 = cv2.VideoCapture("/dev/insta360", cv2.CAP_V4L2)
cap2.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap2.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

# --- OTHER WEBCAMS ---
cap3 = cv2.VideoCapture("/dev/video4") 
cap4 = cv2.VideoCapture("/dev/video0") 
cap5 = cv2.VideoCapture("/dev/mini_camera") 

# --- STARTUP LOGIC ---
try:
    # Start RealSense pipeline
    pipeline.start(config)
    print("RealSense camera initialized successfully.")
except Exception as e:
    print(f"RealSense Setup Error: {e}")

if not cap2.isOpened():
    print("Error: Insta360 not found at /dev/insta360.")

# --- PIXHAWK CONNECTION ---
PIXHAWK = None
try:
    print(f"Connecting to Pixhawk on {PIXHAWK_CONNECTION_PORT}...")
    PIXHAWK = mavutil.mavlink_connection(PIXHAWK_CONNECTION_PORT, baud=PIXHAWK_BAUDRATE)
    PIXHAWK.wait_heartbeat()
    print("Pixhawk connected!")
except Exception as e:
    print(f"Pixhawk Connection Failed: {e}")

# --- FRAME GENERATORS ---

def generate_realsense_dual_frame():
    """Generates two normal RGB streams side-by-side."""
    while True:
        try:
            frames = pipeline.wait_for_frames()
            color_frame = frames.get_color_frame()
            
            if not color_frame:
                continue

            # Convert RealSense frame to numpy array (standard RGB)
            color_image = np.asanyarray(color_frame.get_data())
            
            # Since you want two normal RGB streams on left and right:
            # We stack the same RGB image side-by-side to fill your dashboard slots
            combined_frame = np.hstack([color_image, color_image])

            ret, buffer = cv2.imencode('.jpg', combined_frame)
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        except Exception as e:
            print(f"RealSense RGB Error: {e}")
            time.sleep(0.1)

def generate_insta360_frame():
    """Generates the Insta360 feed with split-view rotation."""
    while True:
        if not cap2 or not cap2.isOpened():
            cap2.open("/dev/insta360", cv2.CAP_V4L2)
            time.sleep(1)
            continue

        success, frame = cap2.read()
        if not success:
            continue
            
        try:
            height, width, _ = frame.shape
            midpoint = height // 2
            top_half = frame[:midpoint, :]
            rotated_frame = cv2.rotate(top_half, cv2.ROTATE_90_CLOCKWISE)
            
            ret, buffer = cv2.imencode('.jpg', rotated_frame)
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        except Exception as e:
            print(f"Insta360 Error: {e}")
            continue

def generate_generic_frame(capture_device):
    """Generic generator for standard webcams."""
    while True:
        success, frame = capture_device.read()
        if not success:
            time.sleep(0.1)
            continue
        ret, buffer = cv2.imencode('.jpg', frame)
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

# --- FLASK ROUTES ---

@app.route('/')
def index():
    return render_template('dashboard.html')
@app.route('/test')
def testing():
    """Experimental route for RealSense and Insta360 testing."""
    return render_template('testing.html')
@app.route('/video_feed1')
def video_feed1():
    # Primary Dual Vision (RealSense)
    return Response(generate_realsense_dual_frame(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_feed2')
def video_feed2():
    return Response(generate_generic_frame(cap3), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_feed3')
def video_feed3():
    return Response(generate_generic_frame(cap4), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_feed4')
def video_feed4():
    # Sidebar view (Insta360)
    return Response(generate_insta360_frame(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_feed5')
def video_feed5():
    # Antenna/Top Cam
    return Response(generate_generic_frame(cap5), mimetype='multipart/x-mixed-replace; boundary=frame')

# --- SENSOR ROUTES (Placeholder logic) ---

@app.route('/rover-position')
def rover_position():
    # Dummy simulator data
    return jsonify({"x": 400, "y": 300, "heading": 0})

@app.route('/compass-value')
def compass_value():
    return jsonify({"angle": "0.00"})

if __name__ == '__main__':
    # Binding to 0.0.0.0 allows access from other devices on the same network
    app.run(host='0.0.0.0', port=5000)