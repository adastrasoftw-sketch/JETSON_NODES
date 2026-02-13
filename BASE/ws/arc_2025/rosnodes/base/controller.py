'''
Usage :
    Recive the data from the joystick and publish the velocity and buttons

topics :
    /joystick_buttons       : publish
    /joystick_cmd           : publish
'''

import rclpy
from rclpy.node import Node
from std_msgs.msg import String ,Float32MultiArray
from joystick import Joystick

NO_OF_BUTTONS_TO_SHARE = 8

class Controller(Node):

    def __init__(self):
        super().__init__("serial_cmd_sender")
        self.controller = Joystick()

        self.motion_cmd_publisher =  self.create_publisher(String,"joystick_motion_cmd",10)
        self.arm_cmd_publisher = self.create_publisher(Float32MultiArray,"joystick_arm_cmd",10)
        self.timer = self.create_timer(0.2,self.get_values)
    
    def get_values(self):
        motion     = self.get_motion()
        arm     = self.get_arm()
        self.motion_cmd_publisher.publish(motion)
        self.arm_cmd_publisher.publish(arm)

    def get_arm(self):
        buttons = Float32MultiArray()
        buttons.data = self.controller.axes_data+self.controller.buttons_data[:NO_OF_BUTTONS_TO_SHARE]
        #self.get_logger().info(f"{buttons.data}")
        return buttons

    def get_motion(self):
        cmd = String()
        cmd.data = self.controller.cmd
        return cmd

def main():
    rclpy.init(args=None)
    publisher = Controller()
    rclpy.spin(publisher)

if __name__ == '__main__':
    main()

