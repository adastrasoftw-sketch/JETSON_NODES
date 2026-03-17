import pyzed.sl as sl
import cv2

# Initialize the ZED Camera
zed = sl.Camera()

# Create configuration for the camera initialization
init_params = sl.InitParameters()
init_params.camera_resolution = sl.RESOLUTION.HD720  # Use HD720 resolution
init_params.depth_mode = sl.DEPTH_MODE.NONE          # Disable depth calculation
init_params.coordinate_units = sl.UNIT.METER         # Set unit to meters

# Open the camera
status = zed.open(init_params)
if status != sl.ERROR_CODE.SUCCESS:
    print(f"Error opening zed camera : {status}")
    exit(1)

# Create Mat objects to hold images
left_image = sl.Mat()
right_image = sl.Mat()

print("Press 'q' to quit")

try:
    while True:
        # Grab the camera frame
        if zed.grab() == sl.ERROR_CODE.SUCCESS:
            # Retrieve the left and right images
            zed.retrieve_image(left_image, sl.VIEW.LEFT)
            zed.retrieve_image(right_image, sl.VIEW.RIGHT)

            # Convert the ZED Mat to OpenCV format
            left_frame = left_image.get_data()
            right_frame = right_image.get_data()

            # Display the images
            cv2.imshow("Left Camera", left_frame)
            cv2.imshow("Right Camera", right_frame)

            # Exit on 'q' key press
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
except KeyboardInterrupt:
    print("\nProgram stopped by user.")
finally:
    # Close all OpenCV windows
    cv2.destroyAllWindows()

    # Close the ZED Camera
    zed.close()
