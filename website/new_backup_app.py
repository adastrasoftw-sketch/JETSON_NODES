# app.py
# Full working Flask server with robust multi-camera streaming on Jetson AGX Orin.
# Key fixes:
# 1) One capture thread per camera (stable under multiple viewers)
# 2) Auto-reconnect when USB resets / /dev/video* changes (use /dev/v4l/by-id for best results)
# 3) Forces MJPEG + lower FPS to reduce USB bandwidth
# 4) Never "break" on read failures (keeps recovering)
# 5) Optional ZED stream preserved (as a worker too)

from flask import render_template, Response, Flask, request, jsonify, send_file
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
import threading
import serial  # pyserial
from io import BytesIO
from PIL import Image

# -----------------------------
# CONFIG
# -----------------------------
SERIAL_PORT = "/dev/ttyACM8"
SERIAL_BAUD = 9600

PIXHAWK_CONNECTION_PORT = "/dev/ttyACM5"
PIXHAWK_BAUDRATE = 115200
PIXHAWK_stream_id = mavutil.mavlink.MAVLINK_MSG_ID_DATA_STREAM if hasattr(mavutil.mavlink, "MAVLINK_MSG_ID_DATA_STREAM") else mavutil.mavlink.MAV_DATA_STREAM_ALL
PIXHAWK_rate_hz = 10

# IMPORTANT:
# Use stable device paths to survive USB re-enumeration:
#   ls -l /dev/v4l/by-id/
# Then set these to by-id paths instead of /dev/videoX.
CAM_INSTA360_SRC = "/dev/video0"
CAM3_SRC        = "/dev/video8"  # Camera 3
CAM4_SRC        = "/dev/video2"  # Camera 4
CAM_TOP_SRC     = "/dev/video10"  # Top/Antenna cam

# Camera settings (keep modest to reduce USB bandwidth)
CAM_W = 640
CAM_H = 360
CAM_FPS = 15

app = Flask(__name__)

# -----------------------------
# THREAD SAFE CAMERA WORKER
# -----------------------------
class CameraWorker:
    """
    One thread per camera. Continuously captures frames and keeps the latest JPEG bytes.
    Auto-reconnects if read fails (typical after USB reset).
    """
    def __init__(self, name, src, width=640, height=360, fps=15,
                 rotate=None, mjpeg=True, reconnect_sec=1.0, transform=None, jpeg_quality=80):
        self.name = name
        self.src = src
        self.width = width
        self.height = height
        self.fps = fps
        self.rotate = rotate  # None, 180, 90, -90
        self.mjpeg = mjpeg
        self.reconnect_sec = reconnect_sec
        self.transform = transform
        self.jpeg_quality = int(jpeg_quality)

        self.cap = None
        self.latest_jpeg = None
        self.lock = threading.Lock()

        self.running = False
        self.thread = None

    def _log(self, msg):
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] {self.name}: {msg}")

    def _open(self):
        # close old
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

        cap = cv2.VideoCapture(self.src, cv2.CAP_V4L2)
        if not cap.isOpened():
            self._log(f"Failed to open {self.src}")
            return None

        # Reduce buffering (important for live stream)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        # Force MJPEG to reduce USB bandwidth if supported
        if self.mjpeg:
            try:
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            except Exception:
                pass

        # Apply capture settings
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(self.width))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self.height))
        cap.set(cv2.CAP_PROP_FPS, float(self.fps))

        self._log(f"Opened {self.src} (target {self.width}x{self.height}@{self.fps}fps, mjpeg={self.mjpeg})")
        return cap

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

    def _loop(self):
        self.cap = self._open()

        while self.running:
            if self.cap is None or (not self.cap.isOpened()):
                time.sleep(self.reconnect_sec)
                self.cap = self._open()
                continue

            ok, frame = self.cap.read()
            if not ok or frame is None:
                self._log("Read failed. Reconnecting...")
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.cap = None
                time.sleep(self.reconnect_sec)
                continue

            # Optional frame transform (cropping/splitting etc.)
            if self.transform is not None:
                try:
                    frame = self.transform(frame)
                except Exception as e:
                    self._log(f"Transform failed: {e}")
                    continue

            # Optional rotate
            if self.rotate == 180:
                frame = cv2.rotate(frame, cv2.ROTATE_180)
            elif self.rotate == 90:
                frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
            elif self.rotate == -90:
                frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

            # Encode once here; Flask endpoints just serve bytes
            ret, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
            if not ret:
                self._log("JPEG encode failed (skipping frame)")
                continue

            jpg = buf.tobytes()
            with self.lock:
                self.latest_jpeg = jpg

            # If camera ignores FPS setting, a tiny sleep prevents CPU max-out
            time.sleep(0.001)

    def get_frame(self):
        with self.lock:
            return self.latest_jpeg


