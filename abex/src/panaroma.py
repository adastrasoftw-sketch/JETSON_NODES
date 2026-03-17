import cv2
import numpy as np
import pyzed.sl as sl
import os
from datetime import datetime
import matplotlib.pyplot as plt

import cv2
import numpy as np
import matplotlib.pyplot as plt

def crop_extra_white_background(img):
    # Convert to grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Detect non-white pixels
    # 245 is safe for near-white backgrounds
    _, thresh = cv2.threshold(gray, 245, 255, cv2.THRESH_BINARY_INV)

    # Find bounding box of actual content
    coords = cv2.findNonZero(thresh)
    x, y, w, h = cv2.boundingRect(coords)

    # Crop to content only
    cropped = img[y:y+h, x:x+w]

    return cropped

def add_scale_to_image(img):
# Load image
    img = img
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    # ================= SCALE CONFIG =================
    UNIT_VALUE_M = 0.2   # 1 unit = 0.2 m

    # Image size
    h, w, _ = img.shape

    # Scale (example)
    pixel_to_mm = 0.02  # 1 pixel = 0.02 mm

    # Create plot
    plt.figure(figsize=(18, 6))
    plt.imshow(img)

    # X and Y ticks with real-world units
    x_ticks = range(0, w, 100)
    y_ticks = range(0, h, 100)

    plt.xticks(
        x_ticks,
        [f"{int(x * pixel_to_mm)} mm" for x in x_ticks]
    )

    plt.yticks(
        y_ticks,
        [f"{int(y * pixel_to_mm)} mm" for y in y_ticks]
    )

    # ================= ADD UNIT SCALE TEXT =================
    plt.text(
        0.98, 0.98,
        f"Scale: 1 unit = {UNIT_VALUE_M} m",
        transform=plt.gca().transAxes,
        fontsize=11,
        color="white",
        ha="right",
        va="top",
        bbox=dict(facecolor="black", alpha=0.5, pad=4)
    )

    plt.savefig('pano_with_scalebar.jpg')
    
    return cv2.imread('pano_with_scalebar.jpg')


def add_info_overlay(
    img,
    latitude,
    longitude,
    elevation,
    accuracy,
    compass_path="news.png"
):
    h, w = img.shape[:2]

    # ================= PANEL CONFIG =================
    panel_w, panel_h = 360, 140
    panel_x = 20
    panel_y =h-160  # FIX: avoid going out of image

    # Copy image for transparency blending
    overlay = img.copy()
    cv2.rectangle(overlay,(panel_x,panel_y),(panel_x+panel_w,panel_y+panel_h),(0,0,0),-1)


    # FIX: Proper panel blending
    alpha = 0.6
    img = cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0)

    # ================= COMPASS =================
    # ================= COMPASS (TOP-LEFT) =================
    if os.path.exists(compass_path):
        compass = cv2.imread(compass_path, cv2.IMREAD_UNCHANGED)

        if compass is not None:
            compass_size = 150
            compass = cv2.resize(compass, (compass_size, compass_size))

            margin = 20
            cx, cy = margin, margin   # TOP-LEFT position

            # Ensure within bounds
            cx = min(cx, w - compass_size)
            cy = min(cy, h - compass_size)

            if compass.shape[2] == 4:
                alpha_c = compass[:, :, 3] / 255.0
                alpha_i = 1.0 - alpha_c

                for c in range(3):
                    img[cy:cy+compass_size, cx:cx+compass_size, c] = (
                        alpha_c * compass[:, :, c] +
                        alpha_i * img[cy:cy+compass_size, cx:cx+compass_size, c]
                    )
            else:
                img[cy:cy+compass_size, cx:cx+compass_size] = compass


    # ================= TEXT =================
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.7
    color = (255, 255, 255)   # white text
    thickness = 1

    text_x = panel_x+90
    text_y = panel_y+30
    line_gap = 24

    texts = [
        f"Latitude: {latitude}",
        f"Longitude: {longitude}",
        f"Elevation: {elevation} m",
        f"Accuracy: {accuracy}"
    ]
  

    for i, t in enumerate(texts):
        cv2.putText(
            img,
            t,
            (text_x, text_y + i * line_gap),
            font,
            font_scale,
            color,
            thickness,
            cv2.LINE_AA
        )

    return img




