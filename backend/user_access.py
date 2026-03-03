from copy import deepcopy


BYTES_PER_MB = 1024 * 1024
DEFAULT_ROLE_KEY = "member"
DEFAULT_PLAN_KEY = "simple"

ROLE_DEFINITIONS = {
    "member": {
        "key": "member",
        "label": "Membro",
        "description": "Conta padrão autenticada via Google.",
        "permissions": {
            "can_query": True,
            "can_upload": True,
            "can_delete_documents": True,
            "can_reset_workspace": True,
            "can_manage_vectorstore": True,
            "can_manage_access": False,
        },
    },
    "admin": {
        "key": "admin",
        "label": "Administrador",
        "description": "Conta com permissão para manutenção avançada e gestão de acesso.",
        "permissions": {
            "can_query": True,
            "can_upload": True,
            "can_delete_documents": True,
            "can_reset_workspace": True,
            "can_manage_vectorstore": True,
            "can_manage_access": True,
        },
    },
}

PLAN_DEFINITIONS = {
    "simple": {
        "key": "simple",
        "label": "Conta simples",
        "description": "Até 3 arquivos com no máximo 10 MB por arquivo.",
        "limits": {
            "max_documents": 3,
            "max_file_size_bytes": 10 * BYTES_PER_MB,
            "max_total_storage_bytes": 30 * BYTES_PER_MB,
        },
        "features": {
            "workspace_isolated": True,
            "google_login": True,
            "priority_indexing": False,
            "usage_dashboard": True,
        },
    },
}


def _clone(mapping):
    return deepcopy(mapping)


def resolve_role_key(role_key):
    candidate = str(role_key or DEFAULT_ROLE_KEY).strip().lower()
    if candidate in ROLE_DEFINITIONS:
        return candidate

    return DEFAULT_ROLE_KEY


def resolve_plan_key(plan_key):
    candidate = str(plan_key or DEFAULT_PLAN_KEY).strip().lower()
    if candidate in PLAN_DEFINITIONS:
        return candidate

    return DEFAULT_PLAN_KEY


def get_role_definition(role_key=None):
    return _clone(ROLE_DEFINITIONS[resolve_role_key(role_key)])


def get_plan_definition(plan_key=None):
    return _clone(PLAN_DEFINITIONS[resolve_plan_key(plan_key)])


def build_access_profile(role_key=None, plan_key=None):
    role = get_role_definition(role_key)
    plan = get_plan_definition(plan_key)

    return {
        "role_key": role["key"],
        "plan_key": plan["key"],
        "role": role,
        "plan": plan,
        "permissions": _clone(role["permissions"]),
        "limits": _clone(plan["limits"]),
        "features": _clone(plan["features"]),
    }
