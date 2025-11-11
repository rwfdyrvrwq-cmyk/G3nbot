"""
Simple scraper for AQ character pages.

Public function:
  get_character_info(char_id: str) -> dict

It attempts to fetch https://account.aq.com/CharPage?id=<char_id>
and extract the character name and guild. The page HTML structure may
vary; this uses a few heuristics and falls back to simple regex search.

Note: network requests are used; the caller must provide a char_id that
is a numeric or short string that the site accepts.
"""
from typing import Optional, Dict
import re
import requests
from bs4 import BeautifulSoup


BASE = "https://account.aq.com/CharPage"


def _first_text_by_label(soup: BeautifulSoup, label: str) -> Optional[str]:
    # find tags that contain the label text, then take next sibling or nearby text
    # e.g. <label>Guild:</label> Alter or <b>Guild:</b> SomeGuild or 'Guild: <a>SomeGuild</a>'
    el = soup.find(text=re.compile(re.escape(label), re.I))
    if not el:
        return None
    
    parent = el.parent
    
    # Strategy 1: Look for link in parent element
    if parent:
        link = parent.find('a')
        if link and link.text.strip():
            return link.text.strip()
    
    # Strategy 2: Get next text node after parent (handles <label>Guild:</label> Alter)
    if parent:
        # Skip past the parent element and find the next text content
        current = parent
        while current:
            next_elem = current.next_sibling
            if next_elem is None:
                break
            if isinstance(next_elem, str):
                text = next_elem.strip()
                if text and text not in (':', '---'):
                    return text
            elif hasattr(next_elem, 'get_text'):
                text = next_elem.get_text(strip=True)
                if text and text not in (':', '---'):
                    return text
            # Keep looking in next siblings
            current = next_elem
            if current and hasattr(current, 'name') and current.name in ('br', 'div', 'p'):
                break
    
    # Strategy 3: Try splitting if label is embedded in same text node
    txt = el.strip()
    parts = re.split(re.escape(label), txt, flags=re.I)
    if len(parts) >= 2:
        remaining = parts[1].strip()
        if remaining and remaining not in (':', '---'):
            return remaining
    
    return None


def get_character_info(char_id: str) -> Dict[str, Optional[str]]:
    """Fetch the character page and return a dict with keys:
       name, guild, class, level, and other character details, plus raw_html

    If a field cannot be found, its value will be None.
    """
    params = {"id": char_id}
    try:
        resp = requests.get(BASE, params=params, timeout=10)
    except Exception as e:
        raise RuntimeError(f"Network error when fetching character page: {e}")
    if resp.status_code != 200:
        raise RuntimeError(f"Character page returned status {resp.status_code}")

    html = resp.text
    soup = BeautifulSoup(html, "html.parser")

    # Initialize all fields
    result = {
        "name": None,
        "guild": None,
        "class": None,
        "level": None,
        "experience": None,
        "health": None,
        "mana": None,
        "raw_html": html
    }

    # Parse character name (try h1, h2, h3 tags)
    for tagname in ("h1", "h2", "h3", "title"):
        t = soup.find(tagname)
        if t and t.text.strip():
            text = t.text.strip()
            if len(text) <= 40:  # heuristic length
                result["name"] = text
                break

    # If not found, search for labels like 'Character' or 'Name'
    if not result["name"]:
        result["name"] = _first_text_by_label(soup, "Character") or _first_text_by_label(soup, "Name")

    # Guild: look for label 'Guild' and nearby link/text
    result["guild"] = _first_text_by_label(soup, "Guild")
    if not result["guild"]:
        m = re.search(r"Guild[:\s]*<[^>]*>([^<]+)</", html, re.I)
        if m:
            result["guild"] = m.group(1).strip()
    if not result["guild"]:
        m2 = re.search(r"Guild[:\s]*([A-Za-z0-9 _-]{2,50})", html, re.I)
        if m2:
            result["guild"] = m2.group(1).strip()

    # Class: look for 'Class' label
    result["class"] = _first_text_by_label(soup, "Class")

    # Level: look for 'Level' label
    level_text = _first_text_by_label(soup, "Level")
    if level_text:
        # Extract just the number if it's like "Level: 50"
        m = re.search(r"\d+", level_text)
        if m:
            result["level"] = m.group(0)

    # Experience: look for 'Experience' or 'EXP' label
    result["experience"] = _first_text_by_label(soup, "Experience") or _first_text_by_label(soup, "EXP")

    # Health: look for 'Health' or 'HP' label
    result["health"] = _first_text_by_label(soup, "Health") or _first_text_by_label(soup, "HP")

    # Mana: look for 'Mana' or 'MP' label
    result["mana"] = _first_text_by_label(soup, "Mana") or _first_text_by_label(soup, "MP")

    # Normalize empty strings to None
    for key in result:
        if key != "raw_html":
            val = result[key]
            result[key] = val.strip() if val and val.strip() else None

    return result


if __name__ == "__main__":
    # quick manual test (won't run in CI); user can run `python scraper.py <id>`
    import sys
    if len(sys.argv) >= 2:
        cid = sys.argv[1]
        info = get_character_info(cid)
        print("Name:", info['name'])
        print("Guild:", info['guild'])
    else:
        print("Usage: python scraper.py <char_id>")
