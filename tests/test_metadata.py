from pathlib import Path
import configparser

def test_metadata_versions():
    p=Path(__file__).parents[1]/'metadata.txt'
    cfg=configparser.ConfigParser(); cfg.read(p,encoding='utf-8')
    assert cfg['general']['qgisMinimumVersion']=='4.0'  # nosec B101 -- test
    assert cfg['general']['qgisMaximumVersion']=='4.99'  # nosec B101 -- test
