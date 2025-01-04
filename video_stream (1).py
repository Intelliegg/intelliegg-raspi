import cv2
from picamera2 import Picamera2
import subprocess
import time
import signal
import sys
import io
import base64
import requests
import threading
from datetime import datetime, timedelta
import os

RTMP_URL = "rtmp://a.rtmp.youtube.com/live2"
STREAM_KEY = "79p6-8hqp-whhs-tmuk-cv2w"

def initialize_camera():
    retries = 5
    delay = 2  # seconds between retries
    for i in range(retries):
        try:
            picam2 = Picamera2()
            picam2.preview_configuration.main.size = (640, 360)
            picam2.preview_configuration.main.format = 'RGB888'
            picam2.configure("preview")
            picam2.start()
            time.sleep(2)  # Warm-up time
            return picam2
        except Exception as e:
            print(f"Attempt {i + 1} failed: {e}")
            time.sleep(delay)
    raise RuntimeError("Failed to initialize camera after multiple retries")

picam2 = initialize_camera()

def start_ffmpeg():
    ffmpeg_cmd = [
        'ffmpeg',
        '-re',
        '-ar', '44100', '-ac', '2', '-f', 's16le', '-i', '/dev/zero',
        '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', '640x360', '-r', '30', '-i', '-',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency', '-b:v', '1000k', '-bufsize', '64k',
        '-g', '15',
        '-c:a', 'aac', '-b:a', '64k', '-f', 'flv', f'{RTMP_URL}/{STREAM_KEY}'
    ]
    return subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)

ffmpeg_process = start_ffmpeg()

def cleanup():
    print('Cleaning up...')
    if picam2:
        picam2.stop()
    if ffmpeg_process:
        ffmpeg_process.stdin.close()
        ffmpeg_process.terminate()
        ffmpeg_process.wait()
    cv2.destroyAllWindows()
    sys.exit(0)

signal.signal(signal.SIGINT, lambda sig, frame: cleanup())
signal.signal(signal.SIGTERM, lambda sig, frame: cleanup())

def check_entry_exists():
    try:
        current_date = datetime.now().date().isoformat()
        check_data = {'detection_date': current_date}
        response = requests.post('http://intelliegg.site/webpages/check_entry.php', json=check_data)
        response.raise_for_status()
        return response.json().get('exists', False)
    except Exception as e:
        print(f"Error checking entry: {e}")
        return True

def capture_and_save_image():
    while True:
        try:
            if not check_entry_exists():
                im = picam2.capture_array()
                temp_file = "/tmp/camera_frame.jpg"
                cv2.imwrite(temp_file, im)

                with open(temp_file, "rb") as f:
                    image_data = f.read()
                image_b64 = base64.b64encode(image_data).decode('utf-8')

                data = {'image': image_b64, 'detection_date': datetime.now().isoformat()}
                response = requests.post('http://intelliegg.site/webpages/fertility_check.php', json=data)
                response.raise_for_status()
                print(response.text)

                os.remove(temp_file)
            else:
                print("Image for this date already exists.")
        except Exception as e:
            print(f"Error capturing and saving image: {e}")

        time.sleep((24 * 60 * 60) - (datetime.now().second + datetime.now().minute * 60 + datetime.now().hour * 3600))

image_capture_thread = threading.Thread(target=capture_and_save_image)
image_capture_thread.daemon = True
image_capture_thread.start()

try:
    while True:
        im = picam2.capture_array()
        ffmpeg_process.stdin.write(im.tobytes())
        if cv2.waitKey(1) == ord('q'):
            break
except Exception as e:
    print(f"Error in main loop: {e}")
finally:
    cleanup()
