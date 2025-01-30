# rag_search.py

import openai
import faiss
import json
import numpy as np
import sys
from decouple import config
from django.conf import settings
import os

openai.api_key = config("OPENAI_API_KEY", default=None)

# 1) load faiss
# 1) 글로벌 로드: qa.index, metadata
BASE_DIR = settings.BASE_DIR
index_path = os.path.join(BASE_DIR, "qa.index")
meta_path  = os.path.join(BASE_DIR, "qa_metadata.json")

index = faiss.read_index(index_path)
with open(meta_path, "r", encoding="utf-8") as f:
    metadata = json.load(f)

def embed_text(text):
    resp = openai.Embedding.create(
        model="text-embedding-ada-002",
        input=text
    )
    return resp["data"][0]["embedding"]

def search_similar(query_text, top_k=3):
    vec = embed_text(query_text)
    xq = np.array([vec], dtype='float32')
    D, I = index.search(xq, top_k)
    results = []
    for rank in range(top_k):
        idx = I[0][rank]
        dist = D[0][rank]
        item = metadata[idx]  # {question, answer, ...}
        results.append({
            "rank": rank+1,
            "distance": float(dist),
            "question": item["question"],
            "answer": item["answer"]
        })
    return results

def build_prompt(sim_docs, user_question):
    """
    sim_docs: list of {question, answer, distance}
    """
    doc_strings = []
    for i, doc in enumerate(sim_docs, start=1):
        q = doc["question"]
        a = doc["answer"]
        doc_strings.append(f"({i}) Q: {q}\n    A: {a}")
    docs_str = "\n".join(doc_strings)

    prompt = f"""
    다음은 과거 유사 문의와 답변입니다:
    {docs_str}

    주의: 질문(Q)만 참고하여 요약을 작성, 답변(A)의 내용은 요약에 포함하지 말 것

    현재 문의: {user_question}

    [신규 문의 요약]
    [추천답변1] 
    [추천답변2]
    """
    return prompt

def generate_gpt_answer(user_question, top_k=3):
    # 1) RAG 검색
    sim_docs = search_similar(user_question, top_k)
    # 2) Prompt 구성
    content = build_prompt(sim_docs, user_question)
    # 3) ChatCompletion
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role":"system", "content":"당신은 고객문의에 대한 전문 CS담당자입니다."},
            {"role":"user", "content": content}
        ],
        max_tokens=512,
        temperature=0.2
    )
    text = response["choices"][0]["message"]["content"].strip()

    # 예: GPT 응답 예시
    # [요약]
    # 문의요약문장
    #
    # [추천답변1]
    # ...
    #
    # [추천답변2]
    # ...
    summary = ""
    rec1 = ""
    rec2 = ""

    # 간단한 파싱 예시(실무엔 더 안전하게 처리)
    parts = text.split("[추천답변1]")
    if len(parts) == 2:
        # left = [요약]\n요약내용
        # right = [추천답변2] ...
        left = parts[0].replace("[요약]", "").strip()
        summary = left  # or parse lines
        right = parts[1]
        # now split by [추천답변2]
        parts2 = right.split("[추천답변2]")
        rec1 = parts2[0].strip()  # 추천답변1 부분
        if len(parts2) > 1:
            rec2 = parts2[1].strip()
    else:
        # GPT 응답이 예상 형식 아님
        summary = text
        rec1 = "(형식 오류)"
        rec2 = "(형식 오류)"

    return summary, rec1, rec2