from datetime import timedelta
from functools import wraps
from flask import Flask, g, jsonify, request, send_from_directory, session
from flask_cors import CORS
import os
from io import SEEK_END, SEEK_SET
from pathlib import Path
from dotenv import load_dotenv
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token

try:
    from .rag_engine import RAGEngine
    from .user_store import UserStore
except ImportError:
    from rag_engine import RAGEngine
    from user_store import UserStore

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
FRONTEND_DIR = PROJECT_ROOT / 'frontend'
USERS_PATH = PROJECT_ROOT / 'data' / 'users.json'
SUPPORTED_EXTENSIONS = {'.pdf', '.txt'}
BYTES_PER_MB = 1024 * 1024
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(BACKEND_DIR / ".env", override=True)
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
ALLOWED_GOOGLE_DOMAIN = os.getenv("GOOGLE_ALLOWED_DOMAIN", "").strip().lower()
ALLOWED_GOOGLE_EMAILS = {
    email.strip().lower()
    for email in os.getenv("GOOGLE_ALLOWED_EMAILS", "").split(",")
    if email.strip()
}

def resolve_project_path(relative_path):
    return (PROJECT_ROOT / relative_path).resolve()


def get_user_workspace(user=None):
    active_user = user or getattr(g, "current_user", None)
    if active_user is None:
        raise RuntimeError("Usuário autenticado não disponível para resolver workspace.")

    workspace = active_user.get("workspace") or user_store.get_user_workspace(active_user["id"])
    if not isinstance(workspace, dict):
        raise RuntimeError("Workspace do usuário não encontrado.")

    workspace_root = resolve_project_path(workspace["root"])
    documents_path = resolve_project_path(workspace["documents_dir"])
    vectorstore_path = resolve_project_path(workspace["vectorstore_dir"])

    workspace_root.mkdir(parents=True, exist_ok=True)
    documents_path.mkdir(parents=True, exist_ok=True)

    return {
        "root_path": workspace_root,
        "documents_path": documents_path,
        "vectorstore_path": vectorstore_path,
        "metadata": workspace,
    }


def get_user_access(user=None):
    active_user = user or getattr(g, "current_user", None)
    if active_user is None:
        raise RuntimeError("Usuário autenticado não disponível para resolver acesso.")

    access = active_user.get("access") or user_store.get_user_access(active_user["id"])
    if not isinstance(access, dict):
        raise RuntimeError("Política de acesso do usuário não encontrada.")

    return access


def has_user_permission(permission_key, user=None):
    access = get_user_access(user=user)
    permissions = access.get("permissions") or {}
    return bool(permissions.get(permission_key, False))


def get_uploaded_file_size(uploaded_file):
    stream = uploaded_file.stream
    current_position = stream.tell()
    stream.seek(0, SEEK_END)
    size_bytes = stream.tell()
    stream.seek(current_position, SEEK_SET)
    return size_bytes


def build_workspace_usage(workspace, access=None):
    documents = get_supported_document_paths(workspace["documents_path"])
    total_storage_bytes = sum(
        file_path.stat().st_size
        for file_path in documents
        if file_path.exists()
    )
    active_access = access or get_user_access()
    limits = active_access.get("limits") or {}
    max_documents = limits.get("max_documents")
    max_total_storage_bytes = limits.get("max_total_storage_bytes")

    documents_count = len(documents)
    documents_remaining = None
    if isinstance(max_documents, int):
        documents_remaining = max(max_documents - documents_count, 0)

    storage_remaining_bytes = None
    if isinstance(max_total_storage_bytes, int):
        storage_remaining_bytes = max(max_total_storage_bytes - total_storage_bytes, 0)

    over_documents_limit = isinstance(max_documents, int) and documents_count > max_documents
    over_storage_limit = (
        isinstance(max_total_storage_bytes, int)
        and total_storage_bytes > max_total_storage_bytes
    )

    return {
        "documents_count": documents_count,
        "documents_remaining": documents_remaining,
        "storage_bytes": total_storage_bytes,
        "storage_remaining_bytes": storage_remaining_bytes,
        "limit_reached": over_documents_limit or over_storage_limit,
        "over_limits": {
            "documents": over_documents_limit,
            "storage": over_storage_limit,
        },
    }


