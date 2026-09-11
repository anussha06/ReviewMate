# 🤖 ReviewMate AI

> **Agentic GitHub Pull Request Code Review & Repository Analysis System**

ReviewMate AI is an autonomous, multi-agent code review system that automates the analysis of GitHub Pull Requests. It builds a tightly bounded context from diffs and dependencies, scrubs sensitive secrets before prompting, coordinates four specialized LLM agents powered by Groq, deduplicates overlapping findings, generates actionable recommendations, and posts comprehensive review summaries directly to GitHub PR discussions.

---

## 📋 Problem Statement

Code reviews are essential for software quality and security, but manual reviews are often slow, inconsistent, and overburdened by high PR volumes. Key challenges include:
- **Reviewer Fatigue & Blind Spots:** Overlooking subtle logic edge cases, concurrency hazards, or non-obvious SQL/command injection vectors.
- **Context Overload:** LLM context windows can be easily overwhelmed by multi-thousand-line repositories or unconstrained diffs.
- **Credential & Secret Leaks:** Transmitting raw source files containing credentials, tokens, or API keys directly to third-party LLMs presents significant security exposure.
- **Scattered & Noisy Feedback:** Uncoordinated AI tools dump duplicate comments or disjointed nitpicks without clear severity or an overall merge recommendation.

---

## 💡 Proposed Solution

