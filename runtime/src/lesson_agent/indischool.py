from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import re
from typing import Callable
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from lesson_agent.models import Resource, SearchLesson
from lesson_agent.weekly_plan import concept_action_terms, concept_context_terms, query_variants


INDISCHOOL_BASE_URL = "https://indischool.com/"
SESSION_BROWSER_ENDPOINT = "http://127.0.0.1:9222"


class IndischoolError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def session_login_error(url: str) -> IndischoolError | None:
    if "/login" in url:
        return IndischoolError("login_required", "인디스쿨 재로그인이 필요합니다.")
    return None


def choose_resources_from_queries(
    results_by_query: list[list[Resource]], limit: int
) -> list[Resource]:
    """Give every executed search query a chance before filling by displayed rank."""
    if limit <= 0:
        return []

    chosen: list[Resource] = []
    seen: set[str] = set()
    remaining: list[list[Resource]] = []
    for results in results_by_query:
        unique = [resource for resource in results if resource.url not in seen]
        if not unique:
            remaining.append([])
            continue
        chosen.append(unique[0])
        seen.add(unique[0].url)
        remaining.append(unique[1:])
        if len(chosen) >= limit:
            return chosen

    while len(chosen) < limit:
        candidates = [
            (resources[0].rank, query_index, resources[0])
            for query_index, resources in enumerate(remaining)
            if resources
        ]
        if not candidates:
            break
        _, query_index, resource = min(candidates, key=lambda candidate: candidate[:2])
        remaining[query_index].pop(0)
        if resource.url in seen:
            continue
        seen.add(resource.url)
        chosen.append(resource)
    return chosen


def filter_resources_by_title_terms(
    resources: list[Resource], required_terms: tuple[str, ...]
) -> list[Resource]:
    if not required_terms:
        return resources
    normalized_terms = tuple(term.casefold() for term in required_terms)
    return [
        resource
        for resource in resources
        if any(term in resource.title.casefold() for term in normalized_terms)
    ]


def filter_resources_by_all_title_terms(
    resources: list[Resource], required_terms: tuple[str, ...]
) -> list[Resource]:
    if not required_terms:
        return resources
    normalized_terms = tuple(term.casefold() for term in required_terms)
    return [
        resource
        for resource in resources
        if all(term in resource.title.casefold() for term in normalized_terms)
    ]


def filter_resources_by_primary_and_secondary(
    resources: list[Resource], primary_query: str, secondary_terms: tuple[str, ...]
) -> list[Resource]:
    primary = primary_query.casefold()
    secondary = tuple(term.casefold() for term in secondary_terms)
    primary_title = [resource for resource in resources if primary in resource.title.casefold()]
    candidates = primary_title or [
        resource
        for resource in resources
        if primary in f"{resource.title} {resource.snippet}".casefold()
    ]
    return [
        resource
        for resource in candidates
        if all(term in f"{resource.title} {resource.snippet}".casefold() for term in secondary)
    ]


def filter_resources_by_title_or_content(
    resources: list[Resource], required_terms: tuple[str, ...]
) -> list[Resource]:
    if not required_terms:
        return resources
    normalized_terms = tuple(term.casefold() for term in required_terms)
    return [
        resource
        for resource in resources
        if any(
            term in f"{resource.title} {resource.snippet}".casefold()
            for term in normalized_terms
        )
    ]


def prioritize_title_matches(
    resources: list[Resource], required_terms: tuple[str, ...]
) -> list[Resource]:
    title_matches = filter_resources_by_title_terms(resources, required_terms)
    return title_matches or resources


def prefer_title_filtered_resources(
    resources: list[Resource], required_terms: tuple[str, ...]
) -> list[Resource]:
    filtered = filter_resources_by_title_terms(resources, required_terms)
    return filtered or resources


def title_filter_terms(item: SearchLesson) -> tuple[str, ...]:
    if item.subject == "미술":
        return tuple(
            token
            for token in re.findall(r"[가-힣A-Za-z0-9]+", " ".join(query_variants(item)))
            if len(token) >= 2
        )
    if item.subject in {"국어", "음악"}:
        return ()
    if item.subject in {"수학", "과학"}:
        return concept_context_terms(item.topic)
    _, actions = concept_action_terms(item.topic)
    return actions


def title_filter_terms_for_query(item: SearchLesson, query: str) -> tuple[str, ...]:
    if item.subject == "미술":
        return tuple(
            token for token in re.findall(r"[가-힣A-Za-z0-9]+", query) if len(token) >= 2
        )
    return title_filter_terms(item)


def requires_sixth_grade_filter(subject: str) -> bool:
    return subject not in {"미술", "음악"}


