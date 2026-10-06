from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parents[1]))
from core.formatters import format_document, language_for_suffix, trim_trailing

def test_supported_languages():
    assert language_for_suffix('.py') == 'Python'  # nosec B101 -- test
    assert language_for_suffix('.qss') == 'QSS'  # nosec B101 -- test
    assert language_for_suffix('.xml') == 'XML'  # nosec B101 -- test
    assert language_for_suffix('.md') == 'Markdown'  # nosec B101 -- test
    assert language_for_suffix('.txt') == 'Text'  # nosec B101 -- test

def test_qss_format():
    out=format_document('QWidget{color:red;background:white;}', '.qss')
    assert '{' in out and '\n' in out and 'color:red;' in out  # nosec B101 -- test

def test_markdown_format():
    assert format_document('#Title\n', '.md').startswith('# Title')  # nosec B101 -- test

def test_trim():
    assert trim_trailing('a   \n\n\n') == 'a\n\n\n'  # nosec B101 -- test
    assert trim_trailing('a   \n  b\t\n') == 'a\n  b\n'  # nosec B101 -- test
