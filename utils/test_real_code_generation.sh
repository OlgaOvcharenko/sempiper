#!/bin/bash
# Quick test to verify real-time code generation is working

echo "🧪 Testing Real-Time Code Generation..."
echo "========================================"
echo ""

response=$(curl -s -X POST http://localhost:8000/api/execute \
  -H "Content-Type: application/json" \
  -d '{
    "input_code": "import os\nos.environ.setdefault(\"SCIPY_ARRAY_API\", \"1\")\n\nimport skrub\nimport sempipes\n\ndataset = skrub.datasets.fetch_credit_fraud()\nproducts = skrub.var(\"products\", dataset.products)\nproducts_small = products.skb.subsample(n=30, how=\"random\")\n\nproducts_filled = products_small.sem_fillna(\n    target_column=\"make\",\n    nl_prompt=\"Infer manufacturer\",\n    impute_with_existing_values_only=True,\n)\nprint(\"Done\")"
  }')

# Check if we got real code (not fallback)
if echo "$response" | grep -q '"is_fallback":false'; then
    echo "✅ SUCCESS! Real code generation is working!"
    echo ""
    echo "Sample of generated code:"
    echo "$response" | grep '"generated_code"' | head -1 | cut -d'"' -f4 | head -c 200
    echo "..."
    echo ""
    echo "🎉 You can now use the UI at http://localhost:5179"
    echo "   Load an example, click Run, and see REAL generated code!"
    exit 0
else
    echo "❌ Still showing fallback code"
    echo ""
    echo "Debug info:"
    echo "$response" | grep '"is_fallback"' | head -3
    echo ""
    echo "Check:"
    echo "  1. Backend is running (http://localhost:8000)"
    echo "  2. API key is in .env file"
    echo "  3. Backend loaded .env (check main.py has load_dotenv())"
    exit 1
fi