def parse_result_cards(
    html: str, subject: str, *, require_sixth_grade: bool = False
) -> list[Resource]:
    soup = BeautifulSoup(html, "lxml")
    resources: list[Resource] = []
    seen: set[str] = set()
    candidates = list(soup.select(".search-result")) + [
        anchor
        for anchor in soup.find_all("a", href=True)
        if re.search(r"/boards/[^/]+/\d+", urlsplit(anchor["href"]).path)
        and anchor.select_one(".text-sm")
    ]
    for card in candidates:
        anchor = card.select_one("a.title[href]") if card.name != "a" else card
        if anchor is None or not anchor.get("href"):
            continue
        title_node = card.select_one(".text-sm")
        title = (title_node or anchor).get_text(" ", strip=True)
        if _is_pinned_notice(title):
            continue
        if require_sixth_grade:
            category_text = _card_category(card)
            if not category_text.startswith("6"):
                continue
        canonical = _canonical_post_url(anchor["href"])
        if canonical is None or canonical in seen:
            continue
        seen.add(canonical)
        fallback_rank = len(resources) + 1
        rank_text = card.get("data-rank", str(fallback_rank))
        try:
            rank = int(rank_text)
        except ValueError:
            rank = fallback_rank
        snippet_node = card.select_one(".snippet")
        type_node = card.select_one(".type")
        resources.append(
            Resource(
                title=title,
                url=canonical,
                subject=subject,
                snippet=snippet_node.get_text(" ", strip=True) if snippet_node else "",
                rank=rank,
                material_type=type_node.get_text(" ", strip=True) if type_node else None,
            )
        )
    return resources


def load_search_results_with_retry(
    load_html: Callable[[], str],
    subject: str,
    *,
    require_sixth_grade: bool = False,
    attempts: int = 3,
) -> list[Resource]:
    """Retry an apparently empty result page before accepting a real zero."""
    rows: list[Resource] = []
    for _ in range(max(1, attempts)):
        rows = parse_result_cards(
            load_html(), subject, require_sixth_grade=require_sixth_grade
        )
        if rows:
            return rows
    return rows


def parse_recent_art_cards(
    html: str, as_of: date, limit: int = 3, *, window_days: int = 7
) -> list[Resource]:
    soup = BeautifulSoup(html, "lxml")
    resources: list[Resource] = []
    seen: set[str] = set()
    oldest = as_of - timedelta(days=window_days - 1)
    for anchor in soup.find_all("a", href=True):
        if not re.search(r"/boards/[^/]+/\d+", urlsplit(anchor["href"]).path):
            continue
        title_node = anchor.select_one(".text-sm")
        if title_node is None:
            continue
        title = title_node.get_text(" ", strip=True)
        if _is_pinned_notice(title):
            continue
        published_on = _card_published_on(anchor)
        if published_on is None or not oldest <= published_on <= as_of:
            continue
        canonical = _canonical_post_url(anchor["href"])
        if canonical is None or canonical in seen:
            continue
        seen.add(canonical)
        resources.append(
            Resource(
                title=title,
                url=canonical,
                subject="미술",
                snippet="",
                rank=len(resources) + 1,
            )
        )
        if len(resources) >= limit:
            break
    return resources


def select_recent_art_from_pages(
    pages: list[str], as_of: date, limit: int = 3
) -> tuple[list[Resource], int]:
    """Use the smallest 7/14/21/28-day window that supplies the requested posts."""
    selected: list[Resource] = []
    for window_days in (7, 14, 21, 28):
        selected = []
        seen: set[str] = set()
        for html in pages:
            for resource in parse_recent_art_cards(
                html, as_of, limit, window_days=window_days
            ):
                if resource.url in seen:
                    continue
                seen.add(resource.url)
                selected.append(resource)
                if len(selected) >= limit:
                    return selected, window_days
    return selected[:limit], 28


def _card_published_on(card) -> date | None:
    node = card.select_one("time")
    if node is None:
        return None
    raw = node.get("datetime") or node.get_text(" ", strip=True)
    match = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", raw)
    if match is None:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def _is_pinned_notice(title: str) -> bool:
    return "\ud544\ub3c5" in title[:80]


def _card_category(card) -> str:
    for element in (card, *card.parents):
        if element is not card:
            post_links = element.select("a[href]")
            if len(post_links) > 1:
                break
        category = element.select_one(".category")
        if category is not None:
            return category.get_text(" ", strip=True)
    if card.get_text(" ", strip=True).startswith("6"):
        return "6"
    return ""


