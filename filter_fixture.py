#!/usr/bin/env python3
import json
import sys

"""
사용법:
  python filter_fixture.py <input_fixture.json> <output_fixture.json>

이 스크립트는 백업 파일(<input_fixture.json>) 안에서
model == 'contenttypes.contenttype' (또는 원치 않는 모델)을 제거하고,
결과를 <output_fixture.json>으로 저장합니다.
"""

UNWANTED_MODELS = [
    "contenttypes.contenttype",
    "auth.permission",
    # 만약 auth.permission도 빼야 한다면 여기에 "auth.permission" 추가
]

def main():
    if len(sys.argv) < 3:
        print("Usage: python filter_fixture.py <input_fixture.json> <output_fixture.json>")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]

    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # data는 [{"model": "...", "pk":..., "fields": {...}}, ...] 형태 리스트
    filtered = []
    removed_count = 0
    for obj in data:
        if obj["model"] in UNWANTED_MODELS:
            removed_count += 1
        else:
            filtered.append(obj)

    print(f"Original objects: {len(data)}")
    print(f"Removed objects: {removed_count}")
    print(f"Remaining objects: {len(filtered)}")

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(filtered, f, indent=4, ensure_ascii=False)

    print(f"Filtered fixture saved to: {output_file}")


if __name__ == "__main__":
    main()
