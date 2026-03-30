import os
import requests
import anthropic
import xml.etree.ElementTree as ET
from flask import Flask, jsonify, render_template
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def fetch_federal_register():
    """Fetch latest 5 documents from the Federal Register API."""
    url = (
        "https://www.federalregister.gov/api/v1/documents.json"
        "?per_page=5&order=newest"
        "&fields[]=title"
        "&fields[]=agency_names"
        "&fields[]=abstract"
        "&fields[]=publication_date"
        "&fields[]=html_url"
    )
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    docs = response.json()["results"]
    return [{
        "title": d.get("title"),
        "agency": ", ".join(d.get("agency_names", [])),
        "date": d.get("publication_date"),
        "url": d.get("html_url"),
        "text": d.get("abstract") or d.get("title", ""),
        "source": "Federal Register"
    } for d in docs]


def fetch_fda():
    """Fetch latest FDA drug and food enforcement reports."""
    url = "https://api.fda.gov/drug/enforcement.json?limit=5&sort=report_date:desc"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    docs = response.json()["results"]
    return [{
        "title": f"Recall: {d.get('product_description', 'Unknown product')[:80]}",
        "agency": "FDA",
        "date": d.get("report_date", ""),
        "url": "https://www.fda.gov/safety/recalls-market-withdrawals-safety-alerts",
        "text": f"Reason: {d.get('reason_for_recall', '')}. Product: {d.get('product_description', '')}",
        "source": "FDA"
    } for d in docs]


def fetch_sec():
    """Fetch latest SEC filings from EDGAR."""
    url = "https://efts.sec.gov/LATEST/search-index?q=%22material+event%22&dateRange=custom&startdt=2024-01-01&forms=8-K&hits.hits._source=period_of_report,display_names,file_date,period_of_report&hits.hits.total=5"
    # Use the simpler EDGAR full-text search instead
    url = "https://efts.sec.gov/LATEST/search-index?forms=8-K&hits.hits.total=5"
    rss_url = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&dateb=&owner=include&count=5&search_text=&output=atom"
    response = requests.get(rss_url, timeout=10, headers={"User-Agent": "GovTracker contact@govtracker.com"})
    response.raise_for_status()
    root = ET.fromstring(response.content)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall("atom:entry", ns)
    results = []
    for entry in entries[:5]:
        title = entry.findtext("atom:title", default="SEC Filing", namespaces=ns)
        link = entry.find("atom:link", ns)
        url = link.get("href", "https://sec.gov") if link is not None else "https://sec.gov"
        date = entry.findtext("atom:updated", default="", namespaces=ns)[:10]
        summary = entry.findtext("atom:summary", default=title, namespaces=ns)
        results.append({
            "title": title,
            "agency": "SEC",
            "date": date,
            "url": url,
            "text": summary[:500],
            "source": "SEC"
        })
    return results


def fetch_rss(url, agency_name, source_name):
    """Generic RSS feed fetcher for CDC, NASA etc."""
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    items = root.findall(".//item")[:5]
    results = []
    for item in items:
        title = item.findtext("title", default="Update")
        link = item.findtext("link", default="")
        date = item.findtext("pubDate", default="")[:16]
        description = item.findtext("description", default=title)
        # Strip HTML tags simply
        import re
        description = re.sub(r'<[^>]+>', '', description)
        results.append({
            "title": title,
            "agency": agency_name,
            "date": date,
            "url": link,
            "text": description[:500],
            "source": source_name
        })
    return results


def summarize(text):
    """Ask Claude to summarize a government document in plain English."""
    if not text or len(text.strip()) < 50:
        return "No detailed summary available - click the link to read the full document."

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=150,
        messages=[{
            "role": "user",
            "content": (
                "Summarize this US government update in 2 plain-English sentences "
                "that anyone can understand. Be concise and factual.\n\n"
                f"Document: {text}"
            )
        }]
    )
    return message.content[0].text


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/updates")
def updates():
    try:
        all_docs = []

        # Fetch from all sources, skip any that fail
        fetchers = [
            lambda: fetch_federal_register(),
            lambda: fetch_fda(),
            lambda: fetch_sec(),
            lambda: fetch_rss(
                "https://tools.cdc.gov/api/v2/resources/media/316422.rss",
                "CDC", "CDC"
            ),
            lambda: fetch_rss(
                "https://www.nasa.gov/news-release/feed/",
                "NASA", "NASA"
            ),
        ]

        for fetcher in fetchers:
            try:
                all_docs.extend(fetcher())
            except Exception as e:
                print(f"Fetcher failed: {e}")
                continue

        # Summarize each document
        results = []
        for doc in all_docs:
            try:
                summary = summarize(doc["text"])
                results.append({
                    "title": doc["title"],
                    "agency": doc["agency"],
                    "date": doc["date"],
                    "url": doc["url"],
                    "summary": summary,
                    "source": doc["source"]
                })
            except Exception as e:
                print(f"Summarize failed: {e}")
                continue

        return jsonify(results)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)