# -----------------------------
# Step 1: Capture images from ZED
# -----------------------------
def main():
    num_images = 3
    images = []

    zed = sl.Camera()
    init = sl.InitParameters()
    init.camera_resolution = sl.RESOLUTION.HD720
    init.camera_fps = 15
    init.depth_mode = sl.DEPTH_MODE.NONE

    status = zed.open(init)
    if status != sl.ERROR_CODE.SUCCESS:
        raise Exception(f"ZED open failed: {status}")

    runtime = sl.RuntimeParameters()
    mat = sl.Mat()

    print("---------------------------------------------------------")
    print("[INFO] ZED CAPTURE INSTRUCTIONS:")
    print("1. Rotate the ZED camera SLOWLY from Left -> Center -> Right.")
    print("2. Ensure 30-50% OVERLAP between photos.")
    print("3. Keep the camera LEVEL.")
    print("---------------------------------------------------------")

    for i in range(num_images):
        while True:
            if zed.grab(runtime) == sl.ERROR_CODE.SUCCESS:
                zed.retrieve_image(mat, sl.VIEW.LEFT)
                frame = cv2.cvtColor(mat.get_data(), cv2.COLOR_BGRA2BGR)

                display_frame = frame.copy()
                cv2.putText(
                    display_frame,
                    f"Image {i+1}/{num_images} - Press 'c' to Capture",
                    (20, 50),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 0),
                    2
                )

                h, w = display_frame.shape[:2]
                cv2.line(display_frame, (w // 3, 0), (w // 3, h), (255, 255, 0), 1)
                cv2.line(display_frame, (2 * w // 3, 0), (2 * w // 3, h), (255, 255, 0), 1)

                cv2.imshow("ZED Capture Window", display_frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('c'):
                images.append(frame.copy())
                print(f"[OK] Captured Image {i+1}")
                break
            elif key == ord('q'):
                zed.close()
                cv2.destroyAllWindows()
                exit()

    cv2.destroyAllWindows()

    # -----------------------------
    # Step 2: Stitching (OpenCV)
    # -----------------------------
    print("[INFO] Stitching images... (This may take a moment)")
    stitcher = cv2.Stitcher_create(cv2.Stitcher_PANORAMA)
    status, pano_raw = stitcher.stitch(images)

    if status != cv2.Stitcher_OK:
        print(f"[ERROR] Stitching failed with error code: {status}")
        zed.close()
        exit()

    # -----------------------------
    # Step 3: Expand Edges (Inpainting)
    # -----------------------------
    print("[INFO] Expanding edges using inpainting...")

    gray = cv2.cvtColor(pano_raw, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 5, 255, cv2.THRESH_BINARY)
    mask = cv2.bitwise_not(thresh)

    kernel = np.ones((5, 5), np.uint8)
    mask_dilated = cv2.dilate(mask, kernel, iterations=2)

    try:
        pano_final = cv2.inpaint(pano_raw, mask_dilated, 3, cv2.INPAINT_TELEA)
    except Exception as e:
        print(f"[WARN] Inpainting failed: {e}")
        pano_final = pano_raw
    latitude=int(input("enter lat:")),
    longitude=int(input("long:")),
    accuracy=int(input("accu:")),
    elevation=int(input("ele:"))
    pano_final=add_info_overlay(
        pano_final,
        latitude,
        longitude,
        accuracy,
        elevation
    )




    #cv2.imshow("Final ZED Panorama (Expanded Edges)", pano_show)
    x=add_scale_to_image(pano_final)
    x=crop_extra_white_background(x)

    #cv2.imshow("Final ZED Panorama with Scale", pano_final)
    cv2.imshow("fdd",x)
    cv2.imwrite("final_pano.png",x)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

    zed.close()

if __name__=="__main__":
    main()