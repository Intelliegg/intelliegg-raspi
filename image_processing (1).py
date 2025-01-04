import os
import io
import base64
import requests
from PIL import Image
import numpy as np
import cv2
import supervision as sv
import json
from datetime import datetime
from roboflow import Roboflow

# Function to connect to the Roboflow API and load the model
def load_roboflow_model(api_key, project_id, model_version):
    try:
        rf = Roboflow(api_key=api_key)
        project = rf.workspace().project(project_id)
        model = project.version(model_version).model
        print(f"Roboflow model loaded successfully from project {project_id} version {model_version}")
        return model
    except Exception as e:
        print(f"Error loading Roboflow model: {str(e)}")
        return None

# Function to fetch unprocessed images from the PHP script
def get_unprocessed_images(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        response_data = response.json()
        
        if response_data.get("success"):
            print(response_data.get("message"))
            unprocessed_images = response_data.get("data", [])
            print(f"Fetched {len(unprocessed_images)} unprocessed images")
            return unprocessed_images
        else:
            print(f"Error fetching unprocessed images: {response_data.get('message')}")
            return []
    except requests.exceptions.RequestException as e:
        print(f"Error fetching unprocessed images: {str(e)}")
        return []
    except ValueError as e:
        print(f"Error parsing JSON response: {str(e)}")
        return []

# Function to process the image, detect eggs, and determine their positions and status
def process_image(model, image_id, image_data, detection_date):
    try:
        # Decode base64 image data
        image_data = base64.b64decode(image_data)
        image = Image.open(io.BytesIO(image_data)).convert("RGB")
        print(f"Image {image_id} opened successfully")
    except Exception as e:
        print(f"Error opening image {image_id}: {str(e)}")
        return None, None

    # Convert PIL image to OpenCV format
    image_np = np.array(image)
    image_cv2 = cv2.cvtColor(image_np, cv2.COLOR_RGB2BGR)

    # Run prediction using the Roboflow model
    result = model.predict(image_cv2, confidence=40, overlap=30).json()
    print("Raw predictions:", result['predictions'])  # Debug: Print raw predictions

    if not result['predictions']:
        print(f"No eggs detected in image {image_id}.")
        return None, None

    # Extract bounding box coordinates, confidence scores, and class labels
    xyxy = []
    confidence = []
    class_id = []
    labels = []
    for prediction in result['predictions']:
        x1 = int(prediction['x'] - prediction['width'] / 2)
        y1 = int(prediction['y'] - prediction['height'] / 2)
        x2 = int(prediction['x'] + prediction['width'] / 2)
        y2 = int(prediction['y'] + prediction['height'] / 2)
        xyxy.append([x1, y1, x2, y2])
        confidence.append(prediction['confidence'])
        class_id.append(0 if prediction['class'] == 'FER' else 1)  # 0 for FER, 1 for INF
        labels.append(f"{prediction['class'].capitalize()} {prediction['confidence']:.2f}")

    # Debug: Print number of predictions
    print(f"Number of predictions: {len(result['predictions'])}")

    # Create Detections object
    detections = sv.Detections(
        xyxy=np.array(xyxy),
        confidence=np.array(confidence),
        class_id=np.array(class_id)
    )

    # Debug: Print number of detections
    print(f"Number of detections: {len(detections.xyxy)}")

    # Annotate the image with bounding boxes and labels
    label_annotator = sv.LabelAnnotator()
    bounding_box_annotator = sv.BoxAnnotator()

    # Step 1: Draw bounding boxes
    annotated_image = bounding_box_annotator.annotate(scene=image_cv2, detections=detections)

    # Step 2: Add labels
    annotated_image = label_annotator.annotate(scene=annotated_image, detections=detections, labels=labels)

    # Convert annotated image back to PIL format
    annotated_image_pil = Image.fromarray(cv2.cvtColor(annotated_image, cv2.COLOR_BGR2RGB))

    # Save the annotated image
    annotated_image_path = f"annotated_image_{image_id}.jpg"
    annotated_image_pil.save(annotated_image_path)
    print(f"Annotated image saved to {annotated_image_path}")

    # Convert annotated image to base64
    buffered = io.BytesIO()
    annotated_image_pil.save(buffered, format="JPEG")
    annotated_image_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

    return annotated_image_base64, detection_date

# Function to save results to the database using a PHP API
def save_results_to_php(url, annotated_image_base64, detection_date):
    try:
        data = {
            "annotated_image": annotated_image_base64,
            "detection_date": detection_date  # Include detection_date in the data
        }

        headers = {'Content-Type': 'application/json'}
        response = requests.post(url, data=json.dumps(data), headers=headers)
        print("PHP response content:", response.text)  # Print the raw response from PHP for debugging
        response.raise_for_status()
        response_data = response.json()
        
        if response_data.get("success"):
            print(response_data.get("message"))
        else:
            print(f"Error saving results to the database: {response_data.get('message')}")
    except requests.exceptions.RequestException as e:
        print(f"Error saving results to the database: {str(e)}")
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON response: {str(e)} - Response content: {response.text}")

# Main function
def main():
    api_key = "sUBuYLtrPqMORwt1CjMQ"  # Replace with your Roboflow API key
    project_id = "egg-candling-v1.0"  # Replace with your Roboflow project ID
    model_version = 1  # Replace with your model version

    # Load the Roboflow model
    model = load_roboflow_model(api_key, project_id, model_version)
    if model is None:
        return

    # URLs for fetching and saving data
    fetch_url = "http://intelliegg.site/webpages/fetch_data.php"
    insert_url = "http://intelliegg.site/webpages/insert_data.php"

    # Fetch unprocessed images
    unprocessed_images = get_unprocessed_images(fetch_url)
    print(f"Found {len(unprocessed_images)} unprocessed images")

    # Process each image
    for image in unprocessed_images:
        image_id = image['id']
        image_data = image['image_data']
        detection_date = image['detection_Date']

        # Process the image and annotate it
        annotated_image_base64, detection_date = process_image(model, image_id, image_data, detection_date)
        if annotated_image_base64:
            # Save the results to the database
            save_results_to_php(insert_url, annotated_image_base64, detection_date)
            print(f"Processed and saved image {image_id}")
        else:
            print(f"No eggs detected in image {image_id}")

if __name__ == "__main__":
    main()
