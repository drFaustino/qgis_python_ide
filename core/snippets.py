from __future__ import annotations

from qgis.PyQt.QtCore import QSettings


DEFAULTS = {
    # --------------------------------------------------------------
    # Base
    # --------------------------------------------------------------

    "QGIS import": """from qgis.core import (
    Qgis,
    QgsProject,
    QgsVectorLayer,
    QgsMessageLog,
)
""",

    "Active layer": """layer = iface.activeLayer()
if layer is None:
    iface.messageBar().pushWarning(
        "QGIS Python IDE",
        "Seleziona un layer prima di eseguire il codice",
    )
    raise RuntimeError("Nessun layer attivo")
""",

    "Features loop": """for feature in layer.getFeatures():
    geom = feature.geometry()
    if not geom.isNull():
        # Esempio: elabora la geometria
        pass
""",

    "QgsExpression": """from qgis.core import QgsExpression, QgsFeatureRequest

expression = QgsExpression('"population" > 100000')
if expression.hasParserError():
    raise RuntimeError(expression.parserErrorString())

request = QgsFeatureRequest(expression)
for feature in layer.getFeatures(request):
    print(feature.id())
""",

    # --------------------------------------------------------------
    # Layer
    # --------------------------------------------------------------

    "Layer da percorso": """path = "/percorso/del/file.shp"
layer = QgsVectorLayer(path, "Nome layer", "ogr")
if not layer.isValid():
    raise RuntimeError(f"Layer non valido: {path}")
QgsProject.instance().addMapLayer(layer)
""",

    "Aggiungi layer al progetto": """QgsProject.instance().addMapLayer(layer)
""",

    "Layer in memoria": """layer = QgsVectorLayer("Point?crs=epsg:4326", "layer_memoria", "memory")
provider = layer.dataProvider()

from qgis.core import QgsField
from qgis.PyQt.QtCore import QMetaType

provider.addAttributes([
    QgsField("nome", QMetaType.Type.QString),
    QgsField("valore", QMetaType.Type.Double),
])
layer.updateFields()
QgsProject.instance().addMapLayer(layer)
""",

    "Modifica layer (edit)": """layer.startEditing()

feature = QgsFeature(layer.fields())
feature.setAttribute("nome", "esempio")
provider = layer.dataProvider()
provider.addFeature(feature)

layer.commitChanges()  # oppure layer.rollBack()
""",

    "Trasforma CRS": """from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
)

source_crs = QgsCoordinateReferenceSystem("EPSG:4326")
target_crs = QgsCoordinateReferenceSystem("EPSG:3857")
transform = QgsCoordinateTransform(
    source_crs,
    target_crs,
    QgsProject.instance(),
)
geometry_3857 = geometry_4326
geometry_3857.transform(transform)
""",

    # --------------------------------------------------------------
    # GUI / Qt6
    # --------------------------------------------------------------

    "QMessageBox": """from qgis.PyQt.QtWidgets import QMessageBox

QMessageBox.information(
    iface.mainWindow(),
    "QGIS Python IDE",
    "Messaggio",
)
""",

    "Message bar": """iface.messageBar().pushMessage(
    "QGIS Python IDE",
    "Operazione completata",
    level=Qgis.MessageLevel.Info,
    duration=3,
)
""",

    "QgsMessageLog": """from qgis.core import QgsMessageLog, Qgis

QgsMessageLog.logMessage(
    "Messaggio",
    "QGIS Python IDE",
    level=Qgis.MessageLevel.Info,
)
""",

    "QAction (Qt6)": """from qgis.PyQt.QtGui import QAction

action = QAction("Esegui", iface.mainWindow())
action.triggered.connect(lambda: print("Eseguito"))
iface.addToolBarIcon(action)
iface.addPluginToMenu("&QGIS Python IDE", action)
""",

    # --------------------------------------------------------------
    # Task / Processing
    # --------------------------------------------------------------

    "QgsTask": """from qgis.core import QgsTask, QgsApplication


class MyTask(QgsTask):
    def run(self):
        # Codice in background: NON toccare la GUI qui
        return True

    def finished(self, result):
        if result:
            iface.messageBar().pushInfo("Task", "Completato")
        else:
            iface.messageBar().pushCritical("Task", "Errore")


task = MyTask("Il mio task")
QgsApplication.taskManager().addTask(task)
""",

    "QgsTask with progress": """from qgis.core import QgsTask, QgsApplication


class ProgressTask(QgsTask):
    def __init__(self):
        super().__init__("Task con avanzamento", QgsTask.CanCancel)
        self.exception = None

    def run(self):
        for step in range(100):
            if self.isCanceled():
                return False
            self.setProgress(step)
        return True

    def finished(self, result):
        if result:
            iface.messageBar().pushInfo("Task", "Completato")
        else:
            iface.messageBar().pushWarning("Task", "Annullato o errore")


QgsApplication.taskManager().addTask(ProgressTask())
""",

    "Algoritmo Processing": """from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterVectorDestination,
)


class MyAlgorithm(QgsProcessingAlgorithm):
    def name(self):
        return "my_algorithm"

    def displayName(self):
        return "Il mio algoritmo"

    def group(self):
        return "Esempi"

    def groupId(self):
        return "esempi"

    def shortHelpString(self):
        return "Descrizione dell'algoritmo."

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                "INPUT",
                "Layer di input",
            )
        )
        self.addParameter(
            QgsProcessingParameterVectorDestination(
                "OUTPUT",
                "Layer di output",
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, "INPUT", context)
        (sink, dest_id) = self.parameterAsSink(
            parameters,
            "OUTPUT",
            context,
            source.fields(),
            source.wkbType(),
            source.sourceCrs(),
        )
        total = source.featureCount() or 0
        for current, feature in enumerate(source.getFeatures()):
            if feedback.isCanceled():
                break
            sink.addFeature(feature)
            feedback.setProgress(int(current * 100 / max(total, 1)))
        return {"OUTPUT": dest_id}
""",

    "Script Processing": """from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterVectorDestination,
)


class MyScript(QgsProcessingAlgorithm):
    def name(self):
        return "my_script"

    def displayName(self):
        return "Il mio script"

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource("INPUT", "Layer input")
        )
        self.addParameter(
            QgsProcessingParameterVectorDestination("OUTPUT", "Output")
        )

    def processAlgorithm(self, parameters, context, feedback):
        layer = self.parameterAsVectorLayer(parameters, "INPUT", context)
        # elabora...
        return {"OUTPUT": layer.id()}
""",

    # --------------------------------------------------------------
    # Impostazioni
    # --------------------------------------------------------------

    "QgsSettings": """from qgis.core import QgsSettings

settings = QgsSettings()

value = settings.value("mio_plugin/chiave", "default", type=str)
settings.setValue("mio_plugin/chiave", value)
""",
}