def list_supported_documents(documents_path):
    if not documents_path.exists():
        return []

    return sorted(
        file_path.name
        for file_path in documents_path.iterdir()
        if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def get_supported_document_paths(documents_path):
    if not documents_path.exists():
        return []

    return sorted(
        file_path
        for file_path in documents_path.iterdir()
        if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def sync_index_with_documents(workspace):
    documents_path = workspace["documents_path"]
    vectorstore_path = workspace["vectorstore_path"]
    documents = get_supported_document_paths(documents_path)
    if documents:
        return rag_engine.index_directory(
            documents_path,
            persist_directory=vectorstore_path,
        )

    return rag_engine.reset_index(persist_directory=vectorstore_path)


def reset_documents_and_data(workspace):
    documents_path = workspace["documents_path"]
    vectorstore_path = workspace["vectorstore_path"]
    documents_path.mkdir(parents=True, exist_ok=True)

    deleted_files = []
    for file_path in get_supported_document_paths(documents_path):
        file_path.unlink(missing_ok=True)
        deleted_files.append(file_path.name)

    success = rag_engine.reset_index(persist_directory=vectorstore_path)
    return success, deleted_files

def serialize_user(user):
    if not user:
        return None

    return {
        "id": user.get("id"),
        "email": user.get("email"),
        "name": user.get("name"),
        "picture": user.get("picture"),
        "given_name": user.get("given_name"),
        "family_name": user.get("family_name"),
        "hosted_domain": user.get("hosted_domain"),
        "last_login_at": user.get("last_login_at"),
        "login_count": user.get("login_count", 0),
        "role_key": user.get("role_key"),
        "plan_key": user.get("plan_key"),
        "access": user.get("access"),
        "workspace_key": user.get("workspace_key"),
        "workspace": user.get("workspace"),
    }

def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None

    user = user_store.get_user(user_id)
    if user is None:
        session.clear()
        return None

    return user

def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if user is None:
            return jsonify({"error": "Autenticação necessária.", "authenticated": False}), 401

        g.current_user = user
        return view_func(*args, **kwargs)

    return wrapper

def is_google_user_allowed(user_info):
    email = user_info.get("email", "").lower()
    domain = email.split("@")[-1] if "@" in email else ""

    if ALLOWED_GOOGLE_EMAILS and email not in ALLOWED_GOOGLE_EMAILS:
        return False

    if ALLOWED_GOOGLE_DOMAIN and domain != ALLOWED_GOOGLE_DOMAIN:
        return False

    return True

def verify_google_credential(credential):
    if not GOOGLE_CLIENT_ID:
        raise RuntimeError("GOOGLE_CLIENT_ID não configurado.")

    token_info = id_token.verify_oauth2_token(
        credential,
        GoogleAuthRequest(),
        GOOGLE_CLIENT_ID,
    )

    issuer = token_info.get("iss")
    if issuer not in {"accounts.google.com", "https://accounts.google.com"}:
        raise ValueError("Issuer inválido para token Google.")

    if not token_info.get("email_verified", False):
        raise ValueError("O email da conta Google não está verificado.")

    if not is_google_user_allowed(token_info):
        raise PermissionError("Conta Google não autorizada para esta aplicação.")

    return token_info

def ensure_rag_ready(workspace):
    documents_path = workspace["documents_path"]
    vectorstore_path = workspace["vectorstore_path"]
    documents_path.mkdir(parents=True, exist_ok=True)

    if rag_engine.is_ready(persist_directory=vectorstore_path):
        return True

    if rag_engine.has_persisted_store(persist_directory=vectorstore_path):
        rag_engine.load_vectorstore(persist_directory=vectorstore_path)
        return rag_engine.is_ready(persist_directory=vectorstore_path)

    try:
        return rag_engine.bootstrap(
            documents_path,
            persist_directory=vectorstore_path,
        )
    except Exception as e:
        print(f"⚠️ Falha ao inicializar o índice vetorial: {e}")
        rag_engine.load_vectorstore(persist_directory=vectorstore_path)
        return rag_engine.is_ready(persist_directory=vectorstore_path)

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path='')
CORS(app, supports_credentials=True)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "beta-secret-change-me")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "").lower() in {"1", "true", "yes"}
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)

