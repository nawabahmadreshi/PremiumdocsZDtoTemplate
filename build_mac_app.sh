#!/bin/bash
# Builds the standalone macOS application bundle for Aquera Hub

echo "Cleaning previous builds..."
rm -rf build dist

echo "Building PyInstaller bundle..."
./venv/bin/pyinstaller --name "Aquera Hub" \
    --windowed \
    --noconfirm \
    --add-data "app/static:app/static" \
    --add-data ".env:." \
    --add-data "venv/lib/python3.12/site-packages/playwright/driver:playwright/driver" \
    --hidden-import="playwright" \
    --hidden-import="bs4" \
    --hidden-import="pikepdf" \
    --hidden-import="requests" \
    main.py

echo "Build complete! Check the 'dist' folder for 'Aquera Hub.app'."
