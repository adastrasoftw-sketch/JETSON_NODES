from flask import render_template, Response, Flask,request,jsonify,send_file    
import random
import cv2
import numpy as np
import pyzed.sl as sl
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

app = Flask(__name__)

zed = sl.Camera()
left_image = sl.Mat()
right_image = sl.Mat()
#cap1 = cv2.VideoCapture("/dev/video0")
cap2 = cv2.VideoCapture("/dev/video2")  # Camera 2
cap3 = cv2.VideoCapture("/dev/video5")  # Camera 3
cap4 = cv2.VideoCapture("/dev/video8")  # Camera 3
PIXHAWK_CONNECTION_PORT = "/dev/ttyACM2"
PIXHAWK_BAUDRATE = 115200
PIXHAWK = None
PIXHAWK_stream_id = mavutil.mavlink.MAV_DATA_STREAM_ALL
PIXHAWK_rate_hz = 10


init_params = sl.InitParameters()
init_params.camera_resolution = sl.RESOLUTION.VGA  # Use HD720 resolution
init_params.depth_mode = sl.DEPTH_MODE.NONE          # Disable depth calculation
init_params.coordinate_units = sl.UNIT.METER         # Set unit to meters



cap2.set(cv2.CAP_PROP_FRAME_WIDTH, 480)
cap2.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

cap3.set(cv2.CAP_PROP_FRAME_WIDTH, 480)
cap3.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

cap4.set(cv2.CAP_PROP_FRAME_WIDTH, 480)
cap4.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

# Check if the cameras are opened correctly


status = zed.open(init_params)
if status != sl.ERROR_CODE.SUCCESS:
    print(f"Error opening zed camera : {status}")
    exit(1)
if not cap2.isOpened():
    print("Error: Camera 2 not found.")
if not cap3.isOpened():
    print("Error: Camera 3 not found.")
if not cap4.isOpened():
    print("Error: Camera 4 not found.")

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

def read_gps(master):
    try:
        print("Reading GPS Values")

        while True:
            gps_raw_int_msg = master.recv_match(type='GPS_RAW_INT', blocking=True, timeout=0.1)
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
        return 0, 0

def read_compass(master):
    try:
        print("Reading compass data...")
        while True:
            raw_imu_msg = master.recv_match(type='RAW_IMU', blocking=True, timeout=0.1)
            raw_imu = None

            if raw_imu_msg:
                data = raw_imu_msg.to_dict()
                xmag = data['xmag']
                ymag = data['ymag']

                rad = math.atan2(ymag, xmag)
                deg = math.degrees(rad)
                raw_imu = (deg + 360) % 360
                #print("read compass!!!")

                if raw_imu == None:
                    continue
                print("Giving degree : ", int(raw_imu))
                yield(raw_imu)
    except e:
        print(e)



def generate_zed_frame():
    # Initialize the ZED Mat objects
    left_image = sl.Mat()
    right_image = sl.Mat()

    while True:
        # Grab frames from the ZED camera
        if zed.grab() == sl.ERROR_CODE.SUCCESS:
            # Retrieve the left and right images
            zed.retrieve_image(left_image, sl.VIEW.LEFT)
            zed.retrieve_image(right_image, sl.VIEW.RIGHT)

            # Convert ZED Mat objects to NumPy arrays
            left_frame = left_image.get_data()
            right_frame = right_image.get_data()

            # Concatenate the frames horizontally
            combined_frame = np.hstack([left_frame, right_frame])

            # Encode the combined frame as JPEG
            ret, buffer = cv2.imencode('.jpg', combined_frame)
            frame = buffer.tobytes()

            # Yield the frame for streaming
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

def generate_frames2():
    while True:
        success, frame = cap4.read()  # Capture frame-by-frame
        if not success:
            break
        else:
            height, width, _ = frame.shape

            # Compute the midpoint
            midpoint = height // 2

            # Split the image into two halves
            top_half = frame[:midpoint, :]
            bottom_half = frame[midpoint:, :]
            # Rotate the image 90 degrees counterclockwise
            rotated_frame = cv2.rotate(top_half, cv2.ROTATE_90_CLOCKWISE)
            ret, buffer = cv2.imencode('.jpg', rotated_frame)
            frame = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')


def generate_frames3():
    while True:
        success, frame = cap3.read()  # Capture frame-by-frame
        if not success:
            break
        else:
            # Encode the frame as JPEG
            ret, buffer = cv2.imencode('.jpg', frame)
            frame = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

def generate_frames4():
    while True:
        success, frame = cap4.read()  # Capture frame-by-frame
        if not success:
            break
        else:
            # Encode the frame as JPEG
            ret, buffer = cv2.imencode('.jpg', frame)
            frame = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/video_feed1')
