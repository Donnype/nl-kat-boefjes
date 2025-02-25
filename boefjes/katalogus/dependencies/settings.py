import logging
from typing import Dict, Iterator

from sqlalchemy.orm import Session

from boefjes.config import settings
from boefjes.katalogus.dependencies.context import Context, Environment
from boefjes.katalogus.dependencies.encryption import (
    EncryptMiddleware,
    NaclBoxMiddleware,
    IdentityMiddleware,
)
from boefjes.katalogus.models import EncryptionMiddleware
from boefjes.katalogus.storage.interfaces import SettingsStorage
from boefjes.katalogus.storage.memory import SettingsStorageMemory
from boefjes.sql.db import session_managed_iterator
from boefjes.sql.setting_storage import create_setting_storage

logger = logging.getLogger(__name__)


class SettingsService:
    def __init__(self, storage: SettingsStorage, encryption: EncryptMiddleware):
        self.encryption = encryption
        self.storage = storage

    def get_by_key(self, key: str, organisation_id: str, plugin_id: str) -> str:
        return self.encryption.decode(
            self.storage.get_by_key(key, organisation_id, plugin_id)
        )

    def get_all(self, organisation_id: str, plugin_id: str) -> Dict[str, str]:
        return {
            k: self.encryption.decode(v)
            for k, v in self.storage.get_all(organisation_id, plugin_id).items()
        }

    def create(
        self, key: str, value: str, organisation_id: str, plugin_id: str
    ) -> None:
        with self.storage as storage:
            return storage.create(
                key, self.encryption.encode(value), organisation_id, plugin_id
            )

    def update_by_id(
        self, key: str, value: str, organisation_id: str, plugin_id: str
    ) -> None:
        with self.storage as storage:
            return storage.update_by_key(
                key, self.encryption.encode(value), organisation_id, plugin_id
            )

    def delete_by_id(self, key: str, organisation_id: str, plugin_id: str) -> None:
        with self.storage as storage:
            storage.delete_by_key(key, organisation_id, plugin_id)


def get_settings_service(
    organisation_id: str
) -> Iterator[SettingsService]:
    context = Context(Environment())
    encrypter = IdentityMiddleware()
    if context.env.encryption_middleware == EncryptionMiddleware.NACL_SEALBOX:
        encrypter = NaclBoxMiddleware(
            context.env.katalogus_private_key_b64, context.env.katalogus_public_key_b64
        )

    if not settings.enable_db:
        yield SettingsService(
            storage=SettingsStorageMemory(organisation_id), encryption=encrypter
        )
        return

    def closure(session: Session):
        return SettingsService(
            storage=create_setting_storage(session), encryption=encrypter
        )

    yield from session_managed_iterator(closure)
