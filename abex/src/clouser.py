def main():
    #!/usr/bin/env python3

    import cv2
    import numpy as np
    import os
    from datetime import datetime
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

        plt.savefig('closure_with_scalebar.jpg')
        
        return cv2.imread('closure_with_scalebar.jpg')



    # ================= CONFIG =================
    CAMERA_INDEX = "/dev/video1"
    BLUR_THRESHOLD = 80.0


    # ================= FUNCTIONS =================
    def compute_blur(img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return cv2.Laplacian(gray, cv2.CV_64F).var()

    # ================= MAIN =================

    cap = cv2.VideoCapture(CAMERA_INDEX)

    if not cap.isOpened():
        print("[ERROR] Camera not opened")

    print("[INFO] Close-up Capture Started")
    print("[INFO] Press 'c' to capture | 'q' to quit")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        blur_score = compute_blur(frame)

        display = frame.copy()

        # Status logic
        status = "SHARP" if blur_score >= BLUR_THRESHOLD else "BLURRED"
        color = (0, 255, 0) if status == "SHARP" else (0, 0, 255)

        # UI overlay
        cv2.putText(
            display,
            f"Blur Score: {blur_score:.1f}",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            color,
            2
        )

        cv2.putText(
            display,
            status,
            (20, 80),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            color,
            2
        )

        cv2.putText(
            display,
            "Press 'c' to capture | 'q' to exit",
            (20, display.shape[0] - 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            1
        )

        cv2.imshow("Close-up Capture", display)

        key = cv2.waitKey(1) & 0xFF

        # -------- Capture logic --------
        if key == ord('c'):
            if blur_score < BLUR_THRESHOLD:
                print("[WARN] Image rejected (blurred)")
            else:
                #timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")c
                cv2.imwrite("closure.jpg", frame)
                print("[OK] Sharp image saved")

        elif key == ord('q'):
            break
    x=cv2.imread("closure.jpg")
    x=add_scale_to_image(x)
    x=crop_extra_white_background(x)
    cv2.imwrite("final_closure.jpg", x)
    cv2.destroyAllWindows()
    cap.release()
    print("[INFO] Program exited cleanly")



if __name__=="__main__":
    main()