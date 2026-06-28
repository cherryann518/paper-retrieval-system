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

---

## OpenAlex

**Endpoint:** `GET https://api.openalex.org/works`

**Authentication:** None required. No API key. Optional `mailto=` query parameter (set `OPENALEX_MAILTO` in `.env`) for the [polite pool](https://docs.openalex.org/how-to-use-the-api/rate-limits-and-authentication) and higher rate limits.

### Input parameters

| Parameter | Type | Required | Notes |
|-----------|------|----------|-------|
| `search` | string | yes* | Full-text search |
| `filter` | string | no | e.g. `publication_year:2020` |
| `per_page` | int | no | 1–200 (default 25) |
| `cursor` | string | no | `*` for first page; use `meta.next_cursor` |
| `select` | string | no | Comma-separated fields |
| `mailto` | string | no | Contact email for polite pool |

### Example request

```
GET /works?search=retrieval+augmented+generation&per_page=25&cursor=*&filter=publication_year:2020&mailto=you@example.com
```

### Example response (abbreviated)

```json
{
  "meta": { "count": 100, "next_cursor": "abc123" },
  "results": [
    {
      "id": "https://openalex.org/W2741809807",
      "doi": "https://doi.org/10.5555/1234567",
      "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
      "publication_year": 2020,
      "abstract_inverted_index": { "Large": [0], "language": [1] },
      "authorships": [{ "author": { "display_name": "Patrick Lewis" } }],
      "cited_by_count": 4200,
      "ids": { "openalex": "https://openalex.org/W2741809807", "arxiv": "https://arxiv.org/abs/2005.11401" }
    }
  ]
}
```

### Rate limits

- Default pool: ~1 req/s without `mailto`.
- Polite pool with `mailto`: significantly higher (see OpenAlex docs).
- Raw responses cached in SQLite shards with configurable TTL (`cache_ttl_days`).
