#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
import serial
import threading
import sys
import select


class StepperControlNode(Node):

    def __init__(self):
        super().__init__('stepper_control_node')

        # Serial connection
        self.ser = serial.Serial(
            port='/dev/arduino_arm',   # change if needed
            baudrate=9600,
            timeout=0.1
        )

        self.get_logger().info("Stepper Node Ready")
        self.get_logger().info("ENTER to move stepper")

        # Threads
        self.serial_thread = threading.Thread(
            target=self.read_serial,
            daemon=True
        )
        self.serial_thread.start()

        self.keyboard_thread = threading.Thread(
            target=self.keyboard_loop,
            daemon=True
        )
        self.keyboard_thread.start()

    # ---------------- Keyboard Input ----------------
    def keyboard_loop(self):
        while rclpy.ok():
            if select.select([sys.stdin], [], [], 0.1)[0]:
                cmd = sys.stdin.readline().strip()
                if cmd:
                    self.send_stepper_command(cmd)


    # ---------------- Send Stepper Command ----------------
    def send_stepper_command(self, value):
        command = f"{value}\n"
        self.ser.write(command.encode())
        print(f"[STEPPER COMMAND SENT] {value}")

    # ---------------- Read Arduino Feedback ----------------
    def read_serial(self):
        pass
        while rclpy.ok():
            if self.ser.in_waiting:
                line = self.ser.readline().decode('utf-8', errors='ignore').strip()
#                if line.startswith("Enter angle") :
                print(f"[STEPPER FEEDBACK] {line}")


def main(args=None):
    rclpy.init(args=args)
    node = StepperControlNode()
    rclpy.spin(node)

    node.ser.close()
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()