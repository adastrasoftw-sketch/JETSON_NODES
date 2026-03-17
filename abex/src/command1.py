#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

import serial
import threading
import time


class JetsonSerialBridge(Node):
    def __init__(self):
        super().__init__('jetson_serial_bridge')

        # -------- parameters --------
        self.declare_parameter('port', '/dev/ardu_cmd')
        self.declare_parameter('baud', 9600)

        self.port = self.get_parameter('port').value
        self.baud = self.get_parameter('baud').value

        # -------- ROS interfaces --------
        self.create_subscription(
            String,
            'robot_command',
            self.command_callback,
            10
        )

        self.feedback_pub = self.create_publisher(
            String,
            'arduino_feedback',
            10
        )

        # -------- serial --------
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.1)
            time.sleep(2)
            self.get_logger().info(
                f"Serial bridge connected on {self.port} @ {self.baud}"
            )
        except serial.SerialException as e:
            self.get_logger().error(f"Serial connection failed: {e}")
            rclpy.shutdown()
            raise RuntimeError("Serial failed")

        self.running = True
        threading.Thread(target=self.read_loop, daemon=True).start()

    def command_callback(self, msg):
        cmd = msg.data.strip()
        if cmd:
            self.ser.write((cmd + '\n').encode())

    def read_loop(self):
        while rclpy.ok() and self.running:
            if self.ser.in_waiting:
                line = self.ser.readline().decode(errors='ignore').strip()
                if line:
                    msg = String()
                    msg.data = line
                    self.feedback_pub.publish(msg)
            time.sleep(0.01)

    def destroy_node(self):
        self.running = False
        if self.ser.is_open:
            self.ser.close()
        super().destroy_node()


def main():
    rclpy.init()
    node = JetsonSerialBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
