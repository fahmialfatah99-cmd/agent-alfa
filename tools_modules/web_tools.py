"""Web & Research Tools for ALFA Agent."""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def web_search(query: str, max_results: int = 5) -> Dict[str, Any]:
    """Search the web using DuckDuckGo."""
    try:
        from ddgs import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", "")
                })
        return {
            "status": "success",
            "message": f"Found {len(results)} results",
            "data": results
        }
    except Exception as e:
        logger.error(f"Web search error: {e}")
        return {"status": "error", "error": str(e)}


def fetch_web_page_content(url: str, max_length: int = 4000) -> Dict[str, Any]:
    """Fetch and extract content from a web page."""
    try:
        import httpx
        from bs4 import BeautifulSoup
        
        response = httpx.get(url, timeout=15, follow_redirects=True)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Remove script and style elements
        for tag in soup(['script', 'style']):
            tag.decompose()
        
        text = soup.get_text(separator=' ', strip=True)
        text = text[:max_length] + ("..." if len(text) > max_length else "")
        
        return {
            "status": "success",
            "message": "Content fetched successfully",
            "data": {"url": url, "content": text}
        }
    except Exception as e:
        logger.error(f"Fetch page error: {e}")
        return {"status": "error", "error": str(e)}


def deep_research_topic(topic: str, max_depth: int = 3) -> Dict[str, Any]:
    """Conduct deep research on a topic."""
    # Placeholder - full implementation would chain multiple searches
    result = web_search(topic, max_results=10)
    return {
        "status": "success",
        "message": f"Research completed for: {topic}",
        "data": result.get("data", [])
    }
