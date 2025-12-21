"""
Web search script - run this and paste the output back to me
Usage: python web_search.py "your search query"
"""
import sys
import subprocess
import json

def search(query):
    # Use curl to search DuckDuckGo HTML
    url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"
    
    cmd = [
        'curl', '-s', url,
        '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        '--max-time', '15'
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if result.returncode == 0:
            html = result.stdout
            
            # Extract results from HTML
            results = []
            
            # Find result links
            import re
            # Pattern for DuckDuckGo result snippets
            snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
            titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html, re.DOTALL)
            urls = re.findall(r'class="result__url"[^>]*>(.*?)</a>', html, re.DOTALL)
            
            for i in range(min(len(titles), 10)):
                title = re.sub(r'<[^>]+>', '', titles[i]).strip() if i < len(titles) else ""
                snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip() if i < len(snippets) else ""
                url = urls[i].strip() if i < len(urls) else ""
                
                if title:
                    results.append({
                        'title': title,
                        'url': url,
                        'snippet': snippet[:300]
                    })
            
            return results
    except Exception as e:
        print(f"Error: {e}")
    
    return []

if __name__ == "__main__":
    if len(sys.argv) < 2:
        query = "yt-dlp youtube 403 forbidden fix december 2024 cobalt api"
    else:
        query = " ".join(sys.argv[1:])
    
    print(f"Searching: {query}\n")
    print("="*60)
    
    results = search(query)
    
    if results:
        for i, r in enumerate(results, 1):
            print(f"\n{i}. {r['title']}")
            print(f"   URL: {r['url']}")
            print(f"   {r['snippet']}")
    else:
        print("No results found or search failed")
    
    print("\n" + "="*60)
    print("Copy everything above and paste it back to me!")