def mjpeg_stream(worker: CameraWorker):
    """
    HTTP MJPEG stream. Keeps connection alive even when camera is reconnecting.
    """
    while True:
        frame = worker.get_frame()
        if frame is None:
            time.sleep(0.1)
            continue

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        time.sleep(0.03)  # limit client push rate


# -----------------------------
# ZED WORKER (optional)
# -----------------------------
class ZEDWorker:
    """
    Captures combined left+right ZED frames and keeps latest JPEG bytes.
    Auto-reconnects if ZED fails.
    """
    def __init__(self, name="ZED", reconnect_sec=1.0, jpeg_quality=80):
        self.name = name
        self.reconnect_sec = reconnect_sec
        self.jpeg_quality = int(jpeg_quality)

        self.zed = None
        self.left_image = None
        self.right_image = None
        self.lock = threading.Lock()
        self.latest_jpeg = None

        self.running = False
        self.thread = None

        self.init_params = sl.InitParameters()
        self.init_params.camera_resolution = sl.RESOLUTION.VGA
        self.init_params.depth_mode = sl.DEPTH_MODE.NONE
        self.init_params.coordinate_units = sl.UNIT.METER

    def _log(self, msg):
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] {self.name}: {msg}")

    def _open(self):
        # close old
        if self.zed is not None:
            try:
                self.zed.close()
            except Exception:
                pass
            self.zed = None

        try:
            zed = sl.Camera()
            status = zed.open(self.init_params)
            if status != sl.ERROR_CODE.SUCCESS:
                self._log(f"Error opening ZED camera: {status}")
                return None

            cam_info = zed.get_camera_information()
            self._log(f"ZED Model: {cam_info.camera_model}, Serial: {cam_info.serial_number}, FW: {cam_info.camera_configuration.firmware_version}")

            self.left_image = sl.Mat()
            self.right_image = sl.Mat()
            self._log("ZED opened successfully")
            return zed
        except Exception as e:
            self._log(f"ZED setup error: {e}")
            return None

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        if self.zed:
            try:
                self.zed.close()
            except Exception:
                pass
            self.zed = None

    def _loop(self):
        self.zed = self._open()

        while self.running:
            if self.zed is None:
                time.sleep(self.reconnect_sec)
                self.zed = self._open()
                continue

            try:
                if self.zed.grab() != sl.ERROR_CODE.SUCCESS:
                    self._log("Grab failed. Reconnecting...")
                    try:
                        self.zed.close()
                    except Exception:
                        pass
                    self.zed = None
                    time.sleep(self.reconnect_sec)
                    continue

                self.zed.retrieve_image(self.left_image, sl.VIEW.LEFT)
                self.zed.retrieve_image(self.right_image, sl.VIEW.RIGHT)

                left_frame = self.left_image.get_data()
                right_frame = self.right_image.get_data()

                # Ensure 3 channels
                if left_frame.shape[-1] == 4:
                    left_frame = left_frame[:, :, :3]
                if right_frame.shape[-1] == 4:
                    right_frame = right_frame[:, :, :3]

                combined = np.hstack([left_frame, right_frame])

                ret, buf = cv2.imencode(".jpg", combined, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
                if not ret:
                    self._log("JPEG encode failed (skipping)")
                    continue

                jpg = buf.tobytes()
                with self.lock:
                    self.latest_jpeg = jpg

            except Exception as e:
                self._log(f"Exception in loop: {e}. Reconnecting...")
                try:
                    self.zed.close()
                except Exception:
                    pass
                self.zed = None
                time.sleep(self.reconnect_sec)

    def get_frame(self):
        with self.lock:
            return self.latest_jpeg


def zed_stream(zed_worker: ZEDWorker):
    while True:
        frame = zed_worker.get_frame()
        if frame is None:
            # keep alive
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + b'')
            time.sleep(0.1)
            continue
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        time.sleep(0.03)


