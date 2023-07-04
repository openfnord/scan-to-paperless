"""Manage the status file of the progress."""

import datetime
import glob
import html
import os.path
from typing import NamedTuple, Optional

import jinja2
import natsort
from ruamel.yaml.main import YAML

_WAITING_STATUS_NAME = "Waiting validation"
_WAITING_STATUS_DESCRIPTION = """You should validate that the generate images are correct ({generated_images}).<br>
    If the result is correct remove the <a href="./{name}/REMOVE_TO_CONTINUE" target="_blank"><code>REMOVE_TO_CONTINUE</code></a> file.<br>
    If not you can:<br>
    <ul>
        <li>Edit the generated tmage Then remove the <a href="./{name}/REMOVE_TO_CONTINUE" target="_blank"><code>REMOVE_TO_CONTINUE</code></a> file.</li>
        <li>Edit the <a href="./{name}/config.yaml" target="_blank"><code>config.yaml</code></a> file to change the parameters, then remove the generated files ({generated_images}) to force the regeneration.</li>
        <li>Edit the source images ({source_images}) then remove the corresponding generated files ({generated_images}) to force the regeneration.</li>
    </ul>"""


class _Folder(NamedTuple):
    nb_images: int
    status: str
    details: str


class Status:
    """Manage the status file of the progress."""

    def __init__(self, no_write: bool = False) -> None:
        """Construct."""

        self.no_write = no_write
        self._file = os.path.join(os.environ.get("SCAN_SOURCE_FOLDER", "/source"), "status.html")
        self._status: dict[str, _Folder] = {}
        self._codes: list[str] = []
        self._consume: list[str] = []
        self._global_status = "Starting..."
        self._global_status_update = datetime.datetime.utcnow().replace(microsecond=0)
        self._start_time = datetime.datetime.utcnow().replace(microsecond=0)
        self._last_scan = datetime.datetime.utcnow()
        self._current_folder: Optional[str] = None
        self.scan()

    def set_global_status(self, status: str) -> None:
        """Set the global status."""

        if self._global_status != status:
            self._global_status = status
            self._global_status_update = datetime.datetime.utcnow().replace(microsecond=0)

        self.write()

    def set_current_folder(self, name: Optional[str]) -> None:
        """Set the current folder."""

        self._current_folder = name

    def set_current_config(self, name: str) -> None:
        """Set the current config file."""

        if name.endswith("/config.yaml"):
            name = os.path.basename(os.path.dirname(name))
        self._current_folder = name

    def set_status(self, name: str, nb_images: int, status: str, details: str = "") -> None:
        """Set the status of a folder."""

        # Config file name
        if name.endswith("/config.yaml"):
            name = os.path.basename(os.path.dirname(name))
        if nb_images <= 0 and name in self._status:
            nb_images = self._status[name].nb_images
        self._status[name] = _Folder(nb_images, html.escape(status), details)

        if self.no_write:
            print(f"{name}: {status}")

        if not self.no_write:
            self.write()

    def scan(self) -> None:
        """Scan for changes for waiting documents."""

        self._last_scan = datetime.datetime.utcnow()

        codes_folder = os.environ.get("SCAN_CODES_FOLDER", "/scan-codes")
        if codes_folder[-1] != "/":
            codes_folder += "/"
        self._codes = [
            f[len(codes_folder) :]
            for f in glob.glob(os.path.join(codes_folder, "**"), recursive=True)
            if os.path.isfile(f)
        ]

        consume_folder = os.environ.get("SCAN_FINAL_FOLDER", "/destination")
        if consume_folder[-1] != "/":
            consume_folder += "/"
        self._consume = [
            f[len(consume_folder) :]
            for f in glob.glob(os.path.join(consume_folder, "**"), recursive=True)
            if os.path.isfile(f)
        ]

        source_folder = os.environ.get("SCAN_SOURCE_FOLDER", "/source")
        for name in list(self._status):
            if name != self._current_folder:
                if os.path.isdir(os.path.join(source_folder, name)):
                    self._update_status(name)
                else:
                    del self._status[name]

        for folder_name in glob.glob(os.path.join(source_folder, "*")):
            if os.path.isdir(folder_name):
                name = os.path.basename(folder_name)
                if name not in self._status:
                    self._update_status(name)

    def _update_status(self, name: str) -> None:
        yaml = YAML(typ="safe")
        source_folder = os.environ.get("SCAN_SOURCE_FOLDER", "/source")
        if os.path.exists(os.path.join(source_folder, name, "error.yaml")):
            with open(
                os.path.join(source_folder, name, "error.yaml"),
                encoding="utf-8",
            ) as error_file:
                error = yaml.load(error_file)

            self.set_status(
                name, -1, "Error: " + error["error"], "<code>" + "<br />".join(error["traceback"]) + "</code>"
            )
            return

        if os.path.exists(os.path.join(source_folder, name, "DONE")):
            self.set_status(name, -1, "Done")
            return

        if not os.path.exists(os.path.join(source_folder, name, "config.yaml")):
            len_folder = len(os.path.join(source_folder, name).rstrip("/")) + 1
            files = [
                f[len_folder:]
                for f in glob.glob(
                    os.path.join(source_folder, name, "**"),
                    recursive=True,
                )
                if os.path.isfile(f)
            ]
            files = [f'<a href="./{name}/{f}" target="_blank"><code>{f}</code></a>' for f in files]
            self.set_status(name, -1, "Missing config", ", ".join(files))
            return

        with open(
            os.path.join(source_folder, name, "config.yaml"),
            encoding="utf-8",
        ) as config_file:
            config = yaml.load(config_file)

        if config is None:
            self.set_status(name, -1, "Empty config")
            return

        if os.path.exists(os.path.join(source_folder, name, "REMOVE_TO_CONTINUE")):
            rerun = False
            for image in config["steps"][-1]["sources"]:
                if not os.path.exists(image):
                    rerun = True
            nb_images = -1
            if config.get("steps", []):
                nb_images = len(config["steps"][-1]["sources"])
            elif "sources" in config:
                nb_images = len(config["sources"])

            if rerun:
                if len(config["steps"]) >= 2:
                    self.set_status(name, nb_images, "Waiting to " + config["steps"][-2]["name"])
                else:
                    self.set_status(name, nb_images, "Waiting to transform")
            else:
                len_folder = len(os.path.join(source_folder, name).rstrip("/")) + 1
                source_images = (
                    config["steps"][-2]["sources"] if len(config["steps"]) >= 2 else config["sources"]
                )
                generated_images = [f[len_folder:] for f in config["steps"][-1]["sources"]]
                self.set_status(
                    name,
                    nb_images,
                    _WAITING_STATUS_NAME,
                    _WAITING_STATUS_DESCRIPTION.format(
                        name=name,
                        source_images=", ".join(
                            [
                                f'<a href="./{name}/{f}" target="_blank"><code>{f}</code></a>'
                                for f in source_images
                            ]
                        ),
                        generated_images=", ".join(
                            [
                                f'<a href="./{name}/{f}" target="_blank"><code>{f}</code></a>'
                                for f in generated_images
                            ]
                        ),
                    ),
                )

        else:
            if len(config.get("steps", [])) >= 1:
                self.set_status(name, -1, "Waiting to " + config["steps"][-1]["name"])
            else:
                self.set_status(name, -1, "Waiting to transform")

    def write(self) -> None:
        """Write the status file."""

        if self._last_scan < datetime.datetime.utcnow() - datetime.timedelta(minutes=1):
            self.scan()

        if self.no_write:
            return

        with open(self._file, "w", encoding="utf-8") as status_file:
            env = jinja2.Environment(
                loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
                autoescape=jinja2.select_autoescape(),
            )
            template = env.get_template("status.html")
            status_file.write(
                template.render(
                    global_status=self._global_status,
                    global_status_update=self._global_status_update,
                    start_time=self._start_time,
                    datetime=datetime,
                    status=self._status,
                    sorted_status_key=natsort.natsorted(self._status.keys()),
                    codes=self._codes,
                    consume=self._consume,
                )
            )
