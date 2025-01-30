# cs_management/management/commands/embed_inquiries.py

import openai
from decouple import config  # or from django.conf import settings
from django.core.management.base import BaseCommand
from cs_management.models import Inquiry

# 만약 FAISS를 로컬로 쓸 경우:
import faiss
import numpy as np

class Command(BaseCommand):
    help = "Embed answered Inquiries (content/answer) into a vector store (e.g. FAISS)."

    def handle(self, *args, **options):
        # (1) API Key 설정
        openai.api_key = config('OPENAI_API_KEY', default=None)
        if not openai.api_key:
            self.stdout.write(self.style.ERROR("OPENAI_API_KEY is not set. Aborting."))
            return

        # (2) 대상 QuerySet
        qs = Inquiry.objects.filter(
            answered=True, 
            content__isnull=False, 
            answer_content__isnull=False
        ).exclude(content__exact='').exclude(answer_content__exact='')

        if not qs.exists():
            self.stdout.write("No answered inquiries with content & answer found.")
            return

        self.stdout.write(f"Found {qs.count()} answered inquiries to embed.")

        # (3) Initialize FAISS Index (예: 차원 1536 for text-embedding-ada-002)
        #     만약 Pinecone/기타 벡터DB를 쓴다면, 여기를 해당 클라이언트로 대체
        dimension = 1536
        index = faiss.IndexFlatL2(dimension)

        # 저장할 메타데이터를 파이썬 리스트로 (in real, you might want a separate DB or JSON)
        metadata_list = []

        # (4) 임베딩 함수
        def embed_text(text):
            # single text => single embedding
            resp = openai.Embedding.create(
                model="text-embedding-ada-002",
                input=text
            )
            vector = resp["data"][0]["embedding"]  # list of float
            return vector

        # (5) Loop & embed
        vectors = []
        for i, inq in enumerate(qs, start=1):
            q_text = inq.content.strip()
            # 단순히 질문만 임베딩한다고 가정
            # (원하면 "Q: ... / A: ..." 식으로 묶어서 임베딩 가능)

            embedding = embed_text(q_text)
            vectors.append(embedding)

            # Save metadata
            metadata_list.append({
                "inquiry_db_id": inq.pk,      # 실제 DB PK
                "question": inq.content,
                "answer": inq.answer_content
            })

            if i % 10 == 0:
                self.stdout.write(f"Processed {i} items...")

        # (6) Convert to numpy array
        np_vectors = np.array(vectors).astype('float32')

        # (7) Add to faiss index
        index.add(np_vectors)
        self.stdout.write(f"FAISS index size: {index.ntotal}")

        # (8) Optionally save index to disk (if we want persistent storage)
        #     - e.g. faiss.write_index(index, "inquiries.index")
        #     - plus some way to store `metadata_list` (json, etc.)
        faiss.write_index(index, "inquiries.index")

        # Save metadata as JSON as well (if needed)
        import json
        with open("inquiries_metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata_list, f, ensure_ascii=False, indent=2)

        self.stdout.write(self.style.SUCCESS("Embedding process completed!"))