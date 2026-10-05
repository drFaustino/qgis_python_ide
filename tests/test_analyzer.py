import ast
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parents[1]))
from core.analyzer import QGISPythonAnalyzer, normalize_whitespace

def test_pass():
    ds=QGISPythonAnalyzer().analyze('def x():\n    pass\n',external=False)
    assert any(d.code=='QGIS001' for d in ds)

def test_syntax():
    ds=QGISPythonAnalyzer().analyze('def x(:\n',external=False)
    assert ds and ds[0].severity=='ERROR'

def test_whitespace():
    assert normalize_whitespace('x=1   \n\n\n\n')=='x=1\n'
