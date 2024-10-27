import io
import logging
import socketserver
from http import server
from threading import Condition
from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder
from picamera2.outputs import FileOutput
import cv2
import threading
import traceback
import time
import base64
import requests
import numpy as np
import os
import sys

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

PAGE = """
<html>
<head>
<title>Raspberry Pi - Video Streaming</title>
</head>
<body>
<center><h1>Raspberry Pi - Video Streaming</h1></center>
<center><img src="stream.mjpg" width="640" height="480"></center>
</body>
</html>
"""

class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()

class StreamingHandler(server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(301)
            self.send_header('Location', '/index.html')
            self.end_headers()
        elif self.path == '/index.html':
            content = PAGE.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        elif self.path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            try:
                while True:
                    with output.condition:
                        output.condition.wait()
                        frame = output.frame
                        self.wfile.write(b'--FRAME\r\n')
                        self.send_header('Content-Type', 'image/jpeg')
                        self.send_header('Content-Length', len(frame))
                        self.end_headers()
                        self.wfile.write(frame)
                        self.wfile.write(b'\r\n')
            except Exception as e:
                logger.error(f"Removed streaming client {self.client_address}: {e}")
        else:
            self.send_error(404)
            self.end_headers()

class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

def initialize_camera():
    for _ in range(3):  # Try 3 times to initialize the camera
        try:
            os.system('pkill -f libcamera')  # Ensure no other libcamera processes are running
            picam2 = Picamera2()
            picam2.configure(picam2.create_video_configuration(main={"size": (640, 480)}))
            return picam2
        except Exception as e:
            logger.error(f"Failed to initialize camera: {e}")
            time.sleep(2)  # Wait before retrying
    return None

picam2 = initialize_camera()
if picam2 is None:
    logger.error("Failed to initialize camera. Exiting.")
    sys.exit(1)

output = StreamingOutput()

try:
    picam2.start_recording(JpegEncoder(), FileOutput(output))

    address = ('', 7123)
    server = StreamingServer(address, StreamingHandler)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    while True:
        with output.condition:
            output.condition.wait()
            frame = output.frame

        # Convert frame to NumPy array
        if isinstance(frame, bytes):
            frame = np.frombuffer(frame, dtype=np.uint8)
            frame = cv2.imdecode(frame, cv2.IMREAD_COLOR)

        # Save the frame to a temporary file
        temp_file = "/tmp/camera_frame.jpg"
        cv2.imwrite(temp_file, frame)

        # Read the file contents and send to the PHP script
        with open(temp_file, "rb") as f:
            image_data = f.read()
        image_b64 = base64.b64encode(image_data).decode('utf-8')

        data = {'image': image_b64}

        try:
            response = requests.post('http://192.168.0.101/Thesis-Intelliegg/webpages/fertility_check.php', json=data)
            response.raise_for_status()  # Raise an exception for HTTP errors
            print(response.text)
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")

        os.remove(temp_file)  # Remove the temporary file

        time.sleep(60)  # Check every minute

except Exception as e:
    logger.error(f"An error occurred: {e}")
    traceback.print_exc()

finally:
    if picam2:
        try:
            picam2.stop_recording()
        except Exception as e:
            logger.error(f"Error stopping camera: {e}")
    logger.info("Exiting program")
