"""Verify results from am instrument -w -r -e session_restart portable_exchange."""
import base64
from pathlib import Path
import re
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.question_files import read_questions


def check(result_file):
    result = Path(result_file).read_text(encoding='utf-8')
    assert 'PASS:' in result and 'FAIL:' not in result, result
    exports = dict(re.findall(r'^INSTRUMENTATION_RESULT: portable_(json|csv)=([A-Za-z0-9+/=]+)', result, re.MULTILINE))
    assert set(exports) == {'json', 'csv'}, 'Missing actual Android exports'
    expected = read_questions(Path(__file__).parent / 'fixtures/portable_exchange.json')
    with tempfile.TemporaryDirectory(prefix='flandre-phone-exchange-') as directory:
        for suffix, content in exports.items():
            file = Path(directory) / f'phone.{suffix}'
            file.write_bytes(base64.b64decode(content, validate=True))
            assert read_questions(file) == expected, f'Phone {suffix} changed question content'
    print('PASS: actual phone JSON/CSV exports import unchanged on desktop')


if __name__ == '__main__':
    check(sys.argv[1])