**ReviewMate AI** solves these challenges through an orchestrated, security-first multi-agent architecture:
1. **Targeted Bounded Context:** Extracts only changed files, patches, direct imports/dependencies, test files, and configuration files, enforcing a token budget to eliminate noise and prevent LLM context exhaustion.
2. **Zero-Leak Secret Redaction:** Pre-scans all diffs and text for GitHub PATs, AWS access keys, Groq/OpenAI tokens, JWTs, private keys, and passwords before anything is transmitted to the LLM.
3. **Four Independent Domain Agents:** Divides the review burden among four specialized agents (Bug, Security, Quality, Performance) that evaluate code concurrently and produce structured JSON findings.
4. **Intelligent Deduplication & Synthesis:** Merges overlapping findings across agents, normalizes severity (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`), preserves confidence, and determines an authoritative verdict: `APPROVE`, `REQUEST_CHANGES`, or `COMMENT`.
5. **Real GitHub Integration & Persistence:** Allows developers to post formatted reviews directly back to GitHub PR conversations and archives all reviews in a local SQLite database.

---

## 🏗️ System Architecture & Workflow

```
       +-------------------------------------------------------------+
       |                  User pastes GitHub PR URL                  |
       +-------------------------------------------------------------+
                                      |
                                      v
       +-------------------------------------------------------------+
       |               GitHub Client (httpx async)                   |
       |  - Validates PR URL (owner/repo/pull/number)                |
       |  - Fetches PR metadata & changed file patches               |
       +-------------------------------------------------------------+
                                      |
                                      v
       +-------------------------------------------------------------+
       |                  Secret Scanner Engine                      |
       |  - Redacts PATs, AWS keys, JWTs, Private Keys, Passwords   |
       +-------------------------------------------------------------+
                                      |
                                      v
       +-------------------------------------------------------------+
       |                     Context Manager                         |
       |  - Detects direct imports & dependencies                    |
       |  - Identifies relevant test & config files touched          |
       |  - Enforces bounded token budget (tiktoken cl100k_base)     |
       +-------------------------------------------------------------+
                                      |
         +----------------------------+----------------------------+
         |                            |                            |
         v                            v                            v
   +------------+              +--------------+              +-------------+
   | Bug Agent  |              |Security Agent|              |Quality Agent| ... + Performance
   +------------+              +--------------+              +-------------+
         |                            |                            |
         +----------------------------+----------------------------+
                                      |
                                      v
       +-------------------------------------------------------------+
       |                  Orchestrator Engine                        |
       |  - Validates JSON schema from each agent                    |
       |  - Deduplicates overlapping findings across agents          |
       |  - Normalizes severity & confidence                         |
       |  - Determines recommendation (APPROVE / REQUEST_CHANGES)   |
       |  - Generates GitHub Markdown summary                        |
       +-------------------------------------------------------------+
                                      |
                    +-----------------+-----------------+
                    |                                   |
                    v                                   v
       +--------------------------+       +--------------------------+
       |   SQLite Review Store    |       |   Web UI & GitHub Post   |
       | (Review History Database)|       | (Live review & comments) |
       +--------------------------+       +--------------------------+
```

---

## 👥 The Four Specialized Agents

| Agent | Focus Area | What It Scrutinizes |
| :--- | :--- | :--- |
| **Bug Agent** | Logic & Correctness | Boolean inversions, off-by-one errors, null/None dereferences, unhandled exceptions, type mismatches, race conditions. |
| **Security Agent** | OWASP Top 10 & AppSec | SQL/OS injection, XSS, broken auth/authz, IDOR, SSRF, insecure deserialization, path traversal, weak crypto. |
| **Quality Agent** | Craftsmanship & Architecture | DRY/SOLID violations, excessive cyclomatic complexity, poor naming, testing coverage gaps, missing error handling. |
| **Performance Agent** | Efficiency & Scaling | $O(N^2)$ algorithmic loops, database N+1 queries, unindexed searches, memory leaks, blocking I/O on async event loops. |

---

## 🛠️ Tech Stack

- **Backend Framework:** FastAPI (Python 3.9+)
- **ASGI Web Server:** Uvicorn
- **LLM Engine:** Groq API SDK (Model: `openai/gpt-oss-120b`, configurable)
- **Token Estimation:** `tiktoken` (`cl100k_base`)
- **HTTP Client:** `httpx` (async client with timeout management)
- **Database:** SQLite3 with indexed relational review records
- **Data Validation:** Pydantic v2
- **Testing:** Pytest & pytest-asyncio
- **Frontend:** Single-page Vanilla HTML5, modern CSS3 (clean light theme with Indigo accent), and plain asynchronous JavaScript (Zero external framework dependencies, no Streamlit).

---

## 📂 Project Structure

```
reviewmate-ai/
├── .env.example              # Environment variables template
├── .gitignore                # Git ignore rules
├── README.md                 # Complete documentation
├── requirements.txt          # Python dependencies
├── reviewmate.db             # Local SQLite database (auto-created on startup)
├── app/
│   ├── __init__.py
│   ├── config.py             # Settings loader with secret masking
│   ├── github_client.py      # GitHub PR URL parsing, diff retrieval, comment posting
│   ├── context_manager.py    # Bounded context builder, import detection, token estimation
│   ├── secret_scanner.py     # Multi-pattern regex engine for redacting sensitive secrets
│   ├── llm_client.py         # Groq API wrapper with structured JSON extraction
│   ├── orchestrator.py       # Multi-agent coordination, deduplication, recommendation logic
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py           # Base agent class with schema validation & hedging
│   │   ├── bug_agent.py      # Logic flaws and runtime errors
│   │   ├── security_agent.py # Security vulnerabilities and OWASP Top 10
│   │   ├── quality_agent.py  # Code smells and maintainability
│   │   └── performance_agent.py # Complexity and resource efficiency
│   └── db/
│       ├── __init__.py
│       ├── models.py         # Pydantic domain models (Finding, ReviewRecord, etc.)
│       └── review_store.py   # SQLite CRUD repository for review history
├── static/
│   ├── index.html            # Clean, modern single-page UI
│   ├── style.css             # Light theme stylesheet (off-white & indigo accent)
│   └── app.js                # Frontend controller & API fetch integration
└── tests/
    ├── test_secret_scanner.py   # Verification of credential redaction
    ├── test_context_manager.py  # Token budgeting and dependency detection
    ├── test_github_client.py    # URL parsing, PR metadata, and posting errors
    ├── test_orchestrator.py     # Deduplication, scoring, and markdown generation
    ├── test_review_store.py     # SQLite persistence lifecycle
    └── test_e2e_pipeline.py     # Full FastAPI API lifecycle & static file tests
```

---

## ⚙️ Setup & Environment Configuration

### 1. Prerequisites
- Python 3.9 or higher
- Git

### 2. Clone or Navigate to Project
```bash
cd reviewmate-ai
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Edit `.env` and fill in your keys:
```env
# Groq API Key (get from https://console.groq.com)
GROQ_API_KEY=your_groq_api_key_here

# Groq Model (default: openai/gpt-oss-120b)
GROQ_MODEL=openai/gpt-oss-120b

# GitHub Personal Access Token (classic with repo scope or fine-grained Pull Requests: Read & Write)
# Optional for reading public PRs, required for posting review comments
GITHUB_TOKEN=your_github_token_here

# Server host & port
HOST=127.0.0.1
PORT=8000
```

> **Note:** Never commit real API keys or tokens into version control. ReviewMate AI's `config.py` masks all secrets and will never print them to logs or UI.

---

## 🚀 How to Run

Start the FastAPI application with Uvicorn:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Once running, open your browser and navigate to:
```
http://localhost:8000
```
This single FastAPI server serves both the REST API and the static frontend UI.

---

## 🧪 How to Test

Run the complete automated test suite:

```bash
python -m pytest tests/ -v
```

All 31 unit, integration, and end-to-end tests run with mocked network calls so no live GitHub tokens or Groq quotas are consumed during testing.

---

## 🎬 How to Perform the Complete Demo

1. Start the server:
   ```bash
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
   ```
2. Open `http://localhost:8000` in your web browser.
3. Paste any public GitHub Pull Request URL (or click one of the quick example chips such as `pallets/flask#5000`).
4. Click **"Analyze PR"**.
   - Watch the live progress indicator as ReviewMate fetches PR metadata, changed files, and git diffs.
   - Observe the bounded context summary (files included, token count meter).
   - Watch the four agent status chips (Bug, Security, Quality, Performance).
   - Review the final recommendation banner (`APPROVE`, `REQUEST_CHANGES`, or `COMMENT`).
   - Filter findings by severity (Critical, High, Medium, Low) or by agent.
5. Click **"Post Review to GitHub"** to publish the formatted review markdown directly as a comment on the PR (requires `GITHUB_TOKEN` with write access).
6. Click **"Review History"** in the top navigation to view previous reviews stored in SQLite and reload any past review with one click.

---

## ⚠️ Documented Limitations

1. **Advisory Hypotheses:** LLM findings are heuristic hypotheses and not mathematical proofs. All findings should undergo human verification.
2. **Static Context Boundary:** ReviewMate reviews changed files, direct imports, and bounded context; it does not execute code or run test suites dynamically.
3. **Large Repository Truncation:** To adhere to model token limits, pull requests touching tens of thousands of lines are bounded to the most critical diffs.
4. **GitHub API Rate Limits:** Unauthenticated GitHub API calls are limited to 60 requests/hour by GitHub. Setting `GITHUB_TOKEN` increases this limit to 5,000 requests/hour.
5. **False Positives/Negatives:** While the multi-agent design with cross-agent deduplication substantially reduces noise, false positives or missed defects are still possible.

---

## 🔮 Future Scope

- **Inline PR Comments:** Posting specific review comments directly anchored to exact diff line numbers via GitHub Pull Request Reviews API.
- **Automated Webhook Integration:** Running ReviewMate automatically as a GitHub App or Webhook on every `pull_request.opened` event.
- **CI/CD Actions:** Packaging ReviewMate as a reusable GitHub Action (`uses: reviewmate-ai/action@v1`).
- **Additional Language Parsers:** AST-based dependency graphs for Rust, Go, Java, and C++ to enhance supplemental context selection.
- **Historical Learning:** Indexing past repository reviews to adapt to team-specific style conventions and review policies.
- **Configurable Review Policies:** Allowing repository owners to configure custom severity thresholds, blocking rules, and compliance requirements via `.reviewmate.yml`.
