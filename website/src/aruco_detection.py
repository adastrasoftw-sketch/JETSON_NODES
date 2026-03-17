import cv2
from cv2 import aruco

def detect_aruco_tags(frame):
    aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
    parameters = aruco.DetectorParameters()
    
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = aruco.detectMarkers(gray, aruco_dict, parameters=parameters)
    
    if ids is not None:
        aruco.drawDetectedMarkers(frame, corners, ids)
        detected_ids = [marker_id[0] for marker_id in ids]
        print(f"Detected ArUco marker IDs: {detected_ids}")
        return detected_ids, corners
    
    return None, None