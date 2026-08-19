#!/usr/bin/env python
import os
import sys
import argparse
from compression_handler import CompressionHandler
from data_extractor import DataExtractor
from data_restructurer import DataRestructurer
from error_handler import ErrorHandler

def main():
    parser = argparse.ArgumentParser(description="Read compressed files and restructure them.")
    parser = argparse.ArgumentParser(description="Read compressed files and restructure them.")
    parser.add_argument("target_dir", help="The directory containing the compressed files.")
    args = parser.parse_args()

    target_dir = args.target_dir

    if not os.path.isdir(target_dir):
        print(f"Error: Directory '{target_dir}' does not exist.")
        sys.exit(1)

    compression_handler = CompressionHandler()
    data_extractor = DataExtractor()
    data_restructurer = DataRestructurer()
    error_handler = ErrorHandler()

    # Find compressed files
    compressed_files = []
    for root, _, files in os.walk(target_dir):
        for file in files:
            file_path = os.path.join(root, file)
            if file_path != "/Users/Elnaz1/Documents/data from the servers /miniscope /A0600/A0634/2020_11_22.zip":
                continue
            if compression_handler.is_compressed(file_path):
                compressed_files.append(file_path)

    # Process each compressed file
    for compressed_file in compressed_files:
        print(f"Processing: {compressed_file}")
        extract_path = os.path.splitext(compressed_file)[0]  # Extract to a directory with the same name as the file
        if compression_handler.extract_file(compressed_file, extract_path):
            print(f"Extracted to: {extract_path}")

            # Find extracted files
            extracted_files = []
            for root, _, files in os.walk(extract_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    extracted_files.append(file_path)

            # Process each extracted file
            for extracted_file in extracted_files:
                data = data_extractor.extract_data(extracted_file)
                if data is None:
                    error_handler.log_error(f"Failed to extract data from {extracted_file}")
                    continue

                output_dir = os.path.join(target_dir, "output")  # Output directory
                if not data_restructurer.restructure_data(data["file_path"], extracted_file, output_dir):
                    error_handler.log_error(f"Failed to restructure data from {extracted_file}")
        else:
            error_handler.log_error(f"Failed to extract {compressed_file}")

if __name__ == "__main__":
    main()
