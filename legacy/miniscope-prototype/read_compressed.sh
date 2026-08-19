#!/bin/bash

# Check if a directory is provided as an argument
if [ -z "$1" ]; then
    echo "Usage: $0 <directory>"
    exit 1
fi

TARGET_DIR="$1"

# Ensure the directory exists
if [ ! -d "$TARGET_DIR" ]; then
    echo "Error: Directory '$TARGET_DIR' does not exist."
    exit 1
fi

# Function to list the contents of a compressed file
list_contents() {
    local file="$1"
    case "$file" in
        *.zip)
            echo "Listing contents of ZIP file: $file"
            unzip -l "$file"
            ;;
        *.tar.gz | *.tgz)
            echo "Listing contents of TAR.GZ file: $file"
            tar -tzf "$file"
            ;;
        *.tar.bz2)
            echo "Listing contents of TAR.BZ2 file: $file"
            tar -tjf "$file"
            ;;
        *.7z)
            echo "Listing contents of 7Z file: $file"
            7z l "$file"
            ;;
        *)
            echo "Skipping unsupported file type: $file"
            ;;
    esac
}

# Find and process compressed files in the target directory
find "$TARGET_DIR" -type f \( -iname "*.zip" -o -iname "*.tar.gz" -o -iname "*.tgz" -o -iname "*.tar.bz2" -o -iname "*.7z" \) |
while read -r compressed_file; do
    list_contents "$compressed_file"
done

echo "Completed processing files in '$TARGET_DIR'."
