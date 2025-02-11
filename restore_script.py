#!/usr/bin/env python3

# python manage.py flush --no-input
# python manage.py migrate --no-input
# python manage.py loaddata backups/backup_20250211_1701.json


import os
import sys
import subprocess

BACKUP_DIR = "backups"

def restore_from_backup(backup_file: str):
    """
    1) DB를 flush --no-input
    2) DB migrate (기본 테이블 재생성)
    3) loaddata로 백업 복원
    """
    try:
        # 1) 전체 데이터 삭제
        flush_command = "python manage.py flush --no-input"
        print(f"Running flush: {flush_command}")
        subprocess.run(flush_command, shell=True, check=True)

        # 2) 마이그레이션
        migrate_command = "python manage.py migrate --no-input"
        print(f"Running migrate: {migrate_command}")
        subprocess.run(migrate_command, shell=True, check=True)

        # 3) 백업 데이터 로드
        loaddata_command = f"python manage.py loaddata {backup_file}"
        print(f"Loading backup file: {loaddata_command}")
        subprocess.run(loaddata_command, shell=True, check=True)

        print(f"Restore complete from '{backup_file}'")

    except subprocess.CalledProcessError as e:
        print(f"[Error] Restore failed: {e}")
        sys.exit(1)

def main():
    if not os.path.exists(BACKUP_DIR):
        print(f"[Error] Backup directory '{BACKUP_DIR}' not found.")
        sys.exit(1)

    backup_files = sorted(os.listdir(BACKUP_DIR))
    if not backup_files:
        print("[Error] No backup files found.")
        sys.exit(1)

    print("=== Available Backup Files ===")
    for i, f in enumerate(backup_files):
        print(f"{i}. {f}")
    print("=============================")

    user_input = input(
        "Select which backup file to restore (index) or press Enter for latest: "
    ).strip()

    if user_input == "":
        selected_file = backup_files[-1]
    else:
        try:
            index = int(user_input)
            selected_file = backup_files[index]
        except:
            print("[Error] Invalid input.")
            sys.exit(1)

    confirm = input(f"Are you sure you want to restore from '{selected_file}'? (y/N): ").lower()
    if confirm != "y":
        print("Restore canceled.")
        sys.exit(0)

    backup_file_path = os.path.join(BACKUP_DIR, selected_file)
    restore_from_backup(backup_file_path)

if __name__ == "__main__":
    main()
