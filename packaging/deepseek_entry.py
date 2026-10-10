"""Run the bundled upstream; self-check never contacts DeepSeek."""
import os
import sys
import app as upstream

if '--self-check' in sys.argv:
    from functions import _get_pow_setup, count_tokens
    assert count_tokens('hello') > 0
    assert _get_pow_setup()[1] is not None
    assert os.path.isfile(os.path.join(upstream.BASE_DIR, 'templates/login.html'))
    assert os.path.isfile(os.path.join(upstream.BASE_DIR, 'static/style.css'))
    print('PASS: bundled tokenizer, WASM, dashboard and service imports')
else:
    upstream.uvicorn.run(upstream.app, host=os.getenv('HOST', '127.0.0.1'), port=int(os.getenv('PORT', '4000')))
