# import serial
# import time

# # Use the ACM port discovered by ls /dev/ttyACM*
# s = serial.Serial('/dev/ttyACM0', 115200, timeout=1)
# time.sleep(2) # Wait for Arduino reset

# print("Sending hardcoded move command...")
# s.write(b"l30,r30\n")
# s.flush()

# # Read response
# time.sleep(0.5)
# if s.in_waiting:
#     print("Arduino says:", s.readline().decode())
# s.close()

import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Float32MultiArray
import serial
import time

port = "/dev/arduino_rover"
baurd = 115200

arm_port = "/dev/arduino_arm"
arm_baud = 9600


class Controller(Node):

    def __init__(self):
        super().__init__("serial_cmd_reciever")

        # ---------- Rover Serial ----------
        self.ser = None
        try:
            self.ser = serial.Serial(port, baurd, timeout=0.1)
            time.sleep(2)                      # Arduino reset
            self.ser.reset_input_buffer()      # ✅ SAME buffer clear (SAFE HERE)
        except Exception as e:
            self.get_logger().error(f"Rover serial error: {e}")

        # ---------- Arm Serial ----------
        self.arm = None
        try:
            self.arm = serial.Serial(arm_port, arm_baud, timeout=0.1)
            time.sleep(2)
            self.arm.reset_input_buffer()      # ✅ SAME buffer clear (SAFE HERE)
        except Exception as e:
            self.get_logger().error(f"Arm serial error: {e}")

        # ---------- Rate limit (CRITICAL) ----------
        self.last_rover_write = 0.0
        self.rover_interval = 0.05   # 20 Hz

        self.motion_subscriber = self.create_subscription(
            String,
            "joystick_motion_cmd",
            self.motion_writer,
            10
        )

        self.arm_subscriber = self.create_subscription(
            Float32MultiArray,
            "joystick_arm_cmd",
            self.arm_writer,
            10
        )

    # ================= ARM =================
    def arm_writer(self, msg: Float32MultiArray):
        if self.arm is None or not self.arm.is_open:
            return

        try:
            data = list(msg.data)
            res = []
            res.extend(map(str, data[0:2]))
            for i in range(2, len(data)):
                res.append(str(int(data[i])))

            cmd = " ".join(res)
            print(cmd)
            self.arm.write((cmd + "\n").encode("utf-8"))

        except Exception as e:
            self.get_logger().error(f"Arm serial write failed: {e}")
            self.arm.reset_input_buffer()   # ✅ buffer clear ONLY on error

    # ================= ROVER =================
    def motion_writer(self, msg: String):
        if self.ser is None or not self.ser.is_open:
            return

        now = time.time()
        if now - self.last_rover_write < self.rover_interval:
            return

        try:
            cmd = msg.data.replace(".0", "")
            self.ser.write((cmd + "\n").encode("utf-8"))
            print("Sent to rover:", cmd.strip())
            self.last_rover_write = now

        except Exception as e:
            self.get_logger().error(f"Serial write failed: {e}")
            self.ser.reset_input_buffer()   # ✅ buffer clear ONLY on error

    # ================= CLEAN EXIT =================
    def destroy_node(self):

        if self.ser and self.ser.is_open:
            self.ser.close()

        if self.arm and self.arm.is_open:
            self.arm.close()

        super().destroy_node()


def main():
    rclpy.init()
    node = Controller()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
