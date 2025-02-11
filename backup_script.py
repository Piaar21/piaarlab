#!/usr/bin/env python3
import os
import datetime
import subprocess
import sys

# 현재 스크립트의 절대 경로
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# backups 폴더 (BASE_DIR/backups)
BACKUP_DIR = os.path.join(BASE_DIR, "backups")

# 최대 백업 파일 보관 개수
MAX_BACKUPS = 168

def main():
    # 1) backups 폴더 없으면 생성
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)

    # 2) 백업 파일명 (backup_YYYYMMDD_HHMM.json)
    now = datetime.datetime.now()
    filename = now.strftime("backup_%Y%m%d_%H%M.json")
    file_path = os.path.join(BACKUP_DIR, filename)

    # 3) dumpdata 실행 (contenttypes, auth.Permission, admin.logentry, sessions.session 제외)
    #    - sys.executable: 현재 파이썬(venv)을 그대로 사용
    command = [
        sys.executable,
        "manage.py", "dumpdata",
        "--exclude", "contenttypes",
        "--exclude", "auth.Permission",
        "--exclude", "admin.logentry",
        "--exclude", "sessions.session",
        "--indent", "4",
    ]
    
    # 표준출력(stdout)을 바로 file_path에 기록
    with open(file_path, "w", encoding="utf-8") as f:
        subprocess.run(command, check=True, stdout=f)

    # 4) 백업 파일 정리 (오래된 것 삭제)
    backup_files = sorted(os.listdir(BACKUP_DIR))
    if len(backup_files) > MAX_BACKUPS:
        num_to_delete = len(backup_files) - MAX_BACKUPS
        for i in range(num_to_delete):
            os.remove(os.path.join(BACKUP_DIR, backup_files[i]))

    print(f"Backup complete: {file_path}")

if __name__ == "__main__":
    main()
