#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
import serial
import threading
import json
import re
import sys
import select


SEPARATOR = "----------------------------------------"


class ArduinoSnapshotPublisher(Node):

    def __init__(self):
        super().__init__('arduino_snapshot_publisher')

        self.publisher = self.create_publisher(
            String,
            'ardu_sensor',
            10
        )

        self.ser = serial.Serial(
            port='/dev/arduino_sensor',   # change if needed
            baudrate=9600,
            timeout=0.1
        )

        self.capture = False
        self.data = {}

        self.create_timer(0.05, self.read_serial)

        self.keyboard_thread = threading.Thread(
            target=self.keyboard_loop,
            daemon=True
        )
        self.keyboard_thread.start()

        self.get_logger().info("Press 'p' to capture one sensor dataset")

    # ---------------- Keyboard ----------------
    def keyboard_loop(self):
        while rclpy.ok():
            if select.select([sys.stdin], [], [], 0.1)[0]:
                key = sys.stdin.read(1)
                if key == 'p':
                    self.capture = True
                    self.data = {}
                    self.get_logger().info("Capturing one dataset...")

    # ---------------- Serial ----------------
    def read_serial(self):
        if not self.capture:
            self.flush_serial()
            return

        if self.ser.in_waiting:
            line = self.ser.readline().decode('utf-8', errors='ignore').strip()
            print(line)
            if not line:
                return

            if SEPARATOR in line:
                self.publish_snapshot()
                self.capture = False
                self.data = {}
                return

            self.parse_line(line)

    def flush_serial(self):
        while self.ser.in_waiting:
            self.ser.readline()

    # ---------------- Parsing ----------------
    def parse_line(self, line):
        try:
            if "Air Quality:" in line:
                self.data["air_quality"] = line.split(":")[1].strip()

            elif "Soil Moisture:" in line:
                self.data["soil_moisture_percent"] = int(re.findall(r"\d+", line)[0])

            elif "Soil Status:" in line:
                self.data["soil_status"] = line.split(":")[1].strip()

            elif "Soil Temperature:" in line:
                self.data["soil_temperature_c"] = float(re.findall(r"[-+]?\d*\.\d+|\d+", line)[0])

            elif "Temperature:" in line and "Soil" not in line:
                self.data["bme_temperature_c"] = float(re.findall(r"[-+]?\d*\.\d+|\d+", line)[0])

            elif "Humidity:" in line:
                self.data["humidity_percent"] = float(re.findall(r"[-+]?\d*\.\d+|\d+", line)[0])

            elif "Pressure:" in line:
                self.data["pressure_hpa"] = float(re.findall(r"[-+]?\d*\.\d+|\d+", line)[0])

            elif "Oxygen Concentration:" in line:
                self.data["oxygen_percent"] = float(re.findall(r"[-+]?\d*\.\d+|\d+", line)[0])

        except Exception as e:
            self.get_logger().warn(f"Parse error: {e}")

    # ---------------- Publish ----------------
    def publish_snapshot(self):
        if not self.data:
            self.get_logger().warn("No data captured")
            return

        msg = String()
        msg.data = json.dumps(self.data)
        self.publisher.publish(msg)

        self.get_logger().info(f"Published snapshot: {msg.data}")


def main(args=None):
    rclpy.init(args=args)
    node = ArduinoSnapshotPublisher()
    rclpy.spin(node)

    node.ser.close()
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()

