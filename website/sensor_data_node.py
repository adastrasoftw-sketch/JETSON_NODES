import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32MultiArray
from threading import Thread, Lock

SENSOR_FORMAT = [""]
N = len(SENSOR_FORMAT) # no of sensors

class Sensor_data(Node):
    def __init__(self):
        super().__init__("sensor_reciever")
        self.sensor_data = dict()
        self.sensor_data_subscriber = self.create_subscription(Float32MultiArray, "/sensor_data", self.sensor_data_callback,10)
        self.lock = Lock()

    def sensor_data_callback(self, msg):
        # Process the sensor data
        data = msg.data
        with self.lock:
            for i in range(N):
                self.sensor_data[SENSOR_FORMAT[i]] = data[i]


def _start_thread(obj):
    rclpy.spin(obj)


def start_capturing():
    rclpy.init()
    sensor_obj = Sensor_data()
    thread = Thread(target=_start_thread, args=(sensor_obj))
    thread.start()
    return sensor_obj
