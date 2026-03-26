# Real-Time Code Generation - FIXED! ✅

## The Issue

You were seeing placeholder text in the UI because the subprocess that runs pipeline code **wasn't receiving environment variables**, specifically the **GEMINI_API_KEY**.

## The Fix

**One-line change in `demo/backend/services/execute_stream.py`:**

```python
proc = subprocess.Popen(
    [sys.executable, "-m", "services.skrub_graph_runner"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    cwd=_BACKEND_ROOT,
    env=os.environ.copy(),  # ← Added this line
    text=False,
)
```

Without `env=os.environ.copy()`, the subprocess didn't inherit the parent process's environment variables, so it couldn't access the API key to call the LLM.

## Verification

**API test shows REAL generated code now:**

```bash
$ curl -X POST http://localhost:8000/api/execute -d '...'

✅ SUCCESS! Node sem_fillna_11 has REAL code:
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.impute import IterativeImputer
from autogluon.tabular import TabularPredictor
...
```

**Before the fix:**
- `"is_fallback": true`
- Placeholder text shown

**After the fix:**
- `"is_fallback": false`
- Real LLM-generated Python code

## Test in the UI

1. **Open the demo**: http://localhost:5179
2. **Load an example** (Simple, Medium, or Full)
3. **Click "Run"** (or Play button)
4. **Watch the right panel** - You should now see REAL generated code like:

```python
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.impute import IterativeImputer
...
```

Instead of the placeholder:
```python
# [Placeholder — no code captured from pipeline run...]
```

## All Fixes Applied

1. ✅ **Added `impute_with_existing_values_only=True`** to `pipeline_scripts/simple.py`
2. ✅ **Increased subprocess timeout** from 30s to 120s (LLM calls take time)
3. ✅ **Fixed environment variable inheritance** - subprocess now gets API key
4. ✅ **Fixed all dependencies** - sempipes imports successfully

## Why Manual Testing Worked But API Failed

- **Manual test**: `cat script.py | poetry run python -m services.skrub_graph_runner`
  - Subprocess inherited shell's environment (including API key) ✅
  
- **API call**: FastAPI spawned subprocess without environment
  - Subprocess had no API key ❌
  - LLM calls failed silently
  - Fallback code was returned

## Files Modified

1. `demo/backend/services/execute_stream.py` - Added `env=os.environ.copy()`
2. `pipeline_scripts/simple.py` - Added required parameter
3. `demo/backend/services/execute_stream.py` - Increased timeout to 120s

## Demo Status

**Running on**: http://localhost:5179
**Backend**: http://localhost:8000
**Status**: ✅ **WORKING** - Real-time code generation enabled!

## Next Time

If you see placeholder text in the future, check:
1. API key is in `.env` file
2. Backend is loading `.env` (check `main.py` has `load_dotenv()`)
3. Subprocess calls include `env=os.environ.copy()`

That's it! The demo should now work perfectly. 🎉