def _canonical_post_url(href: str) -> str | None:
    absolute = urljoin(INDISCHOOL_BASE_URL, href)
    parts = urlsplit(absolute)
    if parts.scheme != "https" or parts.hostname not in {"indischool.com", "www.indischool.com"}:
        return None
    if "download" in parts.path.casefold() or "attachment" in parts.path.casefold():
        return None
    host = "indischool.com"
    return urlunsplit(("https", host, parts.path.rstrip("/"), "", ""))


def resource_with_excerpt(
    resource: Resource, excerpt: str, max_chars: int = 2000
) -> Resource:
    return Resource(
        title=resource.title,
        url=resource.url,
        subject=resource.subject,
        snippet=excerpt.strip()[:max_chars],
        rank=resource.rank,
        material_type=resource.material_type,
    )


class IndischoolBrowser:
    def __init__(self, profile_path: Path, max_results: int = 5) -> None:
        self.profile_path = profile_path
        self.max_results = min(max(max_results, 1), 5)

    def _connect_session_browser(self, playwright):
        try:
            return playwright.chromium.connect_over_cdp(SESSION_BROWSER_ENDPOINT)
        except Exception:
            return None

    def _require_session_context(self, playwright):
        browser = self._connect_session_browser(playwright)
        if browser is None or not browser.contexts:
            raise IndischoolError(
                "session_browser_missing",
                "인디스쿨 세션 유지 창이 열려 있지 않습니다.",
            )
        return browser.contexts[0]

    def setup_login(self) -> None:
        from playwright.sync_api import sync_playwright

        self.profile_path.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(self.profile_path), headless=False
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(INDISCHOOL_BASE_URL, wait_until="domcontentloaded")
            input("인디스쿨 로그인을 마친 뒤 Enter를 누르세요: ")
            context.close()

    def search(self, item: SearchLesson) -> list[Resource]:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            context = self._require_session_context(playwright)
            page = context.new_page()
            try:
                page.goto(
                    urljoin(INDISCHOOL_BASE_URL, "boards/libLanguage"),
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
                login_error = session_login_error(page.url)
                if login_error is not None:
                    raise login_error
                if page.get_by_text("로그인", exact=True).count() and not page.get_by_text(
                    "로그아웃", exact=True
                ).count():
                    raise IndischoolError("login_required", "인디스쿨 로그인 세션이 만료되었습니다.")
                subject_link = page.get_by_role("link", name=item.subject, exact=True)
                if not subject_link.count():
                    raise IndischoolError("layout_changed", f"{item.subject} 자료실을 찾지 못했습니다.")
                board_path = subject_link.first.get_attribute("href")
                page.goto(urljoin(INDISCHOOL_BASE_URL, board_path), wait_until="domcontentloaded")
                grade_link = page.get_by_role("link", name="6학년", exact=True)
                if not grade_link.count():
                    if requires_sixth_grade_filter(item.subject):
                        raise IndischoolError("layout_changed", "6학년 필터를 찾지 못했습니다.")
                    grade_url = urljoin(INDISCHOOL_BASE_URL, board_path)
                else:
                    grade_url = urljoin(INDISCHOOL_BASE_URL, grade_link.first.get_attribute("href"))
                results_by_query: list[list[Resource]] = []
                required_title_terms = title_filter_terms(item)
                strict_content_filter = item.subject in {"수학", "과학"} and bool(required_title_terms)
                for query in query_variants(item):
                    parts = urlsplit(grade_url)
                    category = dict(
                        pair.split("=", 1) for pair in parts.query.split("&") if "=" in pair
                    ).get("category", "")
                    query_title_terms = title_filter_terms_for_query(item, query)
                    max_search_pages = 5 if query_title_terms else 1
                    rows_by_url: dict[str, Resource] = {}
                    for search_page in range(1, max_search_pages + 1):
                        search_params = {
                            "category": category,
                            "order_by": "likes",
                            "search_target": "text",
                            "local_query": query,
                        }
                        if search_page > 1:
                            search_params["page"] = str(search_page)
                        search_url = urlunsplit(
                            (
                                parts.scheme,
                                parts.netloc,
                                parts.path,
                                urlencode(search_params),
                                "",
                            )
                        )

                        def load_search_html(url: str = search_url) -> str:
                            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                            try:
                                page.wait_for_load_state("networkidle", timeout=3_000)
                            except PlaywrightTimeoutError:
                                pass
                            return page.content()

                        page_rows = load_search_results_with_retry(
                            load_search_html,
                            item.subject,
                            require_sixth_grade=requires_sixth_grade_filter(item.subject),
                            attempts=3,
                        )
                        if not page_rows:
                            break
                        for resource in page_rows:
                            rows_by_url.setdefault(resource.url, resource)
                    rows = list(rows_by_url.values())
                    if strict_content_filter:
                        title_rows = filter_resources_by_primary_and_secondary(
                            rows, query, query_title_terms
                        )
                        if title_rows:
                            results_by_query.append(title_rows)
                        else:
                            content_rows: list[Resource] = []
                            primary_title_rows = filter_resources_by_title_terms(rows, (query,))
                            candidates = primary_title_rows or rows
                            for resource in candidates:
                                try:
                                    page.goto(resource.url, wait_until="domcontentloaded", timeout=30_000)
                                    body = page.locator(".tiptap-readonly")
                                    excerpt = body.first.inner_text() if body.count() else ""
                                    candidate = resource_with_excerpt(resource, excerpt)
                                except PlaywrightTimeoutError:
                                    candidate = resource
                                if filter_resources_by_primary_and_secondary(
                                    [candidate], query, query_title_terms
                                ):
                                    content_rows.append(candidate)
                            results_by_query.append(content_rows)
                    else:
                        if item.subject == "미술":
                            art_title_rows = filter_resources_by_all_title_terms(rows, query_title_terms)
                            results_by_query.append(art_title_rows or rows)
                        else:
                            results_by_query.append(
                                prefer_title_filtered_resources(rows, query_title_terms)
                            )
                collected = choose_resources_from_queries(results_by_query, self.max_results)
                enriched: list[Resource] = []
                for resource in collected[: self.max_results]:
                    if strict_content_filter and resource.snippet:
                        enriched.append(resource)
                        continue
                    try:
                        page.goto(resource.url, wait_until="domcontentloaded", timeout=30_000)
                        body = page.locator(".tiptap-readonly")
                        excerpt = body.first.inner_text() if body.count() else ""
                        enriched.append(resource_with_excerpt(resource, excerpt))
                    except PlaywrightTimeoutError:
                        enriched.append(resource)
                return enriched
            except IndischoolError:
                raise
            except PlaywrightTimeoutError as exc:
                raise IndischoolError("layout_changed", "인디스쿨 화면 요소를 찾지 못했습니다.") from exc
            finally:
                page.close()

    def recent_art_resources(self, as_of: date, limit: int = 3) -> list[Resource]:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            context = self._require_session_context(playwright)
            page = context.new_page()
            try:
                page.goto(
                    urljoin(INDISCHOOL_BASE_URL, "boards/libLanguage"),
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
                login_error = session_login_error(page.url)
                if login_error is not None:
                    raise login_error
                subject_link = page.get_by_role("link", name="미술", exact=True)
                if not subject_link.count():
                    raise IndischoolError("layout_changed", "미술 자료실을 찾지 못했습니다.")
                board_path = subject_link.first.get_attribute("href")
                page.goto(
                    urljoin(INDISCHOOL_BASE_URL, board_path),
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
                grade_link = page.get_by_role("link", name="6학년", exact=True)
                grade_url = (
                    urljoin(INDISCHOOL_BASE_URL, grade_link.first.get_attribute("href"))
                    if grade_link.count()
                    else urljoin(INDISCHOOL_BASE_URL, board_path)
                )
                parts = urlsplit(grade_url)
                category = dict(
                    pair.split("=", 1) for pair in parts.query.split("&") if "=" in pair
                ).get("category", "")
                query = {"order_by": "likes"}
                if category:
                    query["category"] = category
                page_html: list[str] = []
                seen_page_signatures: set[tuple[str, ...]] = set()
                for page_number in range(1, 51):
                    recent_url = urlunsplit(
                        (
                            parts.scheme,
                            parts.netloc,
                            parts.path,
                            urlencode({**query, "page": page_number}),
                            "",
                        )
                    )
                    page.goto(recent_url, wait_until="domcontentloaded", timeout=15_000)
                    html = page.content()
                    signature = tuple(
                        anchor.get("href", "")
                        for anchor in BeautifulSoup(html, "lxml").find_all("a", href=True)
                        if re.search(r"/boards/[^/]+/\d+", urlsplit(anchor["href"]).path)
                    )
                    if signature in seen_page_signatures:
                        break
                    seen_page_signatures.add(signature)
                    page_html.append(html)
                    if not page.locator("a[href*='/boards/']").count():
                        break
                resources, _window_days = select_recent_art_from_pages(
                    page_html, as_of, limit
                )
                return resources
            except IndischoolError:
                raise
            except PlaywrightTimeoutError as exc:
                raise IndischoolError("layout_changed", "미술 게시판 화면을 찾지 못했습니다.") from exc
            finally:
                page.close()
