import zipfile
import shutil
import tempfile
import re
import io
import json
import base64
import requests
import pandas as pd
from typing import Union, List, Dict, Any
from collections import defaultdict
from datetime import datetime, timedelta
from tqdm import tqdm
from urllib.parse import urlparse, parse_qs, urlunparse, urljoin
import tarfile
import gzip
import bz2
import os
import py7zr

class CompressionHandler:
    def __init__(self):
        pass

    def extract_file(self, file_path, extract_path):
        """
        Extracts a compressed file to the specified directory.
        """
        try:
            if file_path.endswith(".zip"):
                with zipfile.ZipFile(file_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_path)
            elif file_path.endswith(".tar.gz") or file_path.endswith(".tgz"):
                with tarfile.open(file_path, 'r:gz') as tar_ref:
                    tar_ref.extractall(extract_path)
            elif file_path.endswith(".tar.bz2"):
                with tarfile.open(file_path, 'r:bz2') as tar_ref:
                    tar_ref.extractall(extract_path)
            elif file_path.endswith(".7z"):
                try:
                    with py7zr.SevenZipFile(file_path, mode='r') as archive:
                        archive.extractall(path=extract_path)
                except Exception as e:
                    print(f"Error extracting 7z file: {e}")
            else:
                print(f"Unsupported compression format: {file_path}")
                return False
            return True
        except Exception as e:
            print(f"Error extracting file: {file_path} - {e}")
            return False

    def is_compressed(self, file_path):
        """
        Checks if a file is a supported compressed file.
        """
        return file_path.endswith((".zip", ".tar.gz", ".tgz", ".tar.bz2", ".7z"))
