# FinBuild

FinBuild is a web-based educational platform designed to help users understand financial news by linking real-world articles with clear explanations of financial concepts. The system integrates news retrieval, natural language processing, and interactive learning components within a lightweight server-rendered architecture.

---

## 1. Project Purpose

Financial news often contains complex terminology that is difficult for beginners to understand. This project aims to improve financial literacy by providing contextual explanations of key terms directly within news articles. Users can explore current news while simultaneously learning the underlying financial concepts.

---

## 2. Key Features

### 2.1 News Explorer
- Search financial news using keywords, language, and optional date ranges.
- Results are retrieved via NewsAPI and rendered dynamically using HTMX.
- Pagination is supported through a “Next page” mechanism.

### 2.2 Internal Article Reader
- Displays selected articles within the application before redirecting to external sources.
- Shows title, source, date, and snippet.
- Automatically highlights detected financial terms within the text.
- Includes related concept suggestions and an interactive learning panel.

### 2.3 Learning Hub
- Provides structured explanations of financial concepts.
- Content is primarily sourced from a local dataset.
- Includes:
  - Definitions
  - Beginner explanations
  - Simple examples
  - Importance of the concept
- Supports search and browsing of concepts.

### 2.4 Quiz Functionality
- Each concept may include multiple-choice questions.
- Answers are submitted asynchronously.
- Immediate feedback is provided, including explanations.

### 2.5 Hybrid Financial Term Detection
- Uses spaCy and rule-based heuristics to extract candidate terms.
- Prioritises locally defined concepts.
- Falls back to Wikipedia for terms not present in the local dataset.
- Applies filtering to improve relevance and reduce incorrect matches.

### 2.6 Wikipedia Fallback
- Public Wikipedia endpoints are used to validate and retrieve concept summaries.
- No API key is required.
- Enables dynamic support for terms not predefined in the system.

### 2.7 Chart Doctor
- Accepts uploaded chart images (PNG/JPG).
- Attempts to extract key information using OpenCV and OCR.
- Allows user correction before retrieving related financial news.
- Degrades gracefully if OCR tools are unavailable.

---

## 3. Technology Stack

- **Backend:** FastAPI  
- **Frontend:** Jinja2 (server-rendered templates), HTML, CSS  
- **Dynamic Interaction:** HTMX  
- **NLP:** spaCy  
- **Image Processing:** OpenCV, NumPy, pytesseract  
- **HTTP Client:** httpx  
- **Configuration:** python-dotenv  
- **Server:** Uvicorn  

---

## 4. Project Structure
```app/
main.py
core/
clients/
services/
api/
web/
data/
templates/
```
Key components:
- `services/`: Business logic (news, learning, NLP, chart processing)
- `api/`: API endpoints
- `web/`: Page routes
- `data/`: Local concept dataset
- `templates/`: HTML templates and partials

---

## 5. Setup Instructions

### 5.1 Prerequisites
- Python 3.12+
- `uv` package manager , installed via terminal using pip install uv 
- NewsAPI key

Optional:
- Tesseract OCR (for improved chart processing)
- spaCy English model

---

### 5.2 Installation

Navigate to backend directory:

```bash
cd backend 
```

Install dependencies:
```
uv sync
```

Install spaCy model (optional):
```
uv run python -m spacy download en_core_web_sm
```

## 6. Environment Configuration

Create a .env file in the backend directory:
```
NEWSAPI_KEY=your_newsapi_key
NEWSAPI_BASE_URL=https://newsapi.org/v2
CACHE_TTL_SECONDS=120
```
## 7. Running the Application

Start the server:
```
uv run uvicorn app.main:app --reload
```
Access the application at:
```
http://127.0.0.1:8000
```
Health check:
```
http://127.0.0.1:8000/health
```
## 8. Main Routes
	•	/ – News Explorer
	•	/article – Article Reader
	•	/learn – Learning Hub
	•	/chart-doctor – Chart Doctor
	•	/news – JSON API endpoint

## 9. System Usage (Testing Guide)

To evaluate the system:

	1.	Open the homepage and perform a news search.
	2.	Apply filters such as keywords and date ranges.
	3.	Select an article to open the internal reader.
	4.	Click highlighted financial terms to load concept explanations.
	5.	Navigate to the Learning Hub and attempt quiz questions.
	6.	Upload an image in the Chart Doctor and test detection workflow.