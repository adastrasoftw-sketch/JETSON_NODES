#python3 - <<EOF
import pyzed.sl as sl
zed = sl.Camera()
status = zed.open(sl.InitParameters())
print(status)
zed.close()
#EOF
