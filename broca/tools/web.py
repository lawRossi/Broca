import asyncio
import os

import aiohttp
from tavily import TavilyClient

from broca.logging_config import get_logger
from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus

logger = get_logger(__name__)


# ------------------------------------------------------------------
# Shared AnySearch helpers
# ------------------------------------------------------------------

def _anysearch_config() -> tuple[str, str]:
    """Return (api_key, base_url) for AnySearch.

    Priority: configs.json search section > environment variables.
    """
    try:
        from broca.configs import get_configs

        cfg = get_configs()
        api_key = cfg.search.anysearch_api_key or os.environ.get("ANYSEARCH_API_KEY", "")
        base_url = (
            cfg.search.anysearch_api_base_url
            or os.environ.get("ANYSEARCH_API_BASE_URL", "https://api.anysearch.com")
        ).rstrip("/")
        return api_key, base_url
    except Exception:
        api_key = os.environ.get("ANYSEARCH_API_KEY", "")
        base_url = os.environ.get(
            "ANYSEARCH_API_BASE_URL", "https://api.anysearch.com"
        ).rstrip("/")
        return api_key, base_url


def _anysearch_headers(api_key: str) -> dict:
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "X-Anysearch-Client": "broca/1.0",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _default_search_provider() -> str:
    """Get default search provider from config, fallback to 'tavily'."""
    try:
        from broca.configs import get_configs

        p = get_configs().search.default_search_provider
        return p if p in ("tavily", "anysearch") else "tavily"
    except Exception:
        return "tavily"


def _default_fetch_provider() -> str:
    """Get default fetch provider from config, fallback to 'anysearch'."""
    try:
        from broca.configs import get_configs

        p = get_configs().search.default_fetch_provider
        return p if p in ("anysearch", "playwright") else "anysearch"
    except Exception:
        return "anysearch"


# ==================================================================
#  WebFetch
# ==================================================================

