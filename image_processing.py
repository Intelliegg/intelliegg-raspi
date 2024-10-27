import os
import io
import mysql.connector
from mysql.connector import Error
from ultralytics import YOLO
from PIL import Image
import numpy as np
from datetime import datetime

# Function to load the YOLO model
def load_model(model_path):
    try:
        model = YOLO(model_path)
        print(f"Model loaded successfully from {model_path}")
        return model
    except Exception as e:
        print(f"Error loading model: {str(e)}")
        return None

# Function to run prediction on the given image using the YOLO model
def predict_image(model, image):
    try:
        results = model(image)
        return results
    except Exception as e:
        print(f"Error predicting image: {str(e)}")
        return None

# Function to connect to the MySQL database
def connect_to_database():
    try:
        connection = mysql.connector.connect(
            host="192.168.0.101",  # Replace with your laptop's IP address
            user="root",
            password="",
            database="intelliegg"
        )
        print("Connected to database successfully")
        if connection.is_connected():
            print("Database connection is valid")
        return connection
    except Error as e:
        print(f"Error connecting to database: {str(e)}")
        return None

# Function to fetch unprocessed images from the database
def get_unprocessed_images(connection):
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT id, image_data, detection_Date FROM images")
        all_images = cursor.fetchall()
        print(f"Fetched {len(all_images)} images from the 'images' table")

        cursor.execute("SELECT DISTINCT image_id FROM fertility_status")
        processed_image_ids = set(row for row in cursor.fetchall())

        unprocessed_images = [img for img in all_images if img not in processed_image_ids]
        return unprocessed_images
    except Error as e:
        print(f"Error fetching unprocessed images from database: {str(e)}")
        return []
    finally:
        cursor.close()

# Function to process the image, detect eggs, and determine their positions and status
def process_image(model, image_id, image_data, detection_date):
    image = Image.open(io.BytesIO(image_data))
    results = predict_image(model, image)
    
    if results is None:
        print(f"No eggs detected in image {image_id}.")
        return []  # Return an empty list if no eggs are detected.

    egg_data = []
    img_width, img_height = image.size
    cell_width = img_width / 8  # 8 columns
    cell_height = img_height / 7  # 7 rows

    egg_grid = [[None for _ in range(8)] for _ in range(7)]

    for result in results:
        for box in result.boxes:
            xyxy = box.xyxy.tolist()
            if len(xyxy) != 4:
                print(f"Skipping box due to incorrect format: {xyxy}")
                continue

            x1, y1, x2, y2 = xyxy
            confidence = box.conf.item()
            class_id = int(box.cls)
            status = "fertile" if class_id == 0 else "infertile"

            center_x = (x1 + x2) / 2
            center_y = (y1 + y2) / 2

            col = int(center_x // cell_width)
            row = int(center_y // cell_height)

            egg_grid[row][col] = (status, confidence)

    for row in range(7):
        for col in range(8):
            if egg_grid[row][col] is not None:
                status, confidence = egg_grid[row][col]
                egg_data.append((image_id, row + 1, col + 1, status, confidence, detection_date))

    return egg_data

# Function to save the detected egg data to the database
def save_results_to_database(connection, egg_data):
    cursor = connection.cursor()
    try:
        cursor.executemany("""
            INSERT INTO fertility_status 
            (image_id, row_number, column_number, status, confidence, detection_date, incubatorNo) 
            VALUES (%s, %s, %s, %s, %s, %s, 'incubator1')
        """, egg_data)
        connection.commit()
        print(f"Saved {len(egg_data)} egg results to the database")
        print(f"Affected rows: {cursor.rowcount}")
    except Error as e:
        print(f"Error saving results to the database: {str(e)}")
    finally:
        cursor.close()

# Main function to load the model, connect to the database, and process images
def main():
    model_path = "/home/pi/aws-computer-vision-industrial-egg-fertility-sorting-system/egg_detection_yolov8n_final.pt"
    model = load_model(model_path)
    if model is None:
        return

    connection = connect_to_database()
    if connection is None:
        return

    unprocessed_images = get_unprocessed_images(connection)
    print(f"Found {len(unprocessed_images)} unprocessed images")

    for image_id, image_data, detection_date in unprocessed_images:
        egg_data = process_image(model, image_id, image_data, detection_date)
        if egg_data:
            save_results_to_database(connection, egg_data)
            print(f"Processed and saved image {image_id}")
        else:
            print(f"No eggs detected in image {image_id}")

    connection.close()

if __name__ == "__main__":
    main()