def video_feed1():
    # Route for the video feed
    print("Inside feed1")
    return Response(generate_zed_frame(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_feed2')
def video_feed2():
    # Route for the video feed
    return Response(generate_frames3(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_feed3')
def video_feed3():
    # Route for the video feed
    return Response(generate_frames2(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_feed4')
def video_feed4():
    # Route for the video feed
    return Response(generate_frames4(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/power-subsystem')
def power_subsystem():
    return render_template('power.html')

@app.route('/autonomous-mode/GNSS-submitted')
def autonomous_mode():
    return render_template('autonomous.html')

@app.route('/autonomous-mode')
def autonomous_GPS():
    return render_template('GNSSsubmission.html')

@app.route("/save", methods=["POST"])
def save_coordinates():
    try:
        data = request.get_json()

        # Folder where coordinates will be stored (inside static)
        folder = os.path.join(os.getcwd(), "static", "GNSS_coordinates")
        print("Saving to folder:", folder)

        # Delete the folder if it exists, then create a new one
        if os.path.exists(folder):
            shutil.rmtree(folder)
        os.makedirs(folder)

        # Save the JSON data directly
        file_path = os.path.join(folder, "coordinates.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        # Return a JSON response with a redirect URL
        return jsonify({"redirectUrl": "/autonomous-mode/GNSS-submitted"})

    except Exception as e:
        print("Error processing GNSS coordinates:", e)
        return jsonify({"error": "Internal Server Error"}), 500


@app.route('/science-subsystem')
def science_subsystem():
    data = {
        "MQ_8": {"value": 0},
        "MQ_9": {"percentage": 0, "stroke_dasharray": f"{0}, {100}"},
        "MQ_135": {"value": 0},
        "BME680": {"temperature": 0, "humidity": 0, "pressure": 0, "voc": 0},
        "SOIL_MOISTURE": {"value": 0, "stroke_dasharray": f"{0}, {100}"},
        "SOIL_TEMPERATURE": 0,
        "pH_Level": 0,
        "NPK_SENSOR": {"nitrogen": 0, "phosphorus": 0, "potassium": 0}
    }
    return render_template('science.html', data=data)

@app.route('/science-subsystem/hydrogen-concentration')
def hydrogen_concentration_data():
    val = random.randint(100, 10000)
    return {"hydrogen_concentration": val}

@app.route('/science-subsystem/combustible-gases')
def combustible_gases_data():
    val = random.randint(0, 100)
    return {"combustible_gases": val}

@app.route('/science-subsystem/pH-Level')
def pH_Level_data():
    val = random.randint(0, 14)
    return {"pH_Level": val}

@app.route('/science-subsystem/air-quality')
def air_quality_data():
    val = random.randint(10, 1000)
    return {"air_quality": val}

@app.route('/science-subsystem/soil-moisture')
def soil_moisture_data():
    val = random.randint(0, 100)
    return {"soil_moisture": val}

@app.route('/science-subsystem/soil-temperature')
def soil_temperature_data():
    val = random.randint(-40, 125)
    return {"soil_temperature": val}

@app.route('/science-subsystem/NPK')
def NPK_data():
    NPK = {"nitrogen": random.randint(0, 1000), "phosphorus": random.randint(0, 100), "potassium": random.randint(0, 1000)}
    return NPK

@app.route('/science-subsystem/BME680')
def BME680_data():
    BME680 = {"temperature": random.randint(-40, 85), "humidity": random.randint(0, 100), "pressure": random.randint(30000, 110000), "voc": random.randint(0,500)}
    return BME680

@app.route('/GPS')
def rover_location():
    lat,lon = read_gps(PIXHAWK)
    location = {
        'latitude': lat,
        'longitude': lon
    }
    return location


def generate_dummy_gps():
    # Simulate GPS movement around Bangalore
    lon,lat=read_gps(PIXHAWK)
    base_lat = lat
    base_long = lon
    return {"latitude": round(base_lat, 6), "longitude": round(base_long, 6)}

def generate_dummy_compass():
    # Simulate compass heading (0-360 degrees)
    compass=read_compass(PIXHAWK)
    return next(compass)

def generate_dummy_path():
    # Simulate current position in path
    current_time = time.time()
    # Create a moving point that follows the predefined path
    path_index = int((current_time % 7))  # Cycle through 7 points
    return path_index

@app.route('/api/sensor_data')
def get_sensor_data():
    gps = generate_dummy_gps()
    compass = generate_dummy_compass()
    mission_status = [
        random.choice([True, False]) for _ in range(7)
    ]
    path_progress = generate_dummy_path()
    
    return jsonify({
        "gps": gps,
        "compass": compass,
        "mission_status": mission_status,
        "path_progress": path_progress
    })

def latlon_to_meters(lat, lon, center_lat, center_lon):
    """
    Convert latitude/longitude (in degrees) to meters relative to a given center.
    """
    R = 6371000  # Earth radius in meters
    x = (lon - center_lon) * (np.pi/180) * R * np.cos(center_lat * np.pi/180)
    y = (lat - center_lat) * (np.pi/180) * R
    return x, y

def create_plot():
    # Load GNSS points from JSON file with key "gnssPoints"
    with open(os.path.join(os.getcwd(), "static", "GNSS_coordinates","coordinates.json"), "r") as file:
        data = json.load(file)
    
    # Extract latitude and longitude, converting strings to floats
    latitudes = [float(point["latitude"]) for point in data["gnssPoints"]]
    longitudes = [float(point["longitude"]) for point in data["gnssPoints"]]

    print(latitudes,longitudes)

    # Compute the center (mean latitude and longitude)
    center_lat = np.mean(latitudes)
    center_lon = np.mean(longitudes)

    # Convert all points from degrees to meters relative to the center
    points_in_meters = [
        latlon_to_meters(lat, lon, center_lat, center_lon)
        for lat, lon in zip(latitudes, longitudes)
    ]
    x_points, y_points = zip(*points_in_meters)

    # Create the plot with Matplotlib
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(x_points, y_points, color='blue', label="GNSS Points", zorder=3)

    # # Draw a dashed red circle with a 2 km radius
    # circle = plt.Circle((0, 0), 2000, color='red', fill=False, linestyle="dashed", label="2 km Radius")
    # ax.add_patch(circle)

    # Formatting the plot
    # ax.set_xlabel("East-West Distance (meters)")
    # ax.set_ylabel("North-South Distance (meters)")
    # ax.set_title("GNSS Points with 2 km Radius")
    ax.legend()
    ax.set_xlim(-2100, 2100)
    ax.set_ylim(-2100, 2100)
    ax.set_aspect('equal')

    # Save the plot into a bytes buffer as a PNG image
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight")
    buf.seek(0)
    plt.close(fig)
    return buf

@app.route("/plot.png")
def plot_png():
    buf = create_plot()
    return Response(buf.getvalue(), mimetype="image/png")


def generate_continuous_feed(image_path, mimetype):
    while True:
        # Process the image with a random rotation as before
        angle = random.uniform(0, 10)
        img = Image.open(image_path)
        img = img.rotate(angle, expand=False)
        buf = BytesIO()

        save_format = "PNG" if "png" in image_path.lower() else "JPEG"
        img.save(buf, format=save_format)
        buf.seek(0)

        # Construct the part of a multipart response
        frame = buf.read()
        yield (b'--frame\r\n'
               b'Content-Type: ' + mimetype.encode() + b'\r\n\r\n' + frame + b'\r\n')
        time.sleep(1)  # adjust delay as needed

@app.route("/xview_stream")
def xview_stream():
    return Response(generate_continuous_feed("static/images/sideview.png", "image/png"),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route("/yview_stream")
def yview_stream():
    return Response(generate_continuous_feed("static/images/topview.png", "image/png"),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route("/zview_stream")
def zview_stream():
    return Response(generate_continuous_feed("static/images/frontview.png", "image/png"),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route("/topview")
def topview():
    return send_file("static/images/pointed_rover.png","image/png")

@app.route("/arm")
def armview():
    return send_file("static/images/pointed.png","image/png")


#power
@app.route('/ampere-values-wheel')
def ampere_values_wheel():
    # Generate random ampere values for 6 items (for example, values between 0 and 10 A)
    data = {
        "item1": f"{0} A",
        "item2": f"{random.uniform(0, 10):.2f} A",
        "item3": f"{random.uniform(0, 10):.2f} A",
        "item4": f"{random.uniform(0, 10):.2f} A",
        "item5": f"{random.uniform(0, 10):.2f} A",
        "item6": f"{random.uniform(0, 10):.2f} A"
    }
    return jsonify(data)


@app.route('/ampere-values-arm')
def ampere_values_arm():
    # Generate random ampere values for 6 descriptors.
    data = {
        "desc1": f"{0} A",
        "desc2": f"{random.uniform(0, 10):.2f} A",
        "desc3": f"{random.uniform(0, 10):.2f} A",
        "desc4": f"{random.uniform(0, 10):.2f} A",
        "desc5": f"{random.uniform(0, 10):.2f} A",
        "desc6": f"{random.uniform(0, 10):.2f} A"
    }
    return jsonify(data)

@app.route('/compass-value')
def compass_value():
    # Generate a random compass angle between 0 and 360 degrees.
    angle = random.uniform(0, 0)
    # Return as JSON (formatted to 2 decimals for clarity)
    return jsonify({"angle": f"{angle:.2f}"})



class RoverSimulator:
    def __init__(self):
        # Initialize rover state
        self.x = 400  # Start in middle of canvas
        self.y = 300
        self.heading = random.uniform(0, 360)
        self.speed = 2
        self.last_update = time.time()
        
    def update_position(self):
        # Add some natural movement variation
        self.heading += random.uniform(-5, 5)  # Small random turns
        
        # Calculate new position
        dx = self.speed * math.cos(math.radians(self.heading))
        dy = self.speed * math.sin(math.radians(self.heading))
        
        # Update position
        self.x = max(50, min(750, self.x + dx))  # Keep within canvas bounds
        self.y = max(50, min(550, self.y + dy))
        
        # Bounce off edges
        if self.x <= 50 or self.x >= 750:
            self.heading = 180 - self.heading
        if self.y <= 50 or self.y >= 550:
            self.heading = -self.heading
            
        return {
            "x": round(self.x, 2),
            "y": round(self.y, 2),
            "heading": round(self.heading, 2)
        }

rover = RoverSimulator()

@app.route('/rover-position')
def rover_position():
    return jsonify(rover.update_position())


if __name__ == '__main__':
    app.run(host='192.168.1.110', port=5000)
