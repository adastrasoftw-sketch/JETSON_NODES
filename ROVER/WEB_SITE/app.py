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
from io import BytesIO
from PIL import Image
from collections import deque

# =========================
# CONFIG
# =========================
# Camera device paths (use /dev/v4l/by-id/... for stability if you can)
CAM_INSTA360_SRC = "/dev/video1" #science/end_effector
CAM3_SRC         = "/dev/video2" #webcam frame 2/Hopper Owl lite
CAM4_SRC         = "/dev/video4"#webcam frame 1
CAM_TOP_SRC      = "/dev/video6" #action camera

CAM_W   = 640
CAM_H   = 360
CAM_FPS = 15

# If True, prefer GStreamer pipelines (recommended on Jetson)
USE_GSTREAMER = True

PIXHAWK_CONNECTION_PORT = "/dev/ttyACM5"
PIXHAWK_BAUDRATE = 115200
PIXHAWK_rate_hz = 10

app = Flask(__name__)

# =========================
# QUIET / STABLE LOGGING
# =========================

class RateLimitedLogger:
    """Avoid spamming the same error every frame."""
    def __init__(self, min_interval_sec=3.0):
        self.min_interval_sec = float(min_interval_sec)
        self._last = {}

    def log(self, key: str, msg: str):
        now = time.time()
        last = self._last.get(key, 0)
        if now - last >= self.min_interval_sec:
            self._last[key] = now
            ts = time.strftime("%H:%M:%S")
            print(f"[{ts}] {msg}")

LOGGER = RateLimitedLogger(min_interval_sec=3.0)

# =========================
# CAMERA UTILITIES
# =========================

def safe_release(cap):
    try:
        if cap is not None:
            cap.release()
    except Exception:
        pass

def opencv_has_gstreamer():
    try:
        info = cv2.getBuildInformation()
        return "GStreamer: YES" in info
    except Exception:
        return False

HAS_GST = opencv_has_gstreamer()

def build_gst_mjpeg(device: str, width: int, height: int, fps: int) -> str:
    return (
        f"v4l2src device={device} ! "
        f"image/jpeg,width={width},height={height},framerate={fps}/1 ! "
        f"jpegdec ! videoconvert ! "
        f"appsink drop=true max-buffers=1 sync=false"
    )

def build_gst_raw(device: str, width: int, height: int, fps: int) -> str:
    # RAW avoids MJPEG corruption entirely (more USB bandwidth)
    return (
        f"v4l2src device={device} ! "
        f"video/x-raw,width={width},height={height},framerate={fps}/1 ! "
        f"videoconvert ! "
        f"appsink drop=true max-buffers=1 sync=false"
    )

