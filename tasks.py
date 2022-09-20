import logging
from typing import Dict, List
from octopoes.models import Reference

from boefjes.models import BOEFJES_DIR
from job import BoefjeMeta, NormalizerMeta
from job_handler import (
    handle_boefje_job,
    handle_normalizer_job,
    _find_ooi_in_past,
    get_octopoes_api_connector,
    serialize_ooi,
)
from katalogus.boefjes import resolve_boefjes, resolve_normalizers
from katalogus.models import PluginType, Normalizer
from runner import LocalBoefjeJobRunner

logger = logging.getLogger(__name__)


def handle_boefje(job: Dict) -> Dict:
    boefje_meta = BoefjeMeta(**job)

    input_ooi = _find_ooi_in_past(
        Reference.from_str(boefje_meta.input_ooi),
        get_octopoes_api_connector(boefje_meta.organization),
    )
    boefje_meta.arguments["input"] = serialize_ooi(input_ooi)

    boefjes = resolve_boefjes(BOEFJES_DIR)
    boefje = boefjes[boefje_meta.boefje.id]

    logger.info("Running local boefje plugin")
    updated_job = handle_boefje_job(
        boefje_meta, LocalBoefjeJobRunner(boefje_meta, boefje, BOEFJES_DIR.name)
    )

    return updated_job.dict()


def normalizers_for_meta(
    boefje_meta: BoefjeMeta,
    all_plugins: List[PluginType],
) -> List[Normalizer]:
    def right_boefje_check(plugin: PluginType):
        return plugin.type == "boefje" and plugin.id == boefje_meta.boefje.id

    boefje_for_meta = list(filter(right_boefje_check, all_plugins))
    assert any(boefje_for_meta), "Plugin not found"

    boefje_plugin = boefje_for_meta[0]

    return [
        normalizer
        for normalizer in all_plugins
        if normalizer.type == "normalizer"
        and set(normalizer.consumes) & set(boefje_plugin.produces)
    ]


def handle_normalizer(normalizer_job: Dict) -> None:
    data = normalizer_job.copy()
    boefje_meta = BoefjeMeta(**data.pop("boefje_meta"))

    normalizer_meta = NormalizerMeta(boefje_meta=boefje_meta, **data)
    normalizers = resolve_normalizers(BOEFJES_DIR)
    normalizer = normalizers[normalizer_meta.normalizer.name]

    handle_normalizer_job(normalizer_meta, normalizer, BOEFJES_DIR.name)
