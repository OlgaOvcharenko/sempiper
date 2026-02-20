# Cache Design

**Always apply this rule**

Two-tier caching system for pipeline compilation and execution results.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      CacheService                           │
│  ┌───────────────────┐    ┌───────────────────────────────┐ │
│  │   Memory Cache    │    │        File Cache             │ │
│  │  (single-key)     │    │    (persistent, unbounded)    │ │
│  │                   │    │                               │ │
│  │  Only stores      │    │  .cache/                      │ │
│  │  entries for the  │    │  ├── compile/{key}.json       │ │
│  │  CURRENT hash     │    │  ├── execute/{key}.json       │ │
│  │                   │    │  └── svg/{key}.svg            │ │
│  └───────────────────┘    └───────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Key Design: Single-Key Memory Cache

**Memory is bounded** by only keeping entries for ONE cache key (hash) at a time:

- When you `set()` with a **different** cache_key, all existing memory entries are **cleared**
- When you `get()` with a **different** cache_key, it returns `None` (no implicit switch)
- This ensures memory stays small for demo purposes (no LRU, no TTL needed)

This reflects typical demo usage: working on one pipeline at a time. Switching pipelines clears memory but files remain on disk.

## Cache Key Generation

```python
cache_key = SHA256(script + "|" + temperature + "|" + llm_name)[:16]
```

Same inputs always produce the same 16-char hex key.

## Operations

| Operation | Format | Contents |
|-----------|--------|----------|
| `compile` | JSON | Compiled graph (nodes, edges) |
| `execute` | JSON | Execution events (SSE replay data) |
| `svg` | SVG | Native skrub graph visualization |

## Data Flow

**On `get(cache_key, operation)`:**
1. Check memory → if current_key matches AND operation exists, return it
2. Check file → if exists, load it, populate memory (may clear if different key), return it
3. Return `None`

**On `set(cache_key, operation, value)`:**
1. If cache_key differs from current_key → clear all memory entries
2. Store in memory
3. Write to file

**On `clear()`:**
1. Clear all memory entries and reset current_key
2. Delete all files in `.cache/` subdirectories

## Files

| File | Purpose |
|------|---------|
| `cache_service.py` | Main service orchestrating both tiers |
| `memory_cache.py` | Thread-safe single-key in-memory cache |
| `cache_format.py` | Enum for file formats (JSON, SVG, TEXT, BINARY) |
| `utils.py` | Cache key generation via SHA256 |

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/cache/svg` | POST | Retrieve cached SVG |
| `/api/cache` | DELETE | Clear all cache (memory + files) |

## Important Notes

1. **Memory is volatile** — cleared on restart or key change
2. **Files are persistent** — survive restarts, must be explicitly cleared
3. **Single-key constraint** — memory only holds one pipeline's data at a time
4. **Thread-safe** — memory cache uses locks for concurrent access
5. **Format matters** — same key+operation can have different formats (e.g., JSON vs SVG)