def make_placeholder_jpeg(text: str, w=640, h=360):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    cv2.putText(img, text, (20, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2, cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
    return buf.tobytes() if ok else b""

# =========================
# THREAD SAFE CAMERA WORKER (HARDENED)
# =========================

class CameraWorker:
    """
    One capture thread per camera.
    Hardened features:
    - Catch cv2.error from MJPEG decode (prevents abort)
    - Failure counter with threshold (no reconnect-churn)
    - Auto fallback: MJPEG -> RAW (if corruption persists)
    - Rate-limited logs (keeps console clean)
    """
    def __init__(self, name, src, width, height, fps,
                 rotate=None, transform=None,
                 reconnect_sec=1.0, jpeg_quality=80,
                 use_gstreamer=False,
                 fail_reconnect_threshold=20,
                 corruption_fallback_threshold=8):
        self.name = name
        self.src = src
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.rotate = rotate
        self.transform = transform
        self.reconnect_sec = float(reconnect_sec)
        self.jpeg_quality = int(jpeg_quality)
        self.use_gstreamer = bool(use_gstreamer) and HAS_GST

        # thresholds
        self.fail_reconnect_threshold = int(fail_reconnect_threshold)
        self.corruption_fallback_threshold = int(corruption_fallback_threshold)

        # internal state
        self.cap = None
        self.latest_jpeg = make_placeholder_jpeg(f"{self.name}: starting...")
        self.lock = threading.Lock()

        self.running = False
        self.thread = None

        self.fail_count = 0
        self.decode_error_count = 0
        self._gst_mode = "mjpeg"  # "mjpeg" or "raw"

        # rolling window to decide if corruption is persistent
        self._recent_decode_errors = deque(maxlen=60)

    def _log(self, key, msg):
        LOGGER.log(f"{self.name}:{key}", f"{self.name}: {msg}")

    def _open(self):
        safe_release(self.cap)
        self.cap = None

        try:
            cap = None

            if self.use_gstreamer:
                # Try current mode first
                if self._gst_mode == "mjpeg":
                    pipeline = build_gst_mjpeg(self.src, self.width, self.height, self.fps)
                else:
                    pipeline = build_gst_raw(self.src, self.width, self.height, self.fps)

                cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
                if not cap.isOpened():
                    safe_release(cap)
                    cap = None

                    # Fallback attempt: if mjpeg failed, try raw; if raw failed, try mjpeg
                    alt_mode = "raw" if self._gst_mode == "mjpeg" else "mjpeg"
                    pipeline = build_gst_raw(self.src, self.width, self.height, self.fps) if alt_mode == "raw" else build_gst_mjpeg(self.src, self.width, self.height, self.fps)
                    cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)

                    if cap.isOpened():
                        self._gst_mode = alt_mode
                    else:
                        safe_release(cap)
                        cap = None

            if cap is None:
                cap = cv2.VideoCapture(self.src)
                if not cap.isOpened():
                    self._log("open", f"Failed to open {self.src}")
                    safe_release(cap)
                    return None

                # Best effort low latency & MJPEG preference
                try:
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(self.width))
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self.height))
                    cap.set(cv2.CAP_PROP_FPS, float(self.fps))
                    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                except Exception:
                    pass

            # If opened:
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass

            self.fail_count = 0
            self.decode_error_count = 0
            self._recent_decode_errors.clear()

            mode_info = f"gstreamer={self.use_gstreamer}, gst_mode={self._gst_mode}" if self.use_gstreamer else "gstreamer=False"
            self._log("openok", f"Opened {self.src} ({self.width}x{self.height}@{self.fps}, {mode_info})")
            return cap

        except Exception as e:
            self._log("openex", f"Open exception: {e}")
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
        safe_release(self.cap)
        self.cap = None

    def _should_fallback_to_raw(self):
        # if many decode errors in last 60 frames, switch to RAW mode
        if not self.use_gstreamer:
            return False
        if self._gst_mode == "raw":
            return False
        return sum(self._recent_decode_errors) >= self.corruption_fallback_threshold

    def _loop(self):
        self.cap = self._open()

        while self.running:
            if self.cap is None or (not self.cap.isOpened()):
                with self.lock:
                    self.latest_jpeg = make_placeholder_jpeg(f"{self.name}: camera not open")
                time.sleep(self.reconnect_sec)
                self.cap = self._open()
                continue

            try:
                ok, frame = self.cap.read()
            except cv2.error:
                self.fail_count += 1
                self.decode_error_count += 1
                self._recent_decode_errors.append(1)
                self._log("dec", f"Decode error (fail={self.fail_count})")
                ok, frame = False, None
            except Exception as e:
                self.fail_count += 1
                self._recent_decode_errors.append(0)
                self._log("readex", f"Read exception (fail={self.fail_count}): {e}")
                ok, frame = False, None

            if not ok or frame is None:
                self._recent_decode_errors.append(0)

                # auto switch to RAW if corruption persists
                if self._should_fallback_to_raw():
                    self._log("fallback", "Persistent MJPEG corruption detected -> switching to RAW pipeline")
                    self._gst_mode = "raw"
                    safe_release(self.cap)
                    self.cap = None
                    time.sleep(0.5)
                    self.cap = self._open()
                    continue

                # reconnect only if persistent failures
                if self.fail_count >= self.fail_reconnect_threshold:
                    self._log("reconn", "Too many read failures -> reconnecting")
                    safe_release(self.cap)
                    self.cap = None
                    self.fail_count = 0
                    time.sleep(self.reconnect_sec)
                    self.cap = self._open()
                else:
                    time.sleep(0.02)
                continue

            # good frame
            self.fail_count = 0
            self._recent_decode_errors.append(0)

            if self.transform is not None:
                try:
                    frame = self.transform(frame)
                except Exception:
                    # skip silently (do not spam)
                    continue

            if self.rotate is not None:
                try:
                    if self.rotate == 180:
                        frame = cv2.rotate(frame, cv2.ROTATE_180)
                    elif self.rotate == 90:
                        frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
                    elif self.rotate == -90:
                        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
                except Exception:
                    continue

            try:
                ret, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
                if not ret or buf is None or buf.size == 0:
                    continue
                jpg = buf.tobytes()
            except cv2.error:
                # skip silently
                continue

            with self.lock:
                self.latest_jpeg = jpg

            # small sleep to avoid maxing CPU
            time.sleep(0.001)

    def get_frame(self):
        with self.lock:
            return self.latest_jpeg


