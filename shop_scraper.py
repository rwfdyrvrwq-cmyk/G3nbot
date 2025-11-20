import httpx
from bs4 import BeautifulSoup
from typing import Optional, List, Dict, Any

async def scrape_shop_items(shop_name: str) -> Optional[Dict[str, Any]]:
    """
    Scrape items from an AQW Wiki shop page.
    
    Args:
        shop_name: The shop name to look up
        
    Returns:
        dict with shop items data or None if not found
    """
    import re
    
    slug = shop_name.replace("'", "-")
    slug = slug.replace(' ', '-')
    slug = re.sub(r'[^a-zA-Z0-9-]', '', slug)
    slug = slug.lower()
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')

    # Guard against empty slugs (e.g., "???", "🎮") to avoid fetching the wiki homepage
    if not slug:
        return None

    url = f'http://aqwwiki.wikidot.com/{slug}'
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers, follow_redirects=True)
            
            if response.status_code != 200:
                return None
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            page_content = soup.find('div', {'id': 'page-content'})
            if not page_content:
                return None
            
            content_text = page_content.get_text(strip=True)
            if 'does not exist' in content_text.lower() or len(content_text) < 50:
                return None
            
            title_elem = soup.find('div', {'id': 'page-title'})
            title = title_elem.get_text(strip=True) if title_elem else shop_name
            
            shop_data = {
                'title': title,
                'url': url,
                'items': []
            }
            
            tables = page_content.find_all('table')
            
            for table in tables:
                rows = table.find_all('tr')
                
                if not rows:
                    continue
                
                headers = rows[0].find_all(['th', 'td'])
                header_text = [h.get_text(strip=True).lower() for h in headers]
                
                if 'name' not in header_text:
                    continue
                
                name_index = header_text.index('name') if 'name' in header_text else None
                price_index = header_text.index('price') if 'price' in header_text else None
                
                for row in rows[1:]:
                    cells = row.find_all('td')
                    
                    if len(cells) < 2:
                        continue
                    
                    item_data = {}
                    
                    if name_index is not None and name_index < len(cells):
                        name_cell = cells[name_index]
                        item_name = name_cell.get_text(strip=True)
                        
                        if item_name and len(item_name) > 0:
                            item_data['name'] = item_name
                            
                            link = name_cell.find('a')
                            if link and link.get('href'):
                                href = link['href']
                                if isinstance(href, str) and href.startswith('/'):
                                    item_data['url'] = f"http://aqwwiki.wikidot.com{href}"
                    
                    if price_index is not None and price_index < len(cells):
                        price_text = cells[price_index].get_text(strip=True)
                        if price_text:
                            item_data['price'] = price_text
                    
                    if 'name' in item_data:
                        shop_data['items'].append(item_data)
            
            return shop_data if shop_data['items'] else None
            
    except Exception as e:
        print(f'Error scraping shop page: {e}')
        return None
