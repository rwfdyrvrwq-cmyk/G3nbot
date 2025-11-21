"""
Character data scraper for AQW CharPage

This module combines multiple parsing strategies for robust character data extraction:
1. FlashVars parsing: Fast extraction of equipped/cosmetic items from embedded Flash parameters
2. HTML label parsing: Extracts level, class, faction, guild from div.card-body labels (MultusAQW approach)
3. Fallback parsing: Uses _first_text_by_label for additional robustness
4. API endpoints: Fetches badges and inventory counts from CharPage JSON endpoints

Improvements over base implementation:
- Cleaner ccid extraction using regex helper
- div.card-body label parsing for more reliable data extraction
- Better error handling with specific exception catching
- Timeout handling for API requests
- Validation of JSON response formats
"""

from typing import Optional, Dict, Any, Union
import re
import requests
from urllib.parse import unquote_plus
from bs4 import BeautifulSoup
from bs4.element import NavigableString
import aiohttp
import asyncio
import httpx
from urllib.parse import quote, urlparse, urlunparse


BASE = "https://account.aq.com/CharPage"


def extract_ccid(html: str) -> Optional[int]:
    """
    Extract character ID (ccid) from CharPage HTML.
    Uses regex to find 'var ccid = <number>;'
    
    Args:
        html: The HTML content of the CharPage
        
    Returns:
        The character ID as an integer, or None if not found
    """
    # Remove newlines for easier matching
    html_clean = html.replace('\r\n', '').replace('\n', '').replace('\r', '')
    
    # Match: var ccid = 12345;
    regex = r'var\s+ccid\s*=\s*(\d+);'
    match = re.search(regex, html_clean)
    
    if match:
        return int(match.group(1))
    
    return None


def _first_text_by_label(soup: BeautifulSoup, label: str) -> Optional[str]:
    el = soup.find(text=re.compile(re.escape(label), re.I))
    if not el:
        return None
    
    parent = el.parent
    
    if parent:
        link = parent.find('a')
        if link and link.text.strip():
            return link.text.strip()
    
    if parent:
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
            current = next_elem
            if current and hasattr(current, 'name') and current.name in ('br', 'div', 'p'):
                break
    
    txt = el.strip()
    parts = re.split(re.escape(label), txt, flags=re.I)
    if len(parts) >= 2:
        remaining = parts[1].strip()
        if remaining and remaining not in (':', '---'):
            return remaining
    
    return None


def get_character_info(char_id: str) -> Dict[str, Optional[str]]:
    params = {"id": char_id}
    try:
        resp = requests.get(BASE, params=params, timeout=10)
    except Exception as e:
        raise RuntimeError(f"Network error when fetching character page: {e}")
    if resp.status_code != 200:
        raise RuntimeError(f"Character page returned status {resp.status_code}")

    html = resp.text
    soup = BeautifulSoup(html, "html.parser")

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

    for tagname in ("h1", "h2", "h3", "title"):
        t = soup.find(tagname)
        if t and t.text.strip():
            text = t.text.strip()
            if len(text) <= 40:  # heuristic length
                result["name"] = text
                break

    if not result["name"]:
        result["name"] = _first_text_by_label(soup, "Character") or _first_text_by_label(soup, "Name")

    result["guild"] = _first_text_by_label(soup, "Guild")
    if not result["guild"]:
        # Only match guild in proper HTML structure, not in item filenames
        m = re.search(r"Guild[:\s]*<[^>]*>([^<]+)</", html, re.I)
        if m:
            guild_text = m.group(1).strip()
            # Filter out empty values and common placeholder text
            if guild_text and guild_text not in ('---', 'None', 'N/A'):
                result["guild"] = guild_text
    # Removed overly-greedy fallback regex that was matching item filenames like "GuildBigCloak-8May14.swf"

    result["class"] = _first_text_by_label(soup, "Class")

    level_text = _first_text_by_label(soup, "Level")
    if level_text:
        m = re.search(r"\d+", level_text)
        if m:
            result["level"] = m.group(0)

    result["experience"] = _first_text_by_label(soup, "Experience") or _first_text_by_label(soup, "EXP")

    result["health"] = _first_text_by_label(soup, "Health") or _first_text_by_label(soup, "HP")

    result["mana"] = _first_text_by_label(soup, "Mana") or _first_text_by_label(soup, "MP")

    for key in result:
        if key not in ("raw_html", "ccid"):
            val = result[key]
            result[key] = val.strip() if val and val.strip() else None

    return result