class WebFetch(Tool):
    def __init__(self):
        super().__init__()
        self.browser = None
        self.playwright = None

    @property
    def name(self):
        return "web_fetch"

    @property
    def description(self):
        return "Use this tool to fetch and extract content from web pages. Supports text and markdown formats."

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL of the web page to fetch",
                },
                "format": {
                    "type": "string",
                    "description": "The format to extract content as: 'text' or 'markdown'",
                    "enum": ["text", "markdown"],
                    "default": "text",
                },
                "provider": {
                    "type": "string",
                    "description": (
                        "Fetch method: 'anysearch' (lightweight API, always returns markdown) "
                        "or 'playwright' (full browser rendering, falls back to anysearch if unavailable)"
                    ),
                    "enum": ["anysearch", "playwright"],
                    "default": _default_fetch_provider(),
                },
                "wait_for": {
                    "type": "string",
                    "description": "Optional CSS selector to wait for before extracting content (playwright only)",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in milliseconds (default: 30000)",
                    "default": 30000,
                },
            },
            "required": ["url"],
        }

    # ----------------------------------------------------------------
    # Playwright helpers
    # ----------------------------------------------------------------

    async def _init_playwright(self):
        """Initialize Playwright browser"""
        if self.playwright is None:
            try:
                from playwright.async_api import async_playwright

                self.playwright = await async_playwright().start()
                self.browser = await self.playwright.chromium.launch(headless=True)
            except ImportError:
                logger.warning(
                    "playwright package not installed. Please install it with: pip install playwright && playwright install chromium"
                )
                return False
            except Exception as e:
                logger.error(f"Failed to launch Playwright browser: {e}")
                return False
        return True

    async def _close(self):
        """Close Playwright browser"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        self.browser = None
        self.playwright = None

    def _html_to_markdown(self, html: str) -> str:
        """Convert HTML to markdown"""
        try:
            from markdownify import markdownify as md

            return md(html)
        except ImportError:
            logger.warning("markdownify not installed, returning plain text")
            return self._html_to_text(html)

    def _html_to_text(self, html: str) -> str:
        """Convert HTML to plain text"""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            for script in soup(["script", "style"]):
                script.decompose()
            text = soup.get_text(separator="\n")
            lines = [line.strip() for line in text.split("\n")]
            return "\n".join(line for line in lines if line)
        except ImportError:
            import re

            text = re.sub(r"<[^>]+>", "", html)
            return text

    # ----------------------------------------------------------------
    # Execute (dispatch by provider)
    # ----------------------------------------------------------------

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        provider = arguments.get("provider") or _default_fetch_provider()
        if provider == "anysearch":
            return await self._execute_anysearch(arguments)

        # provider == "playwright": try playwright, fall back to anysearch
        result = await self._execute_playwright(arguments)
        if result.status == ToolStatus.ERROR and "Playwright not available" in result.content:
            logger.info("Playwright unavailable, falling back to AnySearch")
            return await self._execute_anysearch(arguments)
        return result

    # ----------------------------------------------------------------
    # Playwright fetch
    # ----------------------------------------------------------------

    async def _execute_playwright(self, arguments: dict) -> ToolResult:
        url = arguments["url"]

        if not await self._init_playwright():
            return ToolResult(
                status=ToolStatus.ERROR,
                content="Error: Playwright not available. Please install it with: pip install playwright && playwright install chromium",
            )

        page = None
        try:
            page = await self.browser.new_page()
            timeout = arguments.get("timeout", 30000)
            wait_for = arguments.get("wait_for")

            await page.goto(url, timeout=timeout, wait_until="domcontentloaded")

            if wait_for:
                await page.wait_for_selector(wait_for, timeout=timeout)

            content_format = arguments.get("format", "text")

            if content_format == "markdown":
                html_content = await page.content()
                result = self._html_to_markdown(html_content)
            else:
                html_content = await page.content()
                result = self._html_to_text(html_content)

            return ToolResult(status=ToolStatus.SUCCESS, content=result)

        except Exception as e:
            logger.error(f"Web fetch error: {e}")
            return ToolResult(
                status=ToolStatus.ERROR, content=f"Error fetching web page: {str(e)}"
            )
        finally:
            if page:
                await page.close()
            await self._close()

    # ----------------------------------------------------------------
    # AnySearch extract
    # ----------------------------------------------------------------

    async def _execute_anysearch(self, arguments: dict) -> ToolResult:
        url = arguments["url"]
        api_key, base_url = _anysearch_config()
        headers = _anysearch_headers(api_key)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{base_url}/v1/extract",
                    json={"url": url},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    body = await resp.json()

                    if resp.status >= 400 or body.get("code", -1) != 0:
                        msg = body.get("message", f"HTTP {resp.status}")
                        request_id = body.get("request_id", "")
                        detail = f" (request_id: {request_id})" if request_id else ""
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            content=f"AnySearch extract error: {msg}{detail}",
                        )

                    data = body.get("data", {})
                    title = data.get("title", "")
                    content = data.get("content", "")

                    output: list[str] = []
                    if title:
                        output.append(f"# {title}\n")
                    output.append(content)

                    return ToolResult(
                        status=ToolStatus.SUCCESS,
                        content="\n".join(output),
                    )

        except Exception as e:
            logger.error(f"AnySearch extract error: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Error fetching page via AnySearch: {str(e)}",
            )


# ==================================================================
#  WebSearch
# ==================================================================

class WebSearch(Tool):
    """Web search tool supporting multiple providers: Tavily and AnySearch.

    The active provider is selected per-call via the ``provider`` parameter.
    API keys are still read from environment variables:
      - Tavily:    ``TAVILY_API_KEY``
      - AnySearch: ``ANYSEARCH_API_KEY`` (optional, anonymous works)
    """

    def __init__(self, api_key: str | None = None):
        super().__init__()
        self.api_key = api_key
        # Tavily state
        self.tavily_client: TavilyClient | None = None
        # AnySearch state
        self._anysearch_api_key: str = ""
        self._anysearch_base_url: str = "https://api.anysearch.com"
        self._init_clients()

    # ----------------------------------------------------------------
    # Tool interface
    # ----------------------------------------------------------------

    @property
    def name(self):
        return "web_search"

    @property
    def description(self):
        return "Use this tool to perform web searches and get relevant results with sources."

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to look up",
                },
                "provider": {
                    "type": "string",
                    "description": "Search provider: 'tavily' or 'anysearch'",
                    "enum": ["tavily", "anysearch"],
                    "default": _default_search_provider(),
                },
                # ---- shared ----
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results per query (default: 5, AnySearch max 10)",
                    "default": 5,
                },
                # ---- Tavily-specific ----
                "search_depth": {
                    "type": "string",
                    "description": "Search depth (Tavily): 'fast', 'basic', 'advanced', or 'ultra-fast'",
                    "enum": ["fast", "basic", "advanced", "ultra-fast"],
                    "default": "fast",
                },
                "topic": {
                    "type": "string",
                    "description": "Search topic (Tavily): 'general', 'news', or 'finance'",
                    "enum": ["general", "news", "finance"],
                    "default": "general",
                },
                "time_range": {
                    "type": "string",
                    "description": "Time range filter (Tavily): 'day', 'week', 'month', or 'year'",
                    "enum": ["day", "week", "month", "year"],
                },
                "include_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of domains to include in search (Tavily)",
                },
                "exclude_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of domains to exclude from search (Tavily)",
                },
                "include_answer": {
                    "type": "boolean",
                    "description": "Whether to include an AI-generated answer (Tavily)",
                    "default": True,
                },
                "include_images": {
                    "type": "boolean",
                    "description": "Whether to include images in results (Tavily)",
                    "default": False,
                },
                # ---- AnySearch-specific ----
                "tag": {
                    "type": "string",
                    "description": "Capability tag for vertical domain search (AnySearch), e.g. 'finance.quote'",
                },
                "tag_params": {
                    "type": "object",
                    "description": "Structured parameters for the tag (AnySearch)",
                },
                "zone": {
                    "type": "string",
                    "description": "Region preference (AnySearch): 'cn' or 'intl'",
                    "enum": ["cn", "intl"],
                },
                "language": {
                    "type": "string",
                    "description": "Preferred result language (AnySearch), e.g. 'zh-CN' or 'en'",
                },
                # ---- Batch search (both providers) ----
                "queries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query string",
                            },
                            "tag": {
                                "type": "string",
                                "description": "Capability tag (AnySearch)",
                            },
                            "tag_params": {
                                "type": "object",
                                "description": "Tag parameters (AnySearch)",
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Max results for this query",
                            },
                            "zone": {
                                "type": "string",
                                "enum": ["cn", "intl"],
                                "description": "Region preference (AnySearch)",
                            },
                            "language": {
                                "type": "string",
                                "description": "Result language (AnySearch)",
                            },
                        },
                        "required": ["query"],
                    },
                    "minItems": 1,
                    "maxItems": 5,
                    "description": (
                        "Batch search: array of 1-5 query objects. "
                        "When provided, overrides the single 'query' parameter. "
                        "AnySearch runs queries in parallel; Tavily runs them sequentially."
                    ),
                },
            },
            "required": ["query"],
        }

    # ----------------------------------------------------------------
    # Client initialisation
    # ----------------------------------------------------------------

    def _init_clients(self):
        """Initialise both providers. A provider that lacks credentials
        will simply be unavailable (errors are surfaced at call time).

        API key priority: constructor arg > configs.json > environment variable.
        """
        # Try to load keys from web config (configs.json)
        cfg_tavily_key = ""
        cfg_anysearch_key = ""
        cfg_anysearch_url = ""
        try:
            from broca.configs import get_configs

            cfg = get_configs()
            cfg_tavily_key = cfg.search.tavily_api_key
            cfg_anysearch_key = cfg.search.anysearch_api_key
            cfg_anysearch_url = cfg.search.anysearch_api_base_url
        except Exception:
            pass

        # Tavily
        try:
            key = self.api_key or cfg_tavily_key or os.environ.get("TAVILY_API_KEY")
            if key:
                self.tavily_client = TavilyClient(api_key=key)
            else:
                logger.warning("No Tavily API key found. Tavily search will be unavailable.")
        except ImportError:
            logger.warning("tavily-python package not installed. Tavily search will be unavailable.")

        # AnySearch (always initialisable – works anonymously)
        self._anysearch_api_key = cfg_anysearch_key or os.environ.get("ANYSEARCH_API_KEY", "")
        self._anysearch_base_url = (
            cfg_anysearch_url
            or os.environ.get("ANYSEARCH_API_BASE_URL", "https://api.anysearch.com")
        ).rstrip("/")

    # ----------------------------------------------------------------
    # Execute (dispatch by provider param)
    # ----------------------------------------------------------------

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        provider = (arguments.get("provider") or _default_search_provider()).lower()
        if provider == "anysearch":
            return await self._execute_anysearch(arguments)
        elif provider == "tavily":
            return await self._execute_tavily(arguments)
        else:
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Unknown search provider: {provider}. Supported: 'tavily', 'anysearch'.",
            )

    # ----------------------------------------------------------------
    # Tavily
    # ----------------------------------------------------------------

    async def _execute_tavily(self, arguments: dict) -> ToolResult:
        if not self.tavily_client:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="Error: Tavily client not available. Set TAVILY_API_KEY to enable Tavily search.",
            )

        queries = arguments.get("queries")
        if queries:
            return await self._execute_tavily_batch(queries, arguments)
        return await self._execute_tavily_single(arguments)

    async def _execute_tavily_single(self, arguments: dict) -> ToolResult:
        query = arguments["query"]
        try:
            search_params: dict = {
                "query": query,
                "search_depth": arguments.get("search_depth", "fast"),
                "topic": arguments.get("topic", "general"),
                "max_results": arguments.get("max_results", 5),
                "include_answer": arguments.get("include_answer", True),
                "include_images": arguments.get("include_images", False),
            }

            if arguments.get("time_range"):
                search_params["time_range"] = arguments.get("time_range")
            if arguments.get("include_domains"):
                search_params["include_domains"] = arguments.get("include_domains")
            if arguments.get("exclude_domains"):
                search_params["exclude_domains"] = arguments.get("exclude_domains")

            result = self.tavily_client.search(**search_params)
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=self._format_tavily_results(result),
            )

        except Exception as e:
            logger.error(f"Web search error (Tavily): {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Error performing web search: {str(e)}",
            )

    async def _execute_tavily_batch(self, queries: list[dict], shared_args: dict) -> ToolResult:
        """Run multiple Tavily searches sequentially (Tavily has no batch API)."""
        output_parts: list[str] = []
        errors: list[str] = []

        for i, q in enumerate(queries, 1):
            item_args = {
                "query": q["query"],
                "search_depth": q.get("search_depth", shared_args.get("search_depth", "fast")),
                "topic": q.get("topic", shared_args.get("topic", "general")),
                "max_results": q.get("max_results", shared_args.get("max_results", 5)),
                "include_answer": shared_args.get("include_answer", True),
                "include_images": shared_args.get("include_images", False),
            }
            if shared_args.get("time_range"):
                item_args["time_range"] = shared_args["time_range"]
            if shared_args.get("include_domains"):
                item_args["include_domains"] = shared_args["include_domains"]
            if shared_args.get("exclude_domains"):
                item_args["exclude_domains"] = shared_args["exclude_domains"]

            try:
                result = self.tavily_client.search(**item_args)
                content = self._format_tavily_results(result)
                output_parts.append(f"=== Query {i}: {q['query']} ===\n{content}")
            except Exception as e:
                logger.error(f"Tavily batch search error (query {i}): {e}")
                errors.append(f"Query {i} ({q['query']}): {str(e)}")

        if not output_parts and errors:
            return ToolResult(status=ToolStatus.ERROR, content="; ".join(errors))

        content = "\n\n".join(output_parts)
        if errors:
            content += f"\n\n---\nErrors: {'; '.join(errors)}"

        return ToolResult(status=ToolStatus.SUCCESS, content=content)

    # ----------------------------------------------------------------
    # AnySearch – single search
    # ----------------------------------------------------------------

    async def _execute_anysearch(self, arguments: dict) -> ToolResult:
        queries = arguments.get("queries")
        if queries:
            return await self._execute_anysearch_batch(queries)
        return await self._execute_anysearch_single(arguments)

    async def _execute_anysearch_single(self, arguments: dict) -> ToolResult:
        query = arguments["query"]
        payload = self._build_anysearch_payload(query, arguments)
        return await self._anysearch_search_post(payload)

    def _build_anysearch_payload(self, query: str, extra: dict) -> dict:
        payload: dict = {"query": query}
        if extra.get("tag"):
            payload["tag"] = extra["tag"]
        if extra.get("tag_params"):
            payload["params"] = extra["tag_params"]
        if extra.get("zone"):
            payload["zone"] = extra["zone"]
        if extra.get("language"):
            payload["language"] = extra["language"]
        max_results = max(1, min(int(extra.get("max_results", 5)), 10))
        payload["max_results"] = max_results
        return payload

    async def _anysearch_search_post(self, payload: dict) -> ToolResult:
        """POST a search payload to the AnySearch API."""
        headers = _anysearch_headers(self._anysearch_api_key)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._anysearch_base_url}/v1/search",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    body = await resp.json()

                    if resp.status >= 400 or body.get("code", -1) != 0:
                        msg = body.get("message", f"HTTP {resp.status}")
                        request_id = body.get("request_id", "")
                        detail = f" (request_id: {request_id})" if request_id else ""
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            content=f"AnySearch API error: {msg}{detail}",
                        )

                    return ToolResult(
                        status=ToolStatus.SUCCESS,
                        content=self._format_anysearch_results(body.get("data", {})),
                    )

        except Exception as e:
            logger.error(f"Web search error (AnySearch): {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Error performing web search: {str(e)}",
            )

    # ----------------------------------------------------------------
    # AnySearch – batch search (parallel)
    # ----------------------------------------------------------------

    async def _execute_anysearch_batch(self, queries: list[dict]) -> ToolResult:
        """Run multiple AnySearch queries in parallel via asyncio.gather."""
        tasks = [
            self._anysearch_search_post(self._build_anysearch_payload(q["query"], q))
            for q in queries
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output_parts: list[str] = []
        errors: list[str] = []

        for i, (q, res) in enumerate(zip(queries, results), 1):
            if isinstance(res, Exception):
                logger.error(f"AnySearch batch error (query {i}): {res}")
                errors.append(f"Query {i} ({q['query']}): {res}")
            elif res.status == ToolStatus.ERROR:
                errors.append(f"Query {i} ({q['query']}): {res.content}")
            else:
                output_parts.append(f"=== Query {i}: {q['query']} ===\n{res.content}")

        if not output_parts and errors:
            return ToolResult(status=ToolStatus.ERROR, content="; ".join(errors))

        content = "\n\n".join(output_parts)
        if errors:
            content += f"\n\n---\nErrors: {'; '.join(errors)}"

        return ToolResult(status=ToolStatus.SUCCESS, content=content)

    # ----------------------------------------------------------------
    # Result formatting
    # ----------------------------------------------------------------

    def _format_tavily_results(self, result: dict) -> str:
        """Format Tavily search results for better readability."""
        output: list[str] = []

        if "answer" in result and result["answer"]:
            output.append("Answer:")
            output.append(result["answer"])
            output.append("")

        if "sources" in result and result["sources"]:
            output.append("Sources:")
            for i, source in enumerate(result["sources"], 1):
                output.append(f"{i}. {source}")
            output.append("")

        if "results" in result and result["results"]:
            output.append("Search Results:")
            for i, item in enumerate(result["results"], 1):
                title = item.get("title", "No title")
                url = item.get("url", "No URL")
                content = item.get("content", "")
                score = item.get("score", 0)

                output.append(f"{i}. {title}")
                output.append(f"   URL: {url}")
                output.append(f"   Relevance: {score:.2f}")
                if content:
                    output.append(f"   Content: {content}")
                output.append("")

        return "\n".join(output)

    def _format_anysearch_results(self, data: dict) -> str:
        """Format AnySearch results for better readability."""
        results = data.get("results") or []
        metadata = data.get("metadata") or {}

        if not results:
            return "No relevant results found."

        total = metadata.get("total_results", len(results))
        elapsed = metadata.get("search_time_ms", 0)

        output: list[str] = [f"Search Results ({total} results, {elapsed}ms)", ""]
        for i, item in enumerate(results, 1):
            title = item.get("title") or "(Untitled)"
            url = item.get("url", "")
            content = item.get("content") or item.get("snippet") or ""

            output.append(f"{i}. {title}")
            if url:
                output.append(f"   URL: {url}")
            if content:
                output.append(f"   Content: {content}")
            output.append("")

        return "\n".join(output)
