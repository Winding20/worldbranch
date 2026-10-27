"""知识库：切片、入库、检索。

第一版是"字符二元组 + 词频"的重排检索，不引入向量库：
- 中文不需要分词器，二元组足够稳；
- 数据量在几千片以内，纯 Python 打分完全够快；
- 真需要语义检索时，只需替换 ``search`` 的实现，接口不变。
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import KnowledgeChunk, KnowledgeDoc, World

CHUNK_SIZE = 320


def chunk_text(text: str, size: int = CHUNK_SIZE) -> list[str]:
    """按段落优先切分，段落过长再硬切，避免把一句话拦腰截断。"""
    text = (text or "").strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        if len(buf) + len(para) + 1 <= size:
            buf = f"{buf}\n{para}".strip() if buf else para
            continue
        if buf:
            chunks.append(buf)
        while len(para) > size:
            chunks.append(para[:size])
            para = para[size:]
        buf = para
    if buf:
        chunks.append(buf)
    return chunks


def upsert_doc(
    session: Session,
    world: World,
    *,
    slug: str,
    title: str,
    content: str,
    source: str = "",
    reliability: str = "secondary",
) -> KnowledgeDoc:
    """按 slug 幂等写入一篇资料，并重建它的切片。"""
    doc = session.scalar(
        select(KnowledgeDoc).where(
            KnowledgeDoc.world_id == world.id, KnowledgeDoc.slug == slug
        )
    )
    if doc is None:
        doc = KnowledgeDoc(world_id=world.id, slug=slug)
        session.add(doc)
    doc.title = title
    doc.content = content
    doc.source = source
    doc.reliability = reliability
    session.flush()

    for old in list(doc.chunks):
        session.delete(old)
    session.flush()

    for seq, piece in enumerate(chunk_text(content)):
        session.add(KnowledgeChunk(doc_id=doc.id, seq=seq, text=piece))
    session.flush()
    session.refresh(doc)
    return doc


def list_docs(session: Session, world_id: int) -> list[KnowledgeDoc]:
    return list(
        session.scalars(
            select(KnowledgeDoc)
            .where(KnowledgeDoc.world_id == world_id)
            .order_by(KnowledgeDoc.id)
        )
    )


def _bigrams(text: str) -> Counter:
    text = re.sub(r"\s+", "", text)
    if len(text) < 2:
        return Counter(text)
    return Counter(text[i : i + 2] for i in range(len(text) - 1))


def _score(query_grams: Counter, text: str) -> float:
    if not query_grams:
        return 0.0
    grams = _bigrams(text)
    if not grams:
        return 0.0
    hit = sum(min(count, grams.get(gram, 0)) for gram, count in query_grams.items())
    return hit / (sum(query_grams.values()) or 1)


def search(
    session: Session,
    world_id: int,
    query: str,
    *,
    limit: int = 4,
    min_score: float = 0.02,
) -> list[dict]:
    """按相关度返回最匹配的若干片段。"""
    query_grams = _bigrams(query)
    if not query_grams:
        return []

    rows = session.execute(
        select(KnowledgeChunk, KnowledgeDoc)
        .join(KnowledgeDoc, KnowledgeDoc.id == KnowledgeChunk.doc_id)
        .where(KnowledgeDoc.world_id == world_id)
    ).all()

    scored: list[dict] = []
    for chunk, doc in rows:
        score = _score(query_grams, chunk.text) + _score(query_grams, doc.title) * 0.5
        if score < min_score:
            continue
        scored.append(
            {
                "score": round(score, 4),
                "text": chunk.text,
                "doc_id": doc.id,
                "title": doc.title,
                "source": doc.source,
                "reliability": doc.reliability,
                "seq": chunk.seq,
            }
        )
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:limit]


def citations(snippets: Iterable[dict]) -> list[dict]:
    """把命中片段整理成可展示的引用列表（同一篇资料只留一条）。"""
    seen: dict[int, dict] = {}
    for s in snippets:
        if s["doc_id"] in seen:
            continue
        seen[s["doc_id"]] = {
            "title": s["title"],
            "source": s["source"],
            "reliability": s["reliability"],
        }
    return list(seen.values())