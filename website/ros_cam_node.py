import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
import numpy as np
from threading import Thread, Lock

class ImageGetter(Node):

    def __init__(self):
        super().__init__("camera_receiver")
        self.left_img_sub = self.create_subscription(Image, "/zed/zed_node/left/image_rect_color", self.process_left, 10)
        self.right_img_sub = self.create_subscription(Image, "/zed/zed_node/right/image_rect_color", self.process_right, 10)
        self.camera1_img_sub = self.create_subscription(Image, "/camera1",self.process_camera1, 10)
        self.left_img = np.zeros((480,640,3))
        self.right_img = np.zeros((480,640,3))
        self.camera1_img = np.zeros((480,640,3))
        self.cv = CvBridge()
        self.lock = Lock()

    def process_left(self, ros_img):
        with self.lock:
            self.left_img = self.cv.imgmsg_to_cv2(ros_img, desired_encoding='bgr8')

    def process_right(self, ros_img):
        with self.lock:
            self.right_img = self.cv.imgmsg_to_cv2(ros_img, desired_encoding='bgr8')

    def process_camera1(self, ros_img):
        with self.lock:
            self.camera1_img = self.cv.imgmsg_to_cv2(ros_img, desired_encoding='bgr8')

def _start_thread(obj: ImageGetter):
    rclpy.spin(obj)


def start_capturing():
    rclpy.init()
    camera_obj = ImageGetter()
    thread = Thread(target=_start_thread, args=(camera_obj,))
    thread.start()
    return camera_obj
