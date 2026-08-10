from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from lesson_agent.models import Resource, SearchLesson


@dataclass(frozen=True, slots=True)
class ResourceSummary:
    resource: Resource
    summary: str
    usage: str
    extractive: bool = False


class _ModelSummary(BaseModel):
    relevant: bool
    summary: str = Field(max_length=160)
    usage: str = Field(max_length=120)


class Summarizer:
    def __init__(self, client: Any | None, model: str = "gpt-5-mini") -> None:
        self.client = client
        self.model = model

    def summarize(
        self, item: SearchLesson, resources: list[Resource]
    ) -> list[ResourceSummary]:
        output: list[ResourceSummary] = []
        for resource in sorted(resources, key=lambda value: value.rank):
            if len(output) >= 5:
                break
            if self.client is None:
                summary = self._extractive(item, resource)
            else:
                summary = self._model_summary(item, resource)
            if summary is not None:
                output.append(summary)
        return output

    def summarize_recent_art(self, resources: list[Resource]) -> list[ResourceSummary]:
        return [
            ResourceSummary(
                resource=resource,
                summary=(resource.snippet.strip() or resource.title.strip())[:160],
                usage="최근 인기 미술 자료로 참고해 수업에 맞게 활용하세요.",
                extractive=True,
            )
            for resource in sorted(resources, key=lambda value: value.rank)[:3]
        ]

    def _model_summary(
        self, item: SearchLesson, resource: Resource
    ) -> ResourceSummary | None:
        try:
            response = self.client.responses.parse(
                model=self.model,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "초등 수업 자료의 관련성을 판단한다. 보이지 않는 첨부파일 내용은 "
                            "추측하지 말고, 요약 160자와 활용법 120자 이내로 한국어로 답한다."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"과목: {item.subject}\n수업 주제: {item.topic}\n"
                            f"자료 제목: {resource.title}\n보이는 설명: {resource.snippet}"
                        ),
                    },
                ],
                text_format=_ModelSummary,
            )
            parsed = response.output_parsed
            if not parsed.relevant:
                return None
            return ResourceSummary(
                resource,
                parsed.summary[:160],
                parsed.usage[:120],
                extractive=False,
            )
        except Exception:
            return self._extractive(item, resource)

    def _extractive(
        self, item: SearchLesson, resource: Resource
    ) -> ResourceSummary | None:
        topic_terms = _meaningful_terms(item.topic)
        haystack = f"{resource.title} {resource.snippet}".casefold()
        if topic_terms and not any(term in haystack for term in topic_terms):
            return None
        summary = resource.snippet.strip() or resource.title.strip()
        return ResourceSummary(
            resource=resource,
            summary=summary[:160],
            usage="원문을 확인해 수업 단계와 준비물을 결정하세요.",
            extractive=True,
        )


def _meaningful_terms(text: str) -> tuple[str, ...]:
    stopwords = {"그리고", "알아보기", "판단하기", "기능", "구조", "대한"}
    terms: list[str] = []
    for token in re.findall(r"[가-힣A-Za-z0-9]{2,}", text):
        normalized = re.sub(r"(의|을|를|이|가|은|는)$", "", token).casefold()
        if len(normalized) >= 2 and normalized not in stopwords:
            terms.append(normalized)
    return tuple(terms)
