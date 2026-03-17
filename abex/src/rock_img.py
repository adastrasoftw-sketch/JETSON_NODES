def main():
    import cv2
    import time

    CAMERA_INDEX = '/dev/video5'
    SHARPNESS_THRESHOLD = 20
    FILENAME = "rock.jpg"

    cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 160)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 120)

    time.sleep(1)

    def sharpness_score(img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return cv2.Laplacian(gray, cv2.CV_64F).var()

    print("🔬 rock camera ready")
    print("Press 'c' to capture if sharp")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # ---- DO NOT MODIFY frame ----
        raw_frame = frame.copy()

        score = sharpness_score(raw_frame)
        sharp = score > SHARPNESS_THRESHOLD

        # ---- DISPLAY COPY ----
        display = cv2.resize(raw_frame, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)

        label = "SHARP" if sharp else "BLUR"
        cv2.putText(display, f"{label} | {int(score)}",
                    (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1,
                    (0,255,0) if sharp else (0,0,255), 2)

        cv2.imshow("rock View", display)

        key = cv2.waitKey(1) & 0xFF

        if key == ord('c'):
            if sharp:
                cv2.imwrite(FILENAME, raw_frame)   # ✅ clean image
                print("✅ Clean sharp image saved")
            else:
                print("❌ Blurry — refocus rock camera")

        if key == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
if __name__ == '__main__':
    main()