async def get_character_info_async(char_id: str, session: aiohttp.ClientSession) -> Dict[str, Optional[str]]:
    params = {"id": char_id}
    try:
        async with session.get(BASE, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Character page returned status {resp.status}")
            html = await resp.text()
    except asyncio.TimeoutError:
        raise RuntimeError(f"Timeout when fetching character page (server took too long)")
    except Exception as e:
        raise RuntimeError(f"Network error when fetching character page: {e}")

    soup = BeautifulSoup(html, "html.parser")

    result = {
        "name": None,
        "guild": None,
        "class": None,
        "level": None,
        "experience": None,
        "health": None,
        "mana": None,
        "ccid": None,
        "raw_html": html
    }

    # Extract ccid (Character ID) from the HTML
    ccid = extract_ccid(html)
    if ccid:
        result["ccid"] = ccid

    for tagname in ("h1", "h2", "h3", "title"):
        t = soup.find(tagname)
        if t and t.text.strip():
            text = t.text.strip()
            if len(text) <= 40:
                result["name"] = text
                break

    if not result["name"]:
        result["name"] = _first_text_by_label(soup, "Character") or _first_text_by_label(soup, "Name")

    result["guild"] = _first_text_by_label(soup, "Guild")
    if not result["guild"]:
        # Only match guild in proper HTML structure, not in item filenames
        m = re.search(r"Guild[:\s]*<[^>]*>([^<]+)</", html, re.I)
        if m:
            guild_text = m.group(1).strip()
            # Filter out empty values and common placeholder text
            if guild_text and guild_text not in ('---', 'None', 'N/A'):
                result["guild"] = guild_text
    # Removed overly-greedy fallback regex that was matching item filenames like "GuildBigCloak-8May14.swf"

    result["class"] = _first_text_by_label(soup, "Class")

    level_text = _first_text_by_label(soup, "Level")
    if level_text:
        m = re.search(r"\d+", level_text)
        if m:
            result["level"] = m.group(0)

    result["experience"] = _first_text_by_label(soup, "Experience") or _first_text_by_label(soup, "EXP")
    result["health"] = _first_text_by_label(soup, "Health") or _first_text_by_label(soup, "HP")
    result["mana"] = _first_text_by_label(soup, "Mana") or _first_text_by_label(soup, "MP")

    for key in result:
        if key not in ("raw_html", "ccid"):
            val = result[key]
            result[key] = val.strip() if val and val.strip() else None

    return result


def get_value_after_label(label) -> Union[str, Dict[str, str], None]:
    """
    Get the value after a label element.
    The value might be in the next sibling (text or link).
    Returns: string, dict with 'text' and 'url', or None
    """
    current = label.next_sibling
    
    while current:
        if isinstance(current, NavigableString):
            text = str(current).strip()
            if text and text != ':':
                return text
        elif hasattr(current, 'name'):
            if current.name == 'a':
                href = current.get('href', '')
                # URL-encode the path portion to handle spaces and special characters
                if href:
                    if '://' in href:
                        # Absolute URL - parse and encode only the path
                        parsed = urlparse(href)
                        # Encode the path, preserving forward slashes and query delimiters
                        encoded_path = quote(parsed.path, safe='/')
                        # Reconstruct the URL
                        href = urlunparse((
                            parsed.scheme,
                            parsed.netloc,
                            encoded_path,
                            parsed.params,
                            parsed.query,
                            parsed.fragment
                        ))
                    else:
                        # Relative URL - encode while preserving forward slashes
                        href = quote(href, safe='/')
                
                # Get ALL text content from link, including nested elements
                # Use separator='' to join without adding spaces, then clean up
                link_text = current.get_text(separator=' ', strip=True)
                # Clean up multiple spaces
                link_text = ' '.join(link_text.split())
                
                return {
                    'text': link_text,
                    'url': href
                }
            elif current.name == 'label':
                break
            elif current.name in ['br', 'div']:
                break
        
        current = current.next_sibling
    
    return None


async def scrape_character(username: str) -> Optional[Dict[str, Any]]:
    """
    Scrape character data from account.aq.com for /char command
    Combines FlashVars parsing with HTML label extraction for robustness
    
    Args:
        username: The character username to look up
        
    Returns:
        dict with character data or None if not found
    """
    url = f'https://account.aq.com/CharPage?id={username}'
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            
            if response.status_code == 404:
                return None
                
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract character name from h1
            name_elem = soup.find('h1')
            if not name_elem:
                print(f'Warning: No h1 element found for character {username}')
                return None
            
            name = name_elem.get_text(strip=True)
            
            tagline_elem = soup.find('h4')
            tagline = tagline_elem.get_text(strip=True) if tagline_elem else ''
            
            character_data: Dict[str, Any] = {
                'name': name,
                'tagline': tagline,
                'level': None,
                'class': None,
                'faction': None,
                'guild': None,
                'equipment': {},
                'cosmetics': {},
                'badge': None,
                'character_image': None,
                'badges_count': 0,
                'inventory_count': 0,
                'ccid': None,  # Character ID (unique identifier)
                'flashvars': {}  # Store all FlashVars for downstream consumers
            }
            
            # Parse FlashVars to get both equipped and cosmetics items
            flashvars_match = re.search(r'flashvars="([^"]+)"', response.text, re.IGNORECASE)
            if flashvars_match:
                flashvars_raw = flashvars_match.group(1)
                # Decode HTML entities
                flashvars_raw = flashvars_raw.replace('&amp;', '&')
                
                # Parse all FlashVars into a dict for any downstream tooling
                for param in flashvars_raw.split('&'):
                    if '=' in param:
                        key, value = param.split('=', 1)
                        if value and value != 'none':
                            # URL-decode the value so downstream consumers get clean strings
                            character_data['flashvars'][key] = unquote_plus(value)
                
                # Parse equipped items (names and files) - URL decode all values
                equipped_weapon = re.search(r'strWeaponName=([^&]+)', flashvars_raw)
                equipped_armor = re.search(r'strArmorName=([^&]+)', flashvars_raw)
                equipped_helm = re.search(r'strHelmName=([^&]+)', flashvars_raw)
                equipped_cape = re.search(r'strCapeName=([^&]+)', flashvars_raw)
                equipped_pet = re.search(r'strPetName=([^&]+)', flashvars_raw)
                equipped_misc = re.search(r'strMiscName=([^&]+)', flashvars_raw)

                if equipped_weapon and equipped_weapon.group(1):
                    character_data['equipment']['Weapon'] = unquote_plus(equipped_weapon.group(1))
                if equipped_armor and equipped_armor.group(1):
                    character_data['equipment']['Armor'] = unquote_plus(equipped_armor.group(1))
                if equipped_helm and equipped_helm.group(1):
                    character_data['equipment']['Helm'] = unquote_plus(equipped_helm.group(1))
                if equipped_cape and equipped_cape.group(1):
                    character_data['equipment']['Cape'] = unquote_plus(equipped_cape.group(1))
                if equipped_pet and equipped_pet.group(1):
                    character_data['equipment']['Pet'] = unquote_plus(equipped_pet.group(1))
                if equipped_misc and equipped_misc.group(1):
                    character_data['equipment']['Misc'] = unquote_plus(equipped_misc.group(1))
                
                # Parse cosmetics items (strCust prefix)
                cosmetic_weapon = re.search(r'strCustWeaponName=([^&]+)', flashvars_raw)
                cosmetic_armor = re.search(r'strCustArmorName=([^&]+)', flashvars_raw)
                cosmetic_helm = re.search(r'strCustHelmName=([^&]+)', flashvars_raw)
                cosmetic_cape = re.search(r'strCustCapeName=([^&]+)', flashvars_raw)
                cosmetic_pet = re.search(r'strCustPetName=([^&]+)', flashvars_raw)
                
                if cosmetic_weapon and cosmetic_weapon.group(1):
                    character_data['cosmetics']['Weapon'] = unquote_plus(cosmetic_weapon.group(1))
                if cosmetic_armor and cosmetic_armor.group(1):
                    character_data['cosmetics']['Armor'] = unquote_plus(cosmetic_armor.group(1))
                if cosmetic_helm and cosmetic_helm.group(1):
                    character_data['cosmetics']['Helm'] = unquote_plus(cosmetic_helm.group(1))
                if cosmetic_cape and cosmetic_cape.group(1):
                    character_data['cosmetics']['Cape'] = unquote_plus(cosmetic_cape.group(1))
                if cosmetic_pet and cosmetic_pet.group(1):
                    character_data['cosmetics']['Pet'] = unquote_plus(cosmetic_pet.group(1))
            
            # Parse labels using improved method (inspired by MultusAQW)
            # Try div.card-body label approach first (more robust)
            card_body = soup.find('div', class_='card-body')
            if card_body:
                labels = card_body.find_all('label')
                label_data = {}
                
                for label in labels:
                    label_text = label.get_text(strip=True).rstrip(':')
                    value = get_value_after_label(label)
                    
                    if value:
                        if isinstance(value, str):
                            label_data[label_text] = value
                        elif isinstance(value, dict):
                            label_data[label_text] = value
                
                # Map parsed data
                if 'Level' in label_data:
                    character_data['level'] = label_data['Level'] if isinstance(label_data['Level'], str) else label_data['Level']['text']
                if 'Class' in label_data:
                    character_data['class'] = label_data['Class']
                if 'Faction' in label_data:
                    character_data['faction'] = label_data['Faction'] if isinstance(label_data['Faction'], str) else label_data['Faction']['text']
                if 'Guild' in label_data:
                    character_data['guild'] = label_data['Guild'] if isinstance(label_data['Guild'], str) else label_data['Guild']['text']
            else:
                # Fallback to old method if card-body not found
                labels = soup.find_all('label')
                
                for label in labels:
                    label_text = label.get_text(strip=True).rstrip(':')
                    value = get_value_after_label(label)
                    
                    if not value:
                        continue
                    
                    if label_text == 'Level':
                        character_data['level'] = value if isinstance(value, str) else value['text']
                    elif label_text == 'Class':
                        if isinstance(value, dict):
                            character_data['class'] = {'text': value['text'], 'url': value['url']}
                        else:
                            character_data['class'] = value
                    elif label_text == 'Faction':
                        character_data['faction'] = value if isinstance(value, str) else value['text']
                    elif label_text == 'Guild':
                        character_data['guild'] = value if isinstance(value, str) else value['text']
            
            # Equipment and cosmetics are now parsed from FlashVars above
            
            badge_images = soup.find_all('img')
            for img in badge_images:
                src = img.get('src')
                if src and isinstance(src, str) and 'badges' in src:
                    if not src.startswith('http'):
                        src = 'https://game.aq.com' + src
                    character_data['badge'] = src
                    break
            
            # Note: Character visual image is dynamically generated by Flash/JavaScript
            # and cannot be extracted without browser automation (Playwright)
            # which requires system dependencies not available in this environment
            
            # Extract ccid using improved regex method
            ccid = extract_ccid(response.text)
            if ccid:
                character_data['ccid'] = ccid
                # Fetch badges count
                try:
                    badges_response = await client.get(
                        f'https://account.aq.com/CharPage/Badges?ccid={ccid}',
                        headers=headers,
                        timeout=10.0
                    )
                    if badges_response.status_code == 200:
                        try:
                            badges_data = badges_response.json()
                            if isinstance(badges_data, list):
                                character_data['badges_count'] = len(badges_data)
                            else:
                                print(f'Unexpected badges data format for {username}')
                        except Exception as json_err:
                            print(f'Error parsing badges JSON for {username}: {json_err}')
                except Exception as e:
                    print(f'Error fetching badges for {username}: {e}')
                
                # Fetch inventory count
                try:
                    inventory_response = await client.get(
                        f'https://account.aq.com/CharPage/Inventory?ccid={ccid}',
                        headers=headers,
                        timeout=10.0
                    )
                    if inventory_response.status_code == 200:
                        try:
                            inventory_data = inventory_response.json()
                            if isinstance(inventory_data, list):
                                character_data['inventory_count'] = len(inventory_data)
                                character_data['inventory_items'] = inventory_data  # Store full inventory for OCR matching
                            else:
                                print(f'Unexpected inventory data format for {username}')
                        except Exception as json_err:
                            print(f'Error parsing inventory JSON for {username}: {json_err}')
                except Exception as e:
                    print(f'Error fetching inventory for {username}: {e}')
            
            return character_data
        
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None
        raise
    except Exception as e:
        print(f'Error scraping character {username}: {e}')
        raise


if __name__ == "__main__":
    import sys
    import asyncio
    if len(sys.argv) >= 2:
        cid = sys.argv[1]
        async def test():
            async with aiohttp.ClientSession() as session:
                info = await get_character_info_async(cid, session)
                print("Name:", info['name'])
                print("Guild:", info['guild'])
        asyncio.run(test())
    else:
        print("Usage: python scraper.py <char_id>")
