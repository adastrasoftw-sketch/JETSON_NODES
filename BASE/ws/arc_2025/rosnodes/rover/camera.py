import cv2 as cv
import rclpy
from rclpy.node import Node
from threading import Thread
from sensor_msgs.msg import Image
from cv_bridge import CvBridge

CAMERA_1 = "/dev/video0"

class ImagePublisher(Node):

    def __init__(self):
        super().__init__("image_publisher")
        self.cv_bridge = CvBridge()
        self.publisher = self.create_publisher(Image, "/camera1", 10)
        self.thread_obj = Thread(target=self.start)
        self.stop = False
        self.thread_obj.start()
    
    def start(self):
        cam = cv.VideoCapture(CAMERA_1)

        while not self.stop:
            ret, frame = cam.read()
            if not ret:
                pass
            msg = self.cv_bridge.cv2_to_imgmsg(frame, "bgr8")
            self.publisher.publish(msg)
        
    def stop(self):
        self.stop = True
        self.thread_obj.join()

def main():
    rclpy.init()
    node = ImagePublisher()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == "__main__":
    main()