# -----------------------------
# Pixhawk setup
# -----------------------------
PIXHAWK = None
try:
    print(f"Connecting to Pixhawk on {PIXHAWK_CONNECTION_PORT}...")
    PIXHAWK = mavutil.mavlink_connection(PIXHAWK_CONNECTION_PORT, baud=PIXHAWK_BAUDRATE)
    PIXHAWK.wait_heartbeat()
    print("Pixhawk connected! Heartbeat received.")
    try:
        PIXHAWK.mav.request_data_stream_send(
            PIXHAWK.target_system,
            PIXHAWK.target_component,
            mavutil.mavlink.MAV_DATA_STREAM_ALL,
            PIXHAWK_rate_hz,
            1
        )
        print(f"Requested data stream at {PIXHAWK_rate_hz} Hz.")
    except Exception as e:
        print(f"Data stream request failed (non-fatal): {e}")
except Exception as e:
    print(f"Failed to connect to Pixhawk: {e}")
    PIXHAWK = None


def read_gps(master):
    if master is None:
        return 0.0, 0.0
    try:
        while True:
            msg = master.recv_match(type='GPS_RAW_INT', blocking=True, timeout=0.2)
            if not msg:
                return 0.0, 0.0
            data = msg.to_dict()
            lat = data.get('lat', 0) / 1e7
            lon = data.get('lon', 0) / 1e7
            return lon, lat
    except Exception:
        return 0.0, 0.0


def read_compass(master):
    if master is None:
        # yield zeros forever
        while True:
            yield 0.0
    try:
        while True:
            msg = master.recv_match(type='RAW_IMU', blocking=True, timeout=0.2)
            if not msg:
                yield 0.0
                continue
            data = msg.to_dict()
            xmag = data.get('xmag', 0.0)
            ymag = data.get('ymag', 0.0)
            rad = math.atan2(ymag, xmag)
            deg = math.degrees(rad)
            heading = (deg + 360) % 360
            yield heading
    except Exception:
        while True:
            yield 0.0


# -----------------------------
# Camera transforms (optional)
# -----------------------------
def insta_transform_tophalf(frame):
    """
    Your original code: split frame into two halves and use top half.
    """
    h, w, c = frame.shape
    midpoint = h // 2
    top_half = frame[:midpoint, :]
    return top_half


# -----------------------------
# Start workers at boot
# -----------------------------
# ZED
zed_worker = ZEDWorker()
zed_worker.start()

# USB cameras
cam_insta360 = CameraWorker(
    name="Insta360",
    src=CAM_INSTA360_SRC,
    width=CAM_W, height=CAM_H, fps=CAM_FPS,
    transform=insta_transform_tophalf,  # keep your original behavior
    rotate=90,  # your original: rotate top-half 90 CW
    mjpeg=True,
    reconnect_sec=1.0,
    jpeg_quality=80
)

cam_3 = CameraWorker(
    name="Cam3",
    src=CAM3_SRC,
    width=CAM_W, height=CAM_H, fps=CAM_FPS,
    rotate=None,
    mjpeg=True,
    reconnect_sec=1.0
)

