"""CPU-only milestone configuration; relative paths follow the config file."""

from dataclasses import dataclass
from pathlib import Path
import tomllib

from .validation import ContractError, fields, text


@dataclass(frozen=True)
class Config:
    database: Path
    device: str = "cpu"
    backend: str = "unconfigured"
    schema_version: int = 1

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ContractError("unsupported config schema_version")
        if self.device != "cpu":
            raise ContractError("this milestone supports CPU infrastructure only")
        if self.backend != "unconfigured":
            raise ContractError("no real engine backend has been integrated")
        if not isinstance(self.database, Path):
            raise ContractError("database must be a Path")

    def to_dict(self):
        return {"schema_version": self.schema_version, "storage": {"database": str(self.database)},
                "runtime": {"device": self.device}, "engine": {"backend": self.backend}}


def load_config(path: Path | None = None) -> Config:
    if path is None:
        return Config((Path.cwd() / ".cache/ygo-kito/index.sqlite3").resolve())
    with path.open("rb") as handle:
        d = fields(tomllib.load(handle), {"schema_version", "storage", "runtime", "engine"})
    storage = fields(d["storage"], {"database"})
    runtime = fields(d["runtime"], {"device"})
    engine = fields(d["engine"], {"backend"})
    database = Path(text(storage["database"], "storage.database"))
    if not database.is_absolute():
        database = path.resolve().parent / database
    return Config(database.resolve(), runtime["device"], engine["backend"], d["schema_version"])

