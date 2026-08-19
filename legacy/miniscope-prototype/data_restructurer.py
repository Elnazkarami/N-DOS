import os
import shutil

class DataRestructurer:
    def __init__(self):
        pass

    def restructure_data(self, data, file_path, output_dir):
        """
        Restructures the extracted data into the specified directory structure.
        """
        file_name = os.path.basename(file_path)

        # Extract session information from the file path
        parts = file_path.split("/")
        if len(parts) >= 4:
            session_date = parts[-4]
            subject_id = parts[-3]
            session_id = parts[-2]
        else:
            print(f"Could not extract session information from file path: {file_path}")
            return False

        # Define directory structure
        raw_data_dir = os.path.join(output_dir, "raw_data", session_date, subject_id, session_id, "raw")

        # Create the raw data directory if it doesn't exist
        if not os.path.exists(raw_data_dir):
            try:
                os.makedirs(raw_data_dir, exist_ok=True)
            except OSError as e:
                print(f"Could not create directory {raw_data_dir}: {e}")
                return False

        # Move the file to the raw data directory
        dest_path = os.path.join(raw_data_dir, file_name)
        if os.path.exists(dest_path):
            print(f"Destination path '{dest_path}' already exists. Skipping move.")
            return True

        try:
            shutil.move(file_path, dest_path)
            print(f"Moved {file_path} to {dest_path}")
        except OSError as e:
            print(f"Could not move file {file_path} to {dest_path}: {e}")
            return False

        return True
