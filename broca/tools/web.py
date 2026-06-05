from tavily import TavilyClient

from broca.logging_config import get_logger
from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus

logger = get_logger(__name__)


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
                "wait_for": {
                    "type": "string",
                    "description": "Optional CSS selector to wait for before extracting content",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in milliseconds (default: 30000)",
                    "default": 30000,
                },
            },
            "required": ["url"],
        }

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

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
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


class WebSearch(Tool):
    def __init__(self, api_key: str | None = None):
        super().__init__()
        self.api_key = api_key
        self.client = None
        self._init_client()

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
                "search_depth": {
                    "type": "string",
                    "description": "Search depth: 'fast', 'basic', 'advanced', or 'ultra-fast'",
                    "enum": ["fast", "basic", "advanced", "ultra-fast"],
                    "default": "fast",
                },
                "topic": {
                    "type": "string",
                    "description": "Search topic: 'general', 'news', or 'finance'",
                    "enum": ["general", "news", "finance"],
                    "default": "general",
                },
                "time_range": {
                    "type": "string",
                    "description": "Time range filter: 'day', 'week', 'month', or 'year'",
                    "enum": ["day", "week", "month", "year"],
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 10)",
                    "default": 5,
                },
                "include_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of domains to include in search",
                },
                "exclude_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of domains to exclude from search",
                },
                "include_answer": {
                    "type": "boolean",
                    "description": "Whether to include an AI-generated answer",
                    "default": True,
                },
                "include_images": {
                    "type": "boolean",
                    "description": "Whether to include images in results",
                    "default": False,
                },
            },
            "required": ["query"],
        }

    def _init_client(self) -> bool:
        """Initialize Tavily client with API key"""
        try:
            # Try to get API key from environment variable if not provided
            if not self.api_key:
                import os

                self.api_key = os.environ.get("TAVILY_API_KEY")

            if self.api_key:
                self.client = TavilyClient(api_key=self.api_key)
                return True
            else:
                logger.warning("No Tavily API key provided. Web search will not work.")
        except ImportError:
            logger.warning(
                "tavily-python package not installed. Web search will not work."
            )
        return False

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        if not self.client:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="Error: Tavily client not initialized. Please provide a valid API key.",
            )

        query = arguments["query"]
        try:
            # Build search parameters
            search_params = {
                "query": query,
                "search_depth": arguments.get("search_depth", "fast"),
                "topic": arguments.get("topic", "general"),
                "max_results": arguments.get("max_results", 5),
                "include_answer": arguments.get("include_answer", True),
                "include_images": arguments.get("include_images", False),
            }

            # Add optional parameters
            if arguments.get("time_range"):
                search_params["time_range"] = arguments.get("time_range")
            if arguments.get("include_domains"):
                search_params["include_domains"] = arguments.get("include_domains")
            if arguments.get("exclude_domains"):
                search_params["exclude_domains"] = arguments.get("exclude_domains")

            # Perform search
            result = self.client.search(**search_params)

            # Format results
            return ToolResult(
                status=ToolStatus.SUCCESS, content=self._format_results(result)
            )

        except Exception as e:
            logger.error(f"Web search error: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                content=f"Error performing web search: {str(e)}",
            )

    def _format_results(self, result: dict) -> str:
        """Format search results for better readability"""
        output = []

        # Add answer if available
        if "answer" in result and result["answer"]:
            output.append("Answer:")
            output.append(result["answer"])
            output.append("")

        # Add sources
        if "sources" in result and result["sources"]:
            output.append("Sources:")
            for i, source in enumerate(result["sources"], 1):
                output.append(f"{i}. {source}")
            output.append("")

        # Add results
        if "results" in result and result["results"]:
            output.append("Search Results:")
            for i, result_item in enumerate(result["results"], 1):
                title = result_item.get("title", "No title")
                url = result_item.get("url", "No URL")
                content = result_item.get("content", "")
                score = result_item.get("score", 0)

                output.append(f"{i}. {title}")
                output.append(f"   URL: {url}")
                output.append(f"   Relevance: {score:.2f}")
                if content:
                    output.append(f"   Content: {content}")
                output.append("")

        return "\n".join(output)
