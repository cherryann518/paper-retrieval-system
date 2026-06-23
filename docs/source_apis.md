# Source API contracts

This document describes input/output payloads for each retrieval source.

## Semantic Scholar

**Endpoint:** `GET https://api.semanticscholar.org/graph/v1/paper/search`

### Input parameters

| Parameter | Type | Required | Notes |
|-----------|------|----------|-------|
| `query` | string | yes | Plain-text search; use quotes for phrases |
| `limit` | int | no | 1–100 (default 100) |
| `offset` | int | no | Pagination start (max ~1000 total) |
| `fields` | string | no | Comma-separated field list |
| `year` | string | no | e.g. `2023-` or `2020-2024` |
| `fieldsOfStudy` | string | no | e.g. `Computer Science` |
| `minCitationCount` | int | no | Minimum citations filter |

### Example request

```
GET /graph/v1/paper/search?query=retrieval+augmented+generation&limit=10&offset=0&fields=paperId,title,authors,year,abstract,externalIds,citationCount,venue,openAccessPdf
```

### Example response

```json
{
  "total": 1234,
  "offset": 0,
  "data": [
    {
      "paperId": "abc123",
      "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
      "authors": [{"authorId": "123", "name": "Patrick Lewis"}],
      "year": 2020,
      "abstract": "...",
      "externalIds": {"DOI": "10.5555/...", "ArXiv": "2005.11401"},
      "citationCount": 4200,
      "venue": "NeurIPS",
      "openAccessPdf": {"url": "https://..."}
    }
  ]
}
```

### Rate limits

- With API key: 1 request/second
- Without key: shared public limit; expect 429 under load

---

## arXiv

**Endpoint:** `GET http://export.arxiv.org/api/query`

### Input parameters

| Parameter | Type | Required | Notes |
|-----------|------|----------|-------|
| `search_query` | string | no* | Prefix syntax: `all:`, `ti:`, `abs:`, `au:`, `cat:` |
| `id_list` | string | no* | Comma-separated arXiv IDs |
| `start` | int | no | 0-based offset (default 0) |
| `max_results` | int | no | Results per page (default 10) |
| `sortBy` | string | no | `relevance`, `lastUpdatedDate`, `submittedDate` |
| `sortOrder` | string | no | `ascending` or `descending` |

\* At least one of `search_query` or `id_list` is required.

### Search query prefixes

| Prefix | Field |
|--------|-------|
| `ti` | Title |
| `au` | Author |
| `abs` | Abstract |
| `cat` | Category |
| `all` | All fields |

### Example request

```
GET /api/query?search_query=all:retrieval+augmented+generation&start=0&max_results=10&sortBy=relevance&sortOrder=descending
```

### Example response (Atom XML)

Each `<entry>` contains:

- `id` — abstract page URL (`http://arxiv.org/abs/2005.11401v1`)
- `title` — paper title
- `summary` — abstract
- `published` — original submission date
- `updated` — version submission date
- `author` — one or more author elements
- `arxiv:primary_category` — e.g. `cs.CL`
- `link[rel=related type=application/pdf]` — PDF URL

Feed metadata includes `opensearch:totalResults`, `opensearch:startIndex`, `opensearch:itemsPerPage`.

### Rate limits

Polite use: ~1 request per 3 seconds. Cache responses aggressively.