class SnippetStore:
    """Gestisce gli snippet predefiniti e quelli personalizzati."""

    SETTINGS_ORG = "QGIS"
    SETTINGS_APP = "QGISPythonIDEPro"
    SETTINGS_KEY = "snippets"

    def __init__(self):
        self.settings = QSettings(
            self.SETTINGS_ORG,
            self.SETTINGS_APP,
        )

        self.data = dict(DEFAULTS)

        custom = self.settings.value(
            self.SETTINGS_KEY,
            {},
            type=dict,
        )

        if isinstance(custom, dict):
            for name, code in custom.items():
                if isinstance(name, str) and isinstance(code, str):
                    self.data[name] = code

    def all(self) -> dict[str, str]:
        """Restituisce tutti gli snippet disponibili."""
        return dict(self.data)

    def get(self, name: str, default: str = "") -> str:
        """Restituisce il codice dello snippet richiesto."""
        return self.data.get(name, default)

    def add(self, name: str, code: str) -> bool:
        """Aggiunge o sostituisce uno snippet."""
        name = str(name).strip()

        if not name:
            return False

        self.data[name] = str(code)
        self.save()
        return True

    def remove(self, name: str) -> bool:
        """Rimuove uno snippet personalizzato."""
        if name not in self.data:
            return False

        if name in DEFAULTS:
            return False

        del self.data[name]
        self.save()
        return True

    def reset(self) -> None:
        """Ripristina gli snippet predefiniti."""
        self.data = dict(DEFAULTS)
        self.save()

    def save(self) -> None:
        """Salva gli snippet nelle impostazioni di QGIS."""
        self.settings.setValue(
            self.SETTINGS_KEY,
            dict(self.data),
        )
