# -*- coding: utf-8 -*-
"""Provider management — models, registry + persistent store."""

from .models import (
    ActiveModelsInfo,
    CustomProviderData,
    ModelInfo,
    ModelSlotConfig,
    ProviderDefinition,
    ProviderInfo,
    ProviderSettings,
    ProvidersData,
    ResolvedModelConfig,
)
from .registry import (
    PROVIDERS,
    get_chat_model_class,
    get_provider,
    get_provider_chat_model,
    is_builtin,
    list_providers,
    sync_local_models,
    sync_web_providers,
)
from .store import (
    add_model,
    create_custom_provider,
    delete_custom_provider,
    get_active_llm_config,
    load_providers_json,
    mask_api_key,
    remove_model,
    save_providers_json,
    set_active_llm,
    update_provider_settings,
)
from .web_models import WebCredential
from .web_registry import WEB_PROVIDERS, list_web_provider_ids
from .web_store import (
    delete_web_credential,
    get_web_credential,
    is_credential_valid,
    load_web_credentials,
    save_web_credential,
)

__all__ = [
    "ActiveModelsInfo",
    "CustomProviderData",
    "ModelInfo",
    "ModelSlotConfig",
    "ProviderDefinition",
    "ProviderInfo",
    "ProviderSettings",
    "ProvidersData",
    "ResolvedModelConfig",
    "PROVIDERS",
    "get_chat_model_class",
    "get_provider",
    "get_provider_chat_model",
    "is_builtin",
    "list_providers",
    "sync_local_models",
    "sync_web_providers",
    "add_model",
    "create_custom_provider",
    "delete_custom_provider",
    "get_active_llm_config",
    "load_providers_json",
    "mask_api_key",
    "remove_model",
    "save_providers_json",
    "set_active_llm",
    "update_provider_settings",
    "WebCredential",
    "WEB_PROVIDERS",
    "list_web_provider_ids",
    "delete_web_credential",
    "get_web_credential",
    "is_credential_valid",
    "load_web_credentials",
    "save_web_credential",
]
