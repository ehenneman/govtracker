import os
import requests
import anthropic
from flask import Flask, jsonify, render_template
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def fetch_federal_register():
    """Fetch latest 10 documents from the Federal Register API."""
    url = (
        "https://www.federalregister.gov/api/v1/documents.json"
        "?per_page=10&order=newest"
        "&fields[]=title"
        "&fields[]=agency_names"
        "&fields[]=abstract"
        "&fields[]=publication_date"
        "&fields[]=html_url"
    )
    response = requests.get(url)
    response.raise_for_status()
    return response.json()["results"]

def summarize(text):
    """Ask Claude to summarize a government document in plain English."""
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
        documents = fetch_federal_register()
        results = []
        for doc in documents:
            text = doc.get("abstract") or doc.get("title", "")
            summary = summarize(text)
            results.append({
                "title": doc.get("title"),
                "agencies": doc.get("agency_names", []),
                "date": doc.get("publication_date"),
                "url": doc.get("html_url"),
                "summary": summary
            })
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)