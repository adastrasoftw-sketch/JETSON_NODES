import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32MultiArray
import serial
import time

class JoystickSerialNode(Node):
    def __init__(self):
        super().__init__('joystick_serial_node')

        # Initialize subscriber
        self.subscription = self.create_subscription(
            Float32MultiArray,
            '/joystick_arm_cmd',  # Replace with your actual topic name
            self.listener_callback,
            10
        )
        self.subscription  # prevent unused variable warning

        # Initialize serial communication
        try:
            self.ser = serial.Serial('/dev/ttyACM1', 9600)  # Replace with your Arduino's COM port
            time.sleep(2)  # Allow Arduino to reset
            self.ser.reset_input_buffer()  # Clear input buffer
            self.ser.reset_output_buffer()  # Clear output buffer
            self.get_logger().info("Serial port initialized successfully.")
        except Exception as e:
            self.get_logger().error(f"Failed to initialize serial port: {e}")
            self.ser = None

    def listener_callback(self, msg):
        # Log received data
        self.get_logger().info(f"Received data: {msg.data}")

        # Extract axes and button data
        try:
            # Assumes data format [y_axis, z_axis, button1, button2, ...]
            y_axis = msg.data[0]
            z_axis = msg.data[1]
            buttons = msg.data[2:]  # Remaining values are button states

            # Format serial data
            serial_data = f"{y_axis:.2f} {z_axis:.2f} " + " ".join(map(str, map(int, buttons)))

            # Clean buffers and send data via serial
            if self.ser:
                self.ser.reset_input_buffer()  # Clear input buffer
                self.ser.reset_output_buffer()  # Clear output buffer
                self.ser.write(serial_data.encode('utf-8') + b'\n')
                self.get_logger().info(f"Sent to serial: {serial_data}")
            else:
                self.get_logger().warning("Serial port not initialized. Data not sent.")
        except Exception as e:
            self.get_logger().error(f"Error processing data: {e}")

def main(args=None):
    rclpy.init(args=args)
    node = JoystickSerialNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info("Exiting...")

    # Cleanup
    if node.ser:
        node.ser.close()
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
