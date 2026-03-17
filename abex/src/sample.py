import serial
import time

# CHANGE THESE VALUES
PORT = '/dev/ardu_cmd'        # Windows
BAUD_RATE = 9600

# Open serial connection
ser = serial.Serial(PORT, BAUD_RATE, timeout=0.1)
time.sleep(2)  # wait for Arduino reset

print("Serial connection established")

try:
    while True:
        # ---- SEND DATA ----
        data = input("Enter data to send (q to quit): ")

        if data.lower() == 'q':
            break

        ser.write((data + '\n').encode())
        print("Sent:", data)

        # ---- READ DATA (if available) ----
        time.sleep(0.1)  # small delay for Arduino response

        while ser.in_waiting > 0:
            received = ser.readline().decode(errors='ignore').strip()
            print("Arduino:", received)

except KeyboardInterrupt:
    print("\nStopped by user")

finally:
    ser.close()
    print("Serial connection closed")
