"""
Web search script with fetch - run this and paste the output back to me
Usage: 
  python web_search.py "your search query"
  python web_search.py fetch "https://url-to-fetch"
"""
import sys
import subprocess
import re

def search(query):
    """Search DuckDuckGo"""
    url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"
    
    cmd = [
        'curl', '-s', url,
        '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        '--max-time', '15'
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=20)
        if result.returncode == 0:
            html = result.stdout.decode('utf-8', errors='ignore')
            
            results = []
            snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
            titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html, re.DOTALL)
            urls = re.findall(r'class="result__url"[^>]*>(.*?)</a>', html, re.DOTALL)
            
            for i in range(min(len(titles), 10)):
                title = re.sub(r'<[^>]+>', '', titles[i]).strip() if i < len(titles) else ""
                snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip() if i < len(snippets) else ""
                url_text = urls[i].strip() if i < len(urls) else ""
                
                if title:
                    results.append({
                        'title': title,
                        'url': url_text,
                        'snippet': snippet[:400]
                    })
            
            return results
    except Exception as e:
        print(f"Search error: {e}")
    
    return []

def fetch(url):
    """Fetch URL content"""
    cmd = [
        'curl', '-s', '-L', url,
        '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        '--max-time', '20'
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=25)
        if result.returncode == 0:
            content = result.stdout.decode('utf-8', errors='ignore')
            
            # Remove HTML tags for readability
            text = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text)
            text = text.strip()
            
            # Return first 5000 chars
            return text[:5000]
    except Exception as e:
        print(f"Fetch error: {e}")
    
    return None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print('  python web_search.py "search query"')
        print('  python web_search.py fetch "https://url"')
        sys.exit(1)
    
    if sys.argv[1].lower() == "fetch" and len(sys.argv) >= 3:
        # Fetch mode
        url = sys.argv[2]
        print(f"Fetching: {url}\n")
        print("="*60)
        
        content = fetch(url)
        if content:
            print(content)
        else:
            print("Failed to fetch URL")
        
        print("\n" + "="*60)
    else:
        # Search mode
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
            print("No results found")
        
        print("\n" + "="*60)
    
    print("Copy everything above and paste it back to me!")
