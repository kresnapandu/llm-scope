"""
Hallucination judge service for llm-scope.
Scores LLM completions for faithfulness to retrieved context using
a 3-step pipeline: deterministic → semantic similarity → LLM-as-judge.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


# ──────────────────────────────────────────────────────────────────────────────
# Request/Response models
# ──────────────────────────────────────────────────────────────────────────────


class JudgeRequest(BaseModel):
    context: str
    completion: str
    span_id: str


class JudgeResponse(BaseModel):
    score: float
    reasoning: str
    span_id: str
    method: str


class BatchJudgeRequest(BaseModel):
    items: List[JudgeRequest]


class BatchJudgeResponse(BaseModel):
    results: List[JudgeResponse]


# ──────────────────────────────────────────────────────────────────────────────
# Scoring logic
# ──────────────────────────────────────────────────────────────────────────────


def _deterministic_check(context: str, completion: str) -> Optional[float]:
    """
    Step 1: Fast deterministic checks (free, no API call).

    Returns a score [0.0–1.0] if a definitive verdict is possible, else None.
    - Returns 0.0 if completion is too short to score.
    - Returns 0.9 if completion contains many keywords NOT in context (likely hallucinated).
    - Returns None if inconclusive (proceed to semantic check).
    """
    if len(completion.strip()) < 20:
        return 0.0  # Too short to be meaningful

    # Tokenize into word sets
    context_words = set(context.lower().split())
    completion_words = set(completion.lower().split())

    # Stop words to ignore
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "has", "have", "had", "do", "does", "did", "will", "would",
        "can", "could", "should", "may", "might", "to", "of", "in",
        "on", "at", "for", "with", "by", "from", "that", "this",
        "it", "its", "and", "or", "but", "not", "no", "i", "you",
        "he", "she", "they", "we", "my", "your", "his", "her",
    }

    meaningful_completion = completion_words - stop_words
    if not meaningful_completion:
        return None

    # Words in completion that are not in context (potential hallucinations)
    out_of_context = meaningful_completion - context_words - stop_words
    hallucination_ratio = len(out_of_context) / max(len(meaningful_completion), 1)

    # Very high overlap → likely faithful
    if hallucination_ratio < 0.2:
        return 0.1
    # Very low overlap → likely hallucinated
    if hallucination_ratio > 0.8:
        return 0.85

    return None  # Inconclusive


def _semantic_similarity(context: str, completion: str) -> Optional[float]:
    """
    Step 2: TF-IDF + cosine similarity (no GPU, no API).

    Returns a hallucination score: 1.0 - cosine_similarity.
    Low similarity → high hallucination score.
    """
    try:
        import math
        from collections import Counter

        def tf_idf_vector(text: str, vocabulary: set) -> Dict[str, float]:
            words = text.lower().split()
            tf = Counter(words)
            total = len(words) or 1
            return {w: tf[w] / total for w in vocabulary if tf[w] > 0}

        vocabulary = set(context.lower().split()) | set(completion.lower().split())
        ctx_vec = tf_idf_vector(context, vocabulary)
        comp_vec = tf_idf_vector(completion, vocabulary)

        # Cosine similarity
        dot = sum(ctx_vec.get(w, 0) * comp_vec.get(w, 0) for w in vocabulary)
        ctx_mag = math.sqrt(sum(v ** 2 for v in ctx_vec.values())) or 1e-9
        comp_mag = math.sqrt(sum(v ** 2 for v in comp_vec.values())) or 1e-9

        cosine_sim = dot / (ctx_mag * comp_mag)
        # Higher similarity = lower hallucination
        return max(0.0, min(1.0, 1.0 - cosine_sim))

    except Exception as e:
        logger.warning(f"Semantic similarity failed: {e}")
        return None


async def _llm_judge(context: str, completion: str) -> Optional[tuple[float, str]]:
    """
    Step 3: LLM-as-judge via OpenAI API.

    Returns (score, reasoning) or None if API is unavailable.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    judge_model = os.getenv("JUDGE_MODEL", "gpt-4o-mini")

    if not api_key:
        return None

    prompt = (
        "You are a faithfulness evaluator. Given a CONTEXT and a COMPLETION, "
        "determine if the completion is faithful to the context.\n\n"
        f"CONTEXT:\n{context[:3000]}\n\n"
        f"COMPLETION:\n{completion[:1000]}\n\n"
        "Reply with exactly one word: FAITHFUL or UNFAITHFUL, then a newline, "
        "then a one-sentence explanation."
    )

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": judge_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 100,
                    "temperature": 0.0,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()

        lines = content.split("\n", 1)
        verdict = lines[0].strip().upper()
        reasoning = lines[1].strip() if len(lines) > 1 else content

        if "UNFAITHFUL" in verdict:
            return 0.85, reasoning
        elif "FAITHFUL" in verdict:
            return 0.1, reasoning
        else:
            return 0.5, f"Ambiguous verdict: {content}"

    except Exception as e:
        logger.warning(f"LLM judge API call failed: {e}")
        return None


async def score_faithfulness(context: str, completion: str) -> tuple[float, str, str]:
    """
    Run the 3-step hallucination scoring pipeline.

    Returns:
        (score, reasoning, method) where method is "deterministic", "semantic", or "llm".
    """
    # Step 1: Deterministic
    score = _deterministic_check(context, completion)
    if score is not None:
        reasoning = (
            "Completion is too short to evaluate."
            if score == 0.0
            else f"Deterministic keyword overlap analysis: score={score:.2f}"
        )
        return score, reasoning, "deterministic"

    # Step 2: Semantic similarity
    score = _semantic_similarity(context, completion)
    if score is not None:
        # Only use semantic result if conclusive (very high or very low)
        if score < 0.2 or score > 0.7:
            return score, f"TF-IDF cosine similarity analysis: hallucination_score={score:.3f}", "semantic"

    # Step 3: LLM-as-judge
    result = await _llm_judge(context, completion)
    if result is not None:
        llm_score, reasoning = result
        return llm_score, reasoning, "llm"

    # Fallback: use semantic score even if inconclusive
    if score is not None:
        return score, f"TF-IDF cosine similarity (fallback): score={score:.3f}", "semantic"

    return 0.5, "Unable to score — no API key and inconclusive heuristics", "deterministic"


# ──────────────────────────────────────────────────────────────────────────────
# API endpoints
# ──────────────────────────────────────────────────────────────────────────────


@router.post("/judge", response_model=JudgeResponse, tags=["judge"])
async def judge_single(body: JudgeRequest) -> JudgeResponse:
    """
    Score a single completion for faithfulness to context.

    Score interpretation:
    - 0.0–0.2: Likely faithful
    - 0.2–0.5: Uncertain
    - 0.5–1.0: Likely hallucinated
    """
    score, reasoning, method = await score_faithfulness(body.context, body.completion)
    return JudgeResponse(
        score=round(score, 4),
        reasoning=reasoning,
        span_id=body.span_id,
        method=method,
    )


@router.post("/judge/batch", response_model=BatchJudgeResponse, tags=["judge"])
async def judge_batch(body: BatchJudgeRequest) -> BatchJudgeResponse:
    """
    Score multiple completions in a single request.
    """
    import asyncio

    async def score_one(item: JudgeRequest) -> JudgeResponse:
        score, reasoning, method = await score_faithfulness(item.context, item.completion)
        return JudgeResponse(
            score=round(score, 4),
            reasoning=reasoning,
            span_id=item.span_id,
            method=method,
        )

    results = await asyncio.gather(*[score_one(item) for item in body.items])
    return BatchJudgeResponse(results=list(results))
