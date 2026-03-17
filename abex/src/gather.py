#!/usr/bin/env python3

import os
import shutil
import time

# ===== CONFIG =====
SOURCE_FOLDERS = {
    "pano": "/home/jetson/capture/panorama",
    "closure": "/home/jetson/capture/closure",
    "soil": "/home/jetson/capture/soil"
}

DEST_BASE = "/home/jetson/sites"

IMAGE_EXTS = (".jpg", ".png", ".jpeg")

os.makedirs(DEST_BASE, exist_ok=True)

print("\n=== SITE IMAGE GATHERER RUNNING ===")

while True:
    site = input("\nEnter SITE NAME (or 'exit'): ").strip()

    if site.lower() == "exit":
        print("Exiting...")
        break

    site_dir = os.path.join(DEST_BASE, site)
    os.makedirs(site_dir, exist_ok=True)

    moved = 0

    for prefix, folder in SOURCE_FOLDERS.items():
        if not os.path.exists(folder):
            print(f"[WARN] Missing folder: {folder}")
            continue

        for file in os.listdir(folder):
            if file.lower().endswith(IMAGE_EXTS):
                src = os.path.join(folder, file)
                dst = os.path.join(
                    site_dir,
                    f"{prefix}_{int(time.time()*1000)}_{file}"
                )

                try:
                    shutil.move(src, dst)
                    moved += 1
                except Exception as e:
                    print(f"[ERROR] {e}")

    print(f"[OK] {moved} images gathered into {site_dir}")
    print("[INFO] Waiting for next site...")