cam_4 = CameraWorker(
    name="Cam4",
    src=CAM4_SRC,
    width=CAM_W, height=CAM_H, fps=CAM_FPS,
    rotate=None,
    mjpeg=True,
    reconnect_sec=1.0
)

cam_top = CameraWorker(
    name="TopCam",
    src=CAM_TOP_SRC,
    width=CAM_W, height=CAM_H, fps=CAM_FPS,
    rotate=180,  # your original: rotate 180
    mjpeg=True,
    reconnect_sec=1.0
)

cam_insta360.start()
cam_3.start()
cam_4.start()
cam_top.start()

# -----------------------------
# Serial worker (optional for /current-sensor)
# -----------------------------
class SerialWorker:
    def __init__(self, port, baud=9600, reconnect_sec=1.0):
        self.port = port
        self.baud = baud
        self.reconnect_sec = reconnect_sec

        self.ser = None
        self.latest_line = None
        self.lock = threading.Lock()

        self.running = False
        self.thread = None

    def _log(self, msg):
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] SERIAL: {msg}")

    def _open(self):
        try:
            s = serial.Serial(self.port, self.baud, timeout=1)
            self._log(f"Opened {self.port}@{self.baud}")
            return s
        except Exception as e:
            self._log(f"Open failed {self.port}: {e}")
            return None

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        self.ser = self._open()
        while self.running:
            if self.ser is None:
                time.sleep(self.reconnect_sec)
                self.ser = self._open()
                continue
            try:
                line = self.ser.readline().decode("utf-8", errors="ignore").strip()
                if line:
                    with self.lock:
                        self.latest_line = line
            except Exception as e:
                self._log(f"Read failed: {e}. Reconnecting...")
                try:
                    self.ser.close()
                except Exception:
                    pass
                self.ser = None
                time.sleep(self.reconnect_sec)

    def get_latest(self):
        with self.lock:
            return self.latest_line

serial_worker = SerialWorker(SERIAL_PORT, SERIAL_BAUD, reconnect_sec=1.0)
# Start only if you really have device connected; otherwise it will keep retrying.
# serial_worker.start()

