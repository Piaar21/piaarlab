# cs_management/management/commands/embed_faiss.py

import os
import csv
import json
import openai
import faiss
import numpy as np

from decouple import config  # 또는 다른 방식으로 OPENAI_API_KEY 로딩
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    """
    Usage:
      python manage.py embed_faiss --csv=qa_data.csv --index=qa.index --meta=qa_metadata.json
    """
    help = "Read Q/A from CSV, embed with OpenAI, and store in a FAISS index + metadata."

    def add_arguments(self, parser):
        parser.add_argument('--csv', type=str, default="qa_data.csv",
            help="Path to the Q/A CSV file.")
        parser.add_argument('--index', type=str, default="qa.index",
            help="Output FAISS index file name.")
        parser.add_argument('--meta', type=str, default="qa_metadata.json",
            help="Output JSON metadata file name.")

    def handle(self, *args, **options):
        csv_path = options['csv']
        index_path = options['index']
        meta_path = options['meta']

        # 1) OPENAI_API_KEY 설정
        openai.api_key = config('OPENAI_API_KEY', default=None)
        if not openai.api_key:
            self.stdout.write(self.style.ERROR("OPENAI_API_KEY is not set. Aborting."))
            return

        # 2) CSV 로드
        if not os.path.exists(csv_path):
            self.stdout.write(self.style.ERROR(f"CSV file not found: {csv_path}"))
            return

        qa_pairs = []
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)  # e.g. ["question","answer"]
            if not header:
                self.stdout.write(self.style.ERROR("Empty CSV or no header row"))
                return

            # Assuming [0]=question, [1]=answer
            for row in reader:
                q = row[0].strip()
                a = row[1].strip()
                qa_pairs.append((q,a))

        self.stdout.write(f"Loaded {len(qa_pairs)} Q/A pairs from {csv_path}.")

        # 3) Embedding 함수
        def embed_text(text):
            resp = openai.Embedding.create(
                model="text-embedding-ada-002",
                input=text
            )
            vec = resp["data"][0]["embedding"]
            return vec

        # 4) 임베딩 수행
        vectors = []
        metadata = []
        for i, (q_text, a_text) in enumerate(qa_pairs):
            emb = embed_text(q_text)
            vectors.append(emb)
            # 메타데이터(추후 검색결과에서 A를 찾아야 하므로)
            metadata.append({
                "id": i,
                "question": q_text,
                "answer": a_text
            })
            if (i+1) % 10 == 0:
                self.stdout.write(f"Embedded {i+1} pairs...")

        self.stdout.write(f"Embedding complete. Total = {len(vectors)} pairs.")

        # 5) FAISS 인덱스 생성
        dimension = 1536  # text-embedding-ada-002
        index = faiss.IndexFlatL2(dimension)

        # numpy 변환 후 add
        np_vectors = np.array(vectors, dtype='float32')
        index.add(np_vectors)
        self.stdout.write(f"FAISS index size: {index.ntotal}")

        # 6) 인덱스 파일로 저장
        faiss.write_index(index, index_path)
        self.stdout.write(self.style.SUCCESS(f"FAISS index saved to {index_path}"))

        # 7) 메타데이터 JSON
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        self.stdout.write(self.style.SUCCESS(f"Metadata saved to {meta_path}"))

        self.stdout.write(self.style.SUCCESS("All done!"))