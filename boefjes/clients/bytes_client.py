import logging
import typing
from functools import wraps
from typing import Callable, Dict, Union, Any, Set

import requests
from datetime import datetime
from requests.models import HTTPError

from boefjes.job import BoefjeMeta, NormalizerMeta
from boefjes.clients.data import BOEFJE_METAS, NORMALIZER_METAS, RAWS

from scheduler.models import NormalizerMetaReceivedEvent, RawDataReceivedEvent, RawData
from scheduler.connectors.listeners.listeners import QUEUES


BYTES_API_CLIENT_VERSION = "0.3"
logger = logging.getLogger(__name__)


class BytesAPISession(requests.Session):
    def __init__(self, base_url: str):
        super().__init__()

        self._base_url = base_url
        self.headers["User-Agent"] = f"bytes-api-client/{BYTES_API_CLIENT_VERSION}"

    def request(self, method: str, url: Union[str, bytes], **kwargs) -> requests.Response:  # type: ignore
        url = self._base_url + str(url)

        return super().request(method, url, **kwargs)


ClientSessionMethod = Callable[..., Any]


def retry_with_login(function: ClientSessionMethod) -> ClientSessionMethod:
    @wraps(function)
    def wrapper(self, *args, **kwargs):  # type: ignore
        try:
            return function(self, *args, **kwargs)
        except HTTPError as error:
            if error.response.status_code != 401:
                raise error from HTTPError

            self.login()
            return function(self, *args, **kwargs)

    return typing.cast(ClientSessionMethod, wrapper)


class BytesAPIClient:
    def __init__(self, *args, **kwargs):
        pass

    def login(self):
        pass

    def save_boefje_meta(self, boefje_meta: BoefjeMeta) -> None:
        BOEFJE_METAS[boefje_meta.id] = boefje_meta

    def get_boefje_meta(self, boefje_meta_id: str) -> BoefjeMeta:
        return BOEFJE_METAS[boefje_meta_id]

    def save_normalizer_meta(self, normalizer_meta: NormalizerMeta) -> None:
        NORMALIZER_METAS[normalizer_meta.id] = normalizer_meta
        queue_name = f"{normalizer_meta.boefje_meta.organization}__normalizer_meta_received"

        if queue_name not in QUEUES:
            QUEUES[queue_name] = []

        QUEUES[queue_name].append(
            NormalizerMetaReceivedEvent(
                created_at=datetime.now(),
                organization=normalizer_meta.boefje_meta.organization,
                normalizer_meta=normalizer_meta,
            ).dict()
        )

    def get_normalizer_meta(self, normalizer_meta_id: str) -> NormalizerMeta:
        return NORMALIZER_METAS[normalizer_meta_id]

    def save_raw(
        self, boefje_meta_id: str, raw: bytes, mime_types: Set[str] = None
    ) -> None:
        if not mime_types:
            mime_types = set()

        if isinstance(raw, str):
            raw = raw.encode()

        RAWS[boefje_meta_id] = (raw, mime_types)
        boefje_meta = self.get_boefje_meta(boefje_meta_id)

        queue_name = f"{boefje_meta.organization}__raw_file_received"

        if queue_name not in QUEUES:
            QUEUES[queue_name] = []

        QUEUES[queue_name].append(
            RawDataReceivedEvent(
                created_at=datetime.now(),
                organization=boefje_meta.organization,
                raw_data=RawData(
                    boefje_meta=boefje_meta,
                    mime_types=[{"value": m} for m in mime_types],
                ),
            ).dict()
        )

    def get_raw(self, boefje_meta_id: str) -> bytes:
        raw, mime_types = RAWS[boefje_meta_id]

        return raw


class BytesAPIClientV1:
    def __init__(self, base_url: str, username: str, password: str):
        self._session = BytesAPISession(base_url)
        self.credentials = {
            "username": username,
            "password": password,
        }
        self.headers: Dict[str, str] = {}

    def login(self) -> None:
        self.headers = self._get_authentication_headers()

    @staticmethod
    def _verify_response(response: requests.Response) -> None:
        if response.status_code != 200:
            logger.error(response.text)
        response.raise_for_status()

    def _get_authentication_headers(self) -> Dict[str, str]:
        return {"Authorization": f"bearer {self._get_token()}"}

    def _get_token(self) -> str:
        response = self._session.post(
            "/token",
            data=self.credentials,
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

        return str(response.json()["access_token"])

    @retry_with_login
    def save_boefje_meta(self, boefje_meta: BoefjeMeta) -> None:
        response = self._session.post(
            "/bytes/boefje_meta", data=boefje_meta.json(), headers=self.headers
        )

        self._verify_response(response)

    @retry_with_login
    def get_boefje_meta(self, boefje_meta_id: str) -> BoefjeMeta:
        response = self._session.get(
            f"/bytes/boefje_meta/{boefje_meta_id}", headers=self.headers
        )
        self._verify_response(response)

        boefje_meta_json = response.json()
        return BoefjeMeta.parse_obj(boefje_meta_json)

    @retry_with_login
    def save_normalizer_meta(self, normalizer_meta: NormalizerMeta) -> None:
        response = self._session.post(
            "/bytes/normalizer_meta", data=normalizer_meta.json(), headers=self.headers
        )

        self._verify_response(response)

    @retry_with_login
    def get_normalizer_meta(self, normalizer_meta_id: str) -> NormalizerMeta:
        response = self._session.get(
            f"/bytes/normalizer_meta/{normalizer_meta_id}", headers=self.headers
        )
        self._verify_response(response)

        normalizer_meta_json = response.json()
        return NormalizerMeta.parse_obj(normalizer_meta_json)

    @retry_with_login
    def save_raw(
        self, boefje_meta_id: str, raw: bytes, mime_types: Set[str] = None
    ) -> None:
        if not mime_types:
            mime_types = set()

        headers = {"content-type": "application/octet-stream"}
        headers.update(self.headers)

        response = self._session.post(
            f"/bytes/raw/{boefje_meta_id}",
            raw,
            headers=headers,
            params={"mime_types": mime_types},
        )

        self._verify_response(response)

    @retry_with_login
    def get_raw(self, boefje_meta_id: str) -> bytes:
        response = self._session.get(
            f"/bytes/raw/{boefje_meta_id}", headers=self.headers
        )
        self._verify_response(response)

        return response.content