# -----------------------------
# Web routes
# -----------------------------
@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/video_feed1')
def video_feed1():
    # ZED combined
    return Response(zed_stream(zed_worker), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_feed2')
def video_feed2():
    # cam_3
    return Response(mjpeg_stream(cam_3), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_feed3')
def video_feed3():
    # cam_4
    return Response(mjpeg_stream(cam_4), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_feed4')
def video_feed4():
    # Insta360 (top-half + rotate)
    return Response(mjpeg_stream(cam_insta360), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_feed5')
def video_feed5():
    # Top/Antenna cam
    return Response(mjpeg_stream(cam_top), mimetype='multipart/x-mixed-replace; boundary=frame')


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
        folder = os.path.join(os.getcwd(), "static", "GNSS_coordinates")
        print("Saving to folder:", folder)

        if os.path.exists(folder):
            shutil.rmtree(folder)
        os.makedirs(folder, exist_ok=True)

        file_path = os.path.join(folder, "coordinates.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

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
    return {"nitrogen": random.randint(0, 1000),
            "phosphorus": random.randint(0, 100),
            "potassium": random.randint(0, 1000)}

@app.route('/science-subsystem/BME680')
def BME680_data():
    return {"temperature": random.randint(-40, 85),
            "humidity": random.randint(0, 100),
            "pressure": random.randint(30000, 110000),
            "voc": random.randint(0, 500)}

@app.route('/GPS')
def rover_location():
    lon, lat = read_gps(PIXHAWK)
    return {'latitude': lat, 'longitude': lon}


def generate_dummy_gps():
    lon, lat = read_gps(PIXHAWK)
    return {"latitude": round(lat, 6), "longitude": round(lon, 6)}

def generate_dummy_compass():
    compass_gen = read_compass(PIXHAWK)
    return float(next(compass_gen))

def generate_dummy_path():
    current_time = time.time()
    return int((current_time % 7))

@app.route('/api/sensor_data')
def get_sensor_data():
    gps = generate_dummy_gps()
    compass = generate_dummy_compass()
    mission_status = [random.choice([True, False]) for _ in range(7)]
    path_progress = generate_dummy_path()

    return jsonify({
        "gps": gps,
        "compass": compass,
        "mission_status": mission_status,
        "path_progress": path_progress
    })


def latlon_to_meters(lat, lon, center_lat, center_lon):
    R = 6371000
    x = (lon - center_lon) * (np.pi/180) * R * np.cos(center_lat * np.pi/180)
    y = (lat - center_lat) * (np.pi/180) * R
    return x, y

def create_plot():
    coords_path = os.path.join(os.getcwd(), "static", "GNSS_coordinates", "coordinates.json")
    with open(coords_path, "r") as file:
        data = json.load(file)

    latitudes = [float(p["latitude"]) for p in data["gnssPoints"]]
    longitudes = [float(p["longitude"]) for p in data["gnssPoints"]]

    center_lat = np.mean(latitudes)
    center_lon = np.mean(longitudes)

    points_in_meters = [latlon_to_meters(lat, lon, center_lat, center_lon) for lat, lon in zip(latitudes, longitudes)]
    x_points, y_points = zip(*points_in_meters)

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(x_points, y_points, color='blue', label="GNSS Points", zorder=3)
    ax.legend()
    ax.set_xlim(-2100, 2100)
    ax.set_ylim(-2100, 2100)
    ax.set_aspect('equal')

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
        angle = random.uniform(0, 10)
        img = Image.open(image_path)
        img = img.rotate(angle, expand=False)
        buf = BytesIO()
        save_format = "PNG" if "png" in image_path.lower() else "JPEG"
        img.save(buf, format=save_format)
        buf.seek(0)

        frame = buf.read()
        yield (b'--frame\r\n'
               b'Content-Type: ' + mimetype.encode() + b'\r\n\r\n' + frame + b'\r\n')
        time.sleep(1)

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
    return send_file("static/images/pointed_rover.png", mimetype="image/png")

@app.route("/arm")
def armview():
    return send_file("static/images/pointed.png", mimetype="image/png")


# power
@app.route('/ampere-values-wheel')
def ampere_values_wheel():
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
    angle = 0.0
    return jsonify({"angle": f"{angle:.2f}"})


class RoverSimulator:
    def __init__(self):
        self.x = 400
        self.y = 300
        self.heading = random.uniform(0, 360)
        self.speed = 2

    def update_position(self):
        self.heading += random.uniform(-5, 5)
        dx = self.speed * math.cos(math.radians(self.heading))
        dy = self.speed * math.sin(math.radians(self.heading))

        self.x = max(50, min(750, self.x + dx))
        self.y = max(50, min(550, self.y + dy))

        if self.x <= 50 or self.x >= 750:
            self.heading = 180 - self.heading
        if self.y <= 50 or self.y >= 550:
            self.heading = -self.heading

        return {"x": round(self.x, 2), "y": round(self.y, 2), "heading": round(self.heading, 2)}

rover = RoverSimulator()

@app.route('/rover-position')
def rover_position():
    return jsonify(rover.update_position())


@app.route('/current-sensor')
def read_current():
    # If you enable serial_worker.start(), this returns the latest line
    line = serial_worker.get_latest()
    if line is None:
        return jsonify({"value": None, "status": "no-data"})
    return jsonify({"value": line, "status": "ok"})


# -----------------------------
# Main
# -----------------------------
if __name__ == '__main__':
    # IMPORTANT for Jetson stability:
    # Use threaded=True so multiple stream endpoints can work simultaneously.
    # Consider running behind gunicorn for production, but this works for rover use.
    app.run(host='0.0.0.0', port=5000, threaded=True)
