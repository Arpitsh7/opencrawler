from scraper import _scrape_sync

print("Testing scraper...")
try:
    result = _scrape_sync("https://quotes.toscrape.com")
    print("SUCCESS!")
    print(result[:500])
except Exception as e:
    import traceback
    print("FAILED:")
    traceback.print_exc()