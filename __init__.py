"""QGIS Python IDE Pro - QGIS 4 / Qt6."""

def classFactory(iface):
    from .python_ide import QGISPythonIDE
    return QGISPythonIDE(iface)
