#!/usr/bin/env python3
"""
Script to extract treatment plan names from patient directories and create a CSV file.
Scans all patient_* directories and reads _Frames.xml files to extract actual plan names.
"""

import csv
import logging
from pathlib import Path

import defusedxml.ElementTree as ET

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_plan_name_from_xml(xml_file_path):
    """
    Extract the plan name from a _Frames.xml file.

    Args:
        xml_file_path (str): Path to the _Frames.xml file

    Returns:
        str: Plan name or error message if not found
    """
    try:
        # Parse the XML file
        tree = ET.parse(xml_file_path)
        root = tree.getroot()

        # Look for Treatment/ID element
        treatment_element = root.find('Treatment')
        if treatment_element is not None:
            id_element = treatment_element.find('ID')
            if id_element is not None and id_element.text:
                plan_name = id_element.text.strip()
                logger.info(f"Found plan name '{plan_name}' in {xml_file_path}")
                return plan_name

        logger.warning(f"No Treatment/ID found in XML file: {xml_file_path}")
        return "No Treatment ID found"

    except ET.ParseError as e:
        logger.error(f"Error parsing XML file {xml_file_path}: {str(e)}")
        return "XML Parse Error"
    except Exception as e:
        logger.error(f"Error reading XML file {xml_file_path}: {str(e)}")
        return "Error Reading XML"

def scan_patient_directories(base_path):
    """
    Scan the base directory for patient directories and extract plan names from XML files.

    Args:
        base_path (str): Base directory path containing patient directories

    Returns:
        list: List of tuples (patient_dir, plan_name)
    """
    base_path = Path(base_path)
    results = []

    if not base_path.exists():
        logger.error(f"Base directory does not exist: {base_path}")
        return results

    # Find all patient directories
    patient_dirs = []
    for item in base_path.iterdir():
        if item.is_dir() and item.name.startswith('patient_'):
            patient_dirs.append(item.name)

    # Sort alphanumerically
    patient_dirs.sort()
    logger.info(f"Found {len(patient_dirs)} patient directories")

    for patient_dir in patient_dirs:
        patient_path = base_path / patient_dir
        images_path = patient_path / "IMAGES"

        logger.info(f"Processing {patient_dir}")

        if not images_path.exists():
            logger.warning(f"IMAGES directory not found for {patient_dir}")
            results.append((patient_dir, "No IMAGES directory"))
            continue

        # Find img_* directories in the IMAGES directory
        img_dirs = [item for item in images_path.iterdir() if item.is_dir() and item.name.startswith('img_')]

        if not img_dirs:
            logger.warning(f"No img_* directories found in {images_path}")
            results.append((patient_dir, "No img directories found"))
            continue

        # Process the first img directory found (assuming one plan per patient)
        img_dir = img_dirs[0]
        frames_xml_path = img_dir / "_Frames.xml"

        if not frames_xml_path.exists():
            logger.warning(f"_Frames.xml not found in {img_dir}")
            results.append((patient_dir, "No _Frames.xml found"))
            continue

        plan_name = get_plan_name_from_xml(str(frames_xml_path))
        results.append((patient_dir, plan_name))

        if len(img_dirs) > 1:
            logger.info(f"Multiple img directories found for {patient_dir}, using first one: {img_dir.name}")

    return results

def create_csv_file(results, output_file):
    """
    Create a CSV file with the results.

    Args:
        results (list): List of tuples (patient_dir, plan_name)
        output_file (str): Output CSV file path
    """
    try:
        with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['Patient_Directory', 'Plan_Name'])
            writer.writerows(results)

        logger.info(f"CSV file created successfully: {output_file}")
        print(f"CSV file created: {output_file}")
        print(f"Total records: {len(results)}")

    except Exception as e:
        logger.error(f"Error creating CSV file: {str(e)}")
        print(f"Error creating CSV file: {str(e)}")

def main():
    # Configuration
    base_directory = r"E:\XVI_COLLECTION\processed\20230403_Flinders"
    output_csv = "patient_dicom_plans.csv"

    print("Treatment Plan Extractor")
    print("=======================")
    print(f"Scanning directory: {base_directory}")
    print(f"Output file: {output_csv}")
    print()

    # Scan directories and extract plan names
    results = scan_patient_directories(base_directory)

    if not results:
        print("No patient directories or treatment plans found.")
        return

    # Create CSV file
    create_csv_file(results, output_csv)

    # Display summary
    print("\nSummary:")
    print(f"Processed {len(results)} patient directories")

    # Show first few results as preview
    print("\nFirst 5 results:")
    for i, (patient_dir, plan_name) in enumerate(results[:5]):
        print(f"  {patient_dir}: {plan_name}")

    if len(results) > 5:
        print(f"  ... and {len(results) - 5} more")

if __name__ == "__main__":
    main()
