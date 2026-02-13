import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Float32MultiArray
import serial
import time

port = "/dev/arduino_rover"
baurd = 115200

arm_port = "/dev/arduino_arm"
arm_baud = 9600

# ser = serial.Serial(port, baurd)
# arm = serial.Serial(arm_port, arm_baud)


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
        '''self.arm = None
        try:
            self.arm = serial.Serial(arm_port, arm_baud, timeout=0.1)
            time.sleep(2)
            self.arm.reset_input_buffer()      # ✅ SAME buffer clear (SAFE HERE)
        except Exception as e:
            self.get_logger().error(f"Arm serial error: {e}")'''
        

        self.motion_subscriber = self.create_subscription(String, "joystick_motion_cmd", self.motion_writer, 10)
        self.arm_subscriber = self.create_subscription(Float32MultiArray, "joystick_arm_cmd", self.arm_writer, 10)

    def arm_writer(self, msg: Float32MultiArray):
        data = list(msg.data)
        res = []
        res.extend(list(map(str, data[0:2])))
        for i in range(2, len(data)):
            res.append(str(int(data[i])))
        cmd = " ".join(res)
        # self.arm.reset_input_buffer()
        print(cmd)
        #self.arm.write((cmd + "\n").encode('utf-8'))
        	

    def motion_writer(self, msg: String):
        try:
            # Publisher already sends correct format: l20,r20
            cmd = msg.data.replace(".0", "")
            self.ser.reset_input_buffer()
            self.ser.write((cmd + "\n").encode('utf-8'))
            # time.sleep(2)
            print("Sent to rover:", cmd.strip())
            
            

        except Exception as e:
            self.get_logger().error(f"Serial write failed: {e}")

    
    # ================= CLEAN EXIT =================
    def destroy_node(self):

        if self.ser and self.ser.is_open:
            self.ser.close()

        # if self.arm and self.arm.is_open:
        #     self.arm.close()

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