# Inicializa o motor RAG
rag_engine = RAGEngine(llm_provider=os.getenv("LLM_PROVIDER"))
user_store = UserStore(USERS_PATH)

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/api/auth/config', methods=['GET'])
def auth_config():
    return jsonify({
        "provider": "google",
        "google_client_id": GOOGLE_CLIENT_ID,
        "enabled": bool(GOOGLE_CLIENT_ID),
    })

@app.route('/api/auth/me', methods=['GET'])
def auth_me():
    user = get_current_user()
    return jsonify({
        "authenticated": user is not None,
        "user": serialize_user(user),
    })

@app.route('/api/auth/google', methods=['POST'])
def auth_google():
    data = request.get_json(silent=True) or {}
    credential = data.get("credential", "").strip()

    if not credential:
        return jsonify({"error": "Credential Google não enviada."}), 400

    try:
        token_info = verify_google_credential(credential)
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": f"Falha na autenticação Google: {e}"}), 401

    user = user_store.upsert_google_user(token_info)
    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]

    return jsonify({
        "authenticated": True,
        "user": serialize_user(user),
    })

@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    session.clear()
    return jsonify({"authenticated": False, "message": "Sessão encerrada."})

@app.route('/api/query', methods=['POST'])
@login_required
def query():
    """Endpoint para consultas"""
    if not has_user_permission("can_query"):
        return jsonify({"error": "Sua conta não tem permissão para consultar documentos."}), 403

    data = request.get_json(silent=True) or {}
    user_query = data.get('query', '')
    
    if not user_query:
        return jsonify({"error": "Query não fornecida"}), 400
    
    try:
        workspace = get_user_workspace()
        if not rag_engine.is_ready(persist_directory=workspace["vectorstore_path"]):
            ensure_rag_ready(workspace)

        result = rag_engine.query(
            user_query,
            k=3,
            persist_directory=workspace["vectorstore_path"],
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/upload', methods=['POST'])
@login_required
def upload_document():
    """Endpoint para upload de documentos"""
    if not has_user_permission("can_upload"):
        return jsonify({"error": "Sua conta não tem permissão para enviar documentos."}), 403

    files = request.files.getlist('file')
    if not files:
        return jsonify({"error": "Nenhum arquivo enviado"}), 400

    workspace = get_user_workspace()
    access = get_user_access()
    limits = access.get("limits") or {}
    documents_path = workspace["documents_path"]
    vectorstore_path = workspace["vectorstore_path"]
    documents_path.mkdir(parents=True, exist_ok=True)

    existing_document_names = {
        file_path.name
        for file_path in get_supported_document_paths(documents_path)
    }
    max_documents = limits.get("max_documents")
    max_file_size_bytes = limits.get("max_file_size_bytes")
    saved_files = []
    ignored_files = []
    oversized_files = []
    valid_uploads = []

    for uploaded_file in files:
        filename = os.path.basename(uploaded_file.filename or '')
        if not filename:
            continue

        if Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
            ignored_files.append(filename)
            continue

        file_size_bytes = get_uploaded_file_size(uploaded_file)
        if isinstance(max_file_size_bytes, int) and file_size_bytes > max_file_size_bytes:
            oversized_files.append({
                "filename": filename,
                "size_bytes": file_size_bytes,
                "limit_bytes": max_file_size_bytes,
            })
            continue

        valid_uploads.append({
            "uploaded_file": uploaded_file,
            "filename": filename,
            "size_bytes": file_size_bytes,
        })

    if oversized_files:
        return jsonify({
            "error": f"O plano atual permite arquivos de até {max_file_size_bytes // BYTES_PER_MB} MB.",
            "code": "upload_file_too_large",
            "files": oversized_files,
            "limits": limits,
            "usage": build_workspace_usage(workspace, access=access),
        }), 413

    projected_document_names = set(existing_document_names)
    for upload in valid_uploads:
        projected_document_names.add(upload["filename"])

    if isinstance(max_documents, int) and len(projected_document_names) > max_documents:
        return jsonify({
            "error": f"O plano atual permite no máximo {max_documents} documento(s) armazenado(s).",
            "code": "upload_document_limit_exceeded",
            "limits": limits,
            "usage": build_workspace_usage(workspace, access=access),
            "projected_documents_count": len(projected_document_names),
        }), 403

    if not valid_uploads:
        return jsonify({"error": "Nenhum arquivo válido enviado"}), 400

    for upload in valid_uploads:
        file_path = documents_path / upload["filename"]
        upload["uploaded_file"].save(file_path)
        saved_files.append(file_path)

    if rag_engine.is_ready(persist_directory=vectorstore_path):
        rag_engine.index_files(saved_files, persist_directory=vectorstore_path)
    else:
        rag_engine.index_directory(
            documents_path,
            persist_directory=vectorstore_path,
        )

    response = {
        "message": "Documentos enviados com sucesso!",
        "filename": saved_files[0].name,
        "filenames": [file_path.name for file_path in saved_files],
        "access": access,
        "usage": build_workspace_usage(workspace, access=access),
    }
    if ignored_files:
        response["ignored"] = ignored_files

    return jsonify(response)

@app.route('/api/status', methods=['GET'])
@login_required
def status():
    """Verifica status do sistema"""
    workspace = get_user_workspace()
    access = get_user_access()
    documents = list_supported_documents(workspace["documents_path"])

    if (
        documents
        and not rag_engine.is_ready(persist_directory=workspace["vectorstore_path"])
        and not rag_engine.has_persisted_store(persist_directory=workspace["vectorstore_path"])
    ):
        ensure_rag_ready(workspace)

    return jsonify({
        "status": "online",
        "documents_count": len(documents),
        "indexed_chunks": rag_engine.get_collection_count(
            persist_directory=workspace["vectorstore_path"]
        ),
        "rag_initialized": rag_engine.is_ready(
            persist_directory=workspace["vectorstore_path"]
        ),
        "llm_provider": rag_engine.llm_provider or "fallback",
        "llm_ready": rag_engine.has_llm(),
        "current_user": serialize_user(g.current_user),
        "access": access,
        "usage": build_workspace_usage(workspace, access=access),
        "workspace": workspace["metadata"],
    })

@app.route('/api/documents', methods=['GET'])
@login_required
def list_documents():
    """Lista documentos disponíveis"""
    workspace = get_user_workspace()
    return jsonify({"documents": list_supported_documents(workspace["documents_path"])})

@app.route('/api/documents/<path:filename>', methods=['DELETE'])
@login_required
def delete_document(filename):
    """Remove um documento do disco e sincroniza o índice vetorial."""
    if not has_user_permission("can_delete_documents"):
        return jsonify({"error": "Sua conta não tem permissão para excluir documentos."}), 403

    workspace = get_user_workspace()
    documents_path = workspace["documents_path"]
    vectorstore_path = workspace["vectorstore_path"]
    safe_name = Path(filename).name
    file_path = (documents_path / safe_name).resolve()

    try:
        file_path.relative_to(documents_path.resolve())
    except ValueError:
        return jsonify({"error": "Caminho de documento inválido"}), 400

    if not file_path.exists() or not file_path.is_file():
        return jsonify({"error": f"Documento não encontrado: {safe_name}"}), 404

    file_path.unlink()

    success = sync_index_with_documents(workspace)
    if not success and get_supported_document_paths(documents_path):
        return jsonify({"error": "Documento removido, mas falhou a sincronização do índice"}), 500

    return jsonify({
        "message": "Documento removido com sucesso.",
        "filename": safe_name,
        "documents_count": len(list_supported_documents(documents_path)),
        "indexed_chunks": rag_engine.get_collection_count(
            persist_directory=vectorstore_path
        )
    })

@app.route('/api/documents/reset', methods=['POST'])
@login_required
def reset_documents():
    """Apaga todos os documentos salvos e zera o índice vetorial."""
    if not has_user_permission("can_reset_workspace"):
        return jsonify({"error": "Sua conta não tem permissão para resetar o workspace."}), 403

    workspace = get_user_workspace()
    success, deleted_files = reset_documents_and_data(workspace)

    if not success:
        return jsonify({"error": "Não foi possível resetar documentos e base vetorial"}), 500

    return jsonify({
        "message": "Documentos e dados resetados com sucesso.",
        "deleted_files": deleted_files,
        "documents_count": len(list_supported_documents(workspace["documents_path"])),
        "indexed_chunks": rag_engine.get_collection_count(
            persist_directory=workspace["vectorstore_path"]
        )
    })

@app.route('/api/vectorstore/reset', methods=['POST'])
@login_required
def reset_vectorstore():
    """Zera a base vetorial sem apagar os arquivos físicos."""
    if not has_user_permission("can_manage_vectorstore"):
        return jsonify({"error": "Sua conta não tem permissão para resetar a base vetorial."}), 403

    workspace = get_user_workspace()
    success = rag_engine.reset_index(
        persist_directory=workspace["vectorstore_path"]
    )

    if not success:
        return jsonify({"error": "Não foi possível resetar o banco vetorial"}), 500

    return jsonify({
        "message": "Banco vetorial resetado com sucesso.",
        "documents_on_disk": len(list_supported_documents(workspace["documents_path"])),
        "indexed_chunks": rag_engine.get_collection_count(
            persist_directory=workspace["vectorstore_path"]
        )
    })

@app.route('/api/vectorstore/reindex', methods=['POST'])
@login_required
def reindex_vectorstore():
    """Reconstrói o banco vetorial a partir dos arquivos em disco."""
    if not has_user_permission("can_manage_vectorstore"):
        return jsonify({"error": "Sua conta não tem permissão para reindexar a base vetorial."}), 403

    workspace = get_user_workspace()
    success = rag_engine.index_directory(
        workspace["documents_path"],
        persist_directory=workspace["vectorstore_path"],
    )

    if not success:
        return jsonify({"error": "Nenhum documento disponível para reindexação"}), 400

    return jsonify({
        "message": "Banco vetorial reindexado com sucesso.",
        "documents_on_disk": len(list_supported_documents(workspace["documents_path"])),
        "indexed_chunks": rag_engine.get_collection_count(
            persist_directory=workspace["vectorstore_path"]
        )
    })

@app.route('/api/vectorstore/documents/<path:filename>', methods=['DELETE'])
@login_required
def delete_document_from_vectorstore(filename):
    """Remove um documento apenas da base vetorial."""
    if not has_user_permission("can_manage_vectorstore"):
        return jsonify({"error": "Sua conta não tem permissão para alterar a base vetorial."}), 403

    workspace = get_user_workspace()
    safe_name = Path(filename).name
    source_path = (workspace["documents_path"] / safe_name).resolve()
    deleted_chunks = rag_engine.delete_document_from_index(
        source_path,
        persist_directory=workspace["vectorstore_path"],
    )

    if deleted_chunks == 0:
        return jsonify({"error": f"Documento não encontrado no banco vetorial: {safe_name}"}), 404

    return jsonify({
        "message": "Documento removido do banco vetorial com sucesso.",
        "filename": safe_name,
        "deleted_chunks": deleted_chunks,
        "documents_on_disk": len(list_supported_documents(workspace["documents_path"])),
        "indexed_chunks": rag_engine.get_collection_count(
            persist_directory=workspace["vectorstore_path"]
        )
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)