def mjpeg_stream(worker: CameraWorker):
    while True:
        frame = worker.get_frame()
        if frame is None:
            time.sleep(0.05)
            continue
        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
        time.sleep(0.03)

# =========================
# YOUR INSTA SPLIT LOGIC
# =========================

def insta_transform_tophalf(frame):
    h, w, _ = frame.shape
    return frame[: h // 2, :]

# =========================
# ZED WORKER (HARDENED)
# =========================

class ZEDWorker:
    def __init__(self, reconnect_sec=1.0, jpeg_quality=80):
        self.reconnect_sec = float(reconnect_sec)
        self.jpeg_quality = int(jpeg_quality)

        self.zed = None
        self.left = sl.Mat()
        self.right = sl.Mat()

        self.lock = threading.Lock()
        self.latest_jpeg = make_placeholder_jpeg("ZED: starting...")

        self.running = False
        self.thread = None

        self.init_params = sl.InitParameters()
        self.init_params.camera_resolution = sl.RESOLUTION.VGA
        self.init_params.depth_mode = sl.DEPTH_MODE.NONE
        self.init_params.coordinate_units = sl.UNIT.METER

        self.fail_count = 0

    def _log(self, key, msg):
        LOGGER.log(f"ZED:{key}", f"ZED: {msg}")

    def _open(self):
        try:
            if self.zed is not None:
                try:
                    self.zed.close()
                except Exception:
                    pass
                self.zed = None

            z = sl.Camera()
            status = z.open(self.init_params)
            if status != sl.ERROR_CODE.SUCCESS:
                self._log("open", f"Open failed: {status}")
                return None

            self._log("openok", "Opened")
            self.fail_count = 0
            return z
        except Exception as e:
            self._log("openex", f"Open exception: {e}")
            return None

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        self.zed = self._open()

        while self.running:
            if self.zed is None:
                with self.lock:
                    self.latest_jpeg = make_placeholder_jpeg("ZED: not available")
                time.sleep(self.reconnect_sec)
                self.zed = self._open()
                continue

            try:
                if self.zed.grab() != sl.ERROR_CODE.SUCCESS:
                    self.fail_count += 1
                    if self.fail_count >= 10:
                        self._log("grab", "Grab failing persistently -> reconnecting")
                        try:
                            self.zed.close()
                        except Exception:
                            pass
                        self.zed = None
                        self.fail_count = 0
                    time.sleep(0.02)
                    continue

                self.fail_count = 0

                self.zed.retrieve_image(self.left, sl.VIEW.LEFT)
                self.zed.retrieve_image(self.right, sl.VIEW.RIGHT)

                lf = self.left.get_data()
                rf = self.right.get_data()

                if lf.shape[-1] == 4:
                    lf = lf[:, :, :3]
                if rf.shape[-1] == 4:
                    rf = rf[:, :, :3]

                combined = np.hstack([lf, rf])

                ret, buf = cv2.imencode(".jpg", combined, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
                if ret and buf is not None and buf.size > 0:
                    with self.lock:
                        self.latest_jpeg = buf.tobytes()

            except Exception as e:
                self._log("loop", f"Exception -> reconnect: {e}")
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
            time.sleep(0.05)
            continue
        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
        time.sleep(0.03)

# =========================
# PIXHAWK (HARDENED: background thread, non-blocking routes)
# =========================

class PixhawkReader:
    def __init__(self, port, baud, rate_hz=10):
        self.port = port
        self.baud = baud
        self.rate_hz = int(rate_hz)
        self.master = None

        self.lock = threading.Lock()
        self.latest_gps = {"lat": 0.0, "lon": 0.0}
        self.latest_compass = 0.0

        self.running = False
        self.thread = None

    def _log(self, key, msg):
        LOGGER.log(f"PIX:{key}", f"PIXHAWK: {msg}")

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _connect(self):
        try:
            self._log("conn", f"Connecting on {self.port}...")
            m = mavutil.mavlink_connection(self.port, baud=self.baud)
            m.wait_heartbeat(timeout=5)
            self._log("connok", "Connected (heartbeat).")
            try:
                m.mav.request_data_stream_send(
                    m.target_system,
                    m.target_component,
                    mavutil.mavlink.MAV_DATA_STREAM_ALL,
                    self.rate_hz,
                    1
                )
            except Exception:
                pass
            return m
        except Exception as e:
            self._log("connfail", f"Connect failed: {e}")
            return None

    def _loop(self):
        while self.running:
            if self.master is None:
                self.master = self._connect()
                if self.master is None:
                    time.sleep(2.0)
                    continue

            try:
                msg = self.master.recv_match(blocking=True, timeout=0.2)
                if not msg:
                    continue

                t = msg.get_type()
                if t == "GPS_RAW_INT":
                    d = msg.to_dict()
                    lat = d.get("lat", 0) / 1e7
                    lon = d.get("lon", 0) / 1e7
                    with self.lock:
                        self.latest_gps = {"lat": lat, "lon": lon}

                elif t == "RAW_IMU":
                    d = msg.to_dict()
                    xmag = d.get("xmag", 0.0)
                    ymag = d.get("ymag", 0.0)
                    deg = math.degrees(math.atan2(ymag, xmag))
                    heading = (deg + 360) % 360
                    with self.lock:
                        self.latest_compass = heading

            except Exception as e:
                self._log("read", f"Read error -> reconnect: {e}")
                try:
                    self.master.close()
                except Exception:
                    pass
                self.master = None
                time.sleep(1.0)

    def get(self):
        with self.lock:
            return self.latest_gps.copy(), float(self.latest_compass)

pixhawk = PixhawkReader(PIXHAWK_CONNECTION_PORT, PIXHAWK_BAUDRATE, PIXHAWK_rate_hz)
pixhawk.start()

# =========================
# START WORKERS
# =========================

zed_worker = ZEDWorker()
zed_worker.start()

cam_insta360 = CameraWorker(
    name="Insta360",
    src=CAM_INSTA360_SRC,
    width=CAM_W, height=CAM_H, fps=15,
    #transform=insta_transform_tophalf,
    rotate=180,
    reconnect_sec=1.0,
    jpeg_quality=80,
    use_gstreamer=USE_GSTREAMER,
    fail_reconnect_threshold=25,
    corruption_fallback_threshold=8
)

cam3 = CameraWorker(
    name="Cam3",
    src=CAM3_SRC,
    width=CAM_W, height=CAM_H, fps=CAM_FPS,
    rotate=None,
    reconnect_sec=1.0,
    jpeg_quality=80,
    use_gstreamer=USE_GSTREAMER,
    fail_reconnect_threshold=25,
    corruption_fallback_threshold=8
)

cam4 = CameraWorker(
    name="Cam4",
    src=CAM4_SRC,
    width=CAM_W, height=CAM_H, fps=CAM_FPS,
    rotate=None,
    reconnect_sec=1.0,
    jpeg_quality=80,
    use_gstreamer=USE_GSTREAMER,
    fail_reconnect_threshold=25,
    corruption_fallback_threshold=8
)

cam_top = CameraWorker(
    name="TopCam",
    src=CAM_TOP_SRC,
    width=CAM_W, height=CAM_H, fps=CAM_FPS,
    #invert
    rotate=90,
    reconnect_sec=1.0,
    jpeg_quality=80,
    use_gstreamer=USE_GSTREAMER,
    fail_reconnect_threshold=25,
    corruption_fallback_threshold=8
)

cam_insta360.start()
cam3.start()
cam4.start()
cam_top.start()

# =========================
# ROUTES
# =========================

@app.route("/")
def index():
    return render_template("dashboard.html")

@app.route("/video_feed1")
def video_feed1():
    return Response(zed_stream(zed_worker), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/video_feed2")
def video_feed2():
    return Response(mjpeg_stream(cam3), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/video_feed3")
def video_feed3():
    return Response(mjpeg_stream(cam4), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/video_feed4")
def video_feed4():
    return Response(mjpeg_stream(cam_insta360), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/video_feed5")
def video_feed5():
    return Response(mjpeg_stream(cam_top), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/GPS")
def rover_location():
    gps, _ = pixhawk.get()
    # keep your output format
    return {"latitude": gps["lat"], "longitude": gps["lon"]}

@app.route("/api/sensor_data")
def get_sensor_data():
    gps, compass = pixhawk.get()
    mission_status = [random.choice([True, False]) for _ in range(7)]
    path_progress = int(time.time() % 7)

    return jsonify({
        "gps": {"latitude": round(gps["lat"], 6), "longitude": round(gps["lon"], 6)},
        "compass": compass,
        "mission_status": mission_status,
        "path_progress": path_progress
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
