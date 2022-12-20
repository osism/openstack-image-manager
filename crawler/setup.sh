#!/usr/bin/env bash
set -e
echo "OpenStack Image Crawler for lazy DevOps v0.1"
echo
echo "Installing required packages"
sudo apt install git python3-pip python3-venv -y
echo "Creating venv under .oic"
python3 -m venv .oic
source .oic/bin/activate
echo "Installing required python packages"
pip install --upgrade pip wheel
pip install -r requirements.txt
echo
echo "Initializing image catalog database"
./image-crawler.py --init-db
echo
echo "Ready for operation."
echo
echo "Activate the venv before running the crawler:"
echo
echo "source .oic/bin/activate"
echo "./image-crawler.py"
