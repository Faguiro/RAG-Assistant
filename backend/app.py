from datetime import timedelta
from functools import wraps
from flask import Flask, g, jsonify, request, send_from_directory, session
from flask_cors import CORS
import os
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
DOCUMENTS_PATH = PROJECT_ROOT / 'data' / 'documentos'
USERS_PATH = PROJECT_ROOT / 'data' / 'users.json'
SUPPORTED_EXTENSIONS = {'.pdf', '.txt'}
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(BACKEND_DIR / ".env", override=True)
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
ALLOWED_GOOGLE_DOMAIN = os.getenv("GOOGLE_ALLOWED_DOMAIN", "").strip().lower()
ALLOWED_GOOGLE_EMAILS = {
    email.strip().lower()
    for email in os.getenv("GOOGLE_ALLOWED_EMAILS", "").split(",")
    if email.strip()
}

def list_supported_documents():
    if not DOCUMENTS_PATH.exists():
        return []

    return sorted(
        file_path.name
        for file_path in DOCUMENTS_PATH.iterdir()
        if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS
    )

def get_supported_document_paths():
    if not DOCUMENTS_PATH.exists():
        return []

    return sorted(
        file_path
        for file_path in DOCUMENTS_PATH.iterdir()
        if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS
    )

def sync_index_with_documents():
    documents = get_supported_document_paths()
    if documents:
        return rag_engine.index_directory(DOCUMENTS_PATH)

    return rag_engine.reset_index()

def reset_documents_and_data():
    DOCUMENTS_PATH.mkdir(parents=True, exist_ok=True)

    deleted_files = []
    for file_path in get_supported_document_paths():
        file_path.unlink(missing_ok=True)
        deleted_files.append(file_path.name)

    success = rag_engine.reset_index()
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

def ensure_rag_ready():
    DOCUMENTS_PATH.mkdir(parents=True, exist_ok=True)

    if rag_engine.is_ready():
        return True

    if rag_engine.vector_store.has_persisted_store():
        rag_engine.vector_store.load_vectorstore()
        return rag_engine.is_ready()

    try:
        return rag_engine.bootstrap(DOCUMENTS_PATH)
    except Exception as e:
        print(f"⚠️ Falha ao inicializar o índice vetorial: {e}")
        rag_engine.vector_store.load_vectorstore()
        return rag_engine.is_ready()

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
    data = request.get_json(silent=True) or {}
    user_query = data.get('query', '')
    
    if not user_query:
        return jsonify({"error": "Query não fornecida"}), 400
    
    try:
        if not rag_engine.is_ready():
            ensure_rag_ready()

        result = rag_engine.query(user_query, k=3)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/upload', methods=['POST'])
@login_required
def upload_document():
    """Endpoint para upload de documentos"""
    files = request.files.getlist('file')
    if not files:
        return jsonify({"error": "Nenhum arquivo enviado"}), 400

    DOCUMENTS_PATH.mkdir(parents=True, exist_ok=True)

    saved_files = []
    ignored_files = []

    for uploaded_file in files:
        filename = os.path.basename(uploaded_file.filename or '')
        if not filename:
            continue

        if Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
            ignored_files.append(filename)
            continue

        file_path = DOCUMENTS_PATH / filename
        uploaded_file.save(file_path)
        saved_files.append(file_path)

    if not saved_files:
        return jsonify({"error": "Nenhum arquivo válido enviado"}), 400

    if rag_engine.is_ready():
        rag_engine.index_files(saved_files)
    else:
        rag_engine.index_directory(DOCUMENTS_PATH)

    response = {
        "message": "Documentos enviados com sucesso!",
        "filename": saved_files[0].name,
        "filenames": [file_path.name for file_path in saved_files]
    }
    if ignored_files:
        response["ignored"] = ignored_files

    return jsonify(response)

@app.route('/api/status', methods=['GET'])
@login_required
def status():
    """Verifica status do sistema"""
    documents = list_supported_documents()

    if documents and not rag_engine.is_ready() and not rag_engine.vector_store.has_persisted_store():
        ensure_rag_ready()

    return jsonify({
        "status": "online",
        "documents_count": len(documents),
        "indexed_chunks": rag_engine.vector_store.get_collection_count(),
        "rag_initialized": rag_engine.is_ready(),
        "llm_provider": rag_engine.llm_provider or "fallback",
        "llm_ready": rag_engine.has_llm(),
        "current_user": serialize_user(g.current_user),
    })

@app.route('/api/documents', methods=['GET'])
@login_required
def list_documents():
    """Lista documentos disponíveis"""
    return jsonify({"documents": list_supported_documents()})

@app.route('/api/documents/<path:filename>', methods=['DELETE'])
@login_required
def delete_document(filename):
    """Remove um documento do disco e sincroniza o índice vetorial."""
    safe_name = Path(filename).name
    file_path = (DOCUMENTS_PATH / safe_name).resolve()

    try:
        file_path.relative_to(DOCUMENTS_PATH.resolve())
    except ValueError:
        return jsonify({"error": "Caminho de documento inválido"}), 400

    if not file_path.exists() or not file_path.is_file():
        return jsonify({"error": f"Documento não encontrado: {safe_name}"}), 404

    file_path.unlink()

    success = sync_index_with_documents()
    if not success and get_supported_document_paths():
        return jsonify({"error": "Documento removido, mas falhou a sincronização do índice"}), 500

    return jsonify({
        "message": "Documento removido com sucesso.",
        "filename": safe_name,
        "documents_count": len(list_supported_documents()),
        "indexed_chunks": rag_engine.vector_store.get_collection_count()
    })

@app.route('/api/documents/reset', methods=['POST'])
@login_required
def reset_documents():
    """Apaga todos os documentos salvos e zera o índice vetorial."""
    success, deleted_files = reset_documents_and_data()

    if not success:
        return jsonify({"error": "Não foi possível resetar documentos e base vetorial"}), 500

    return jsonify({
        "message": "Documentos e dados resetados com sucesso.",
        "deleted_files": deleted_files,
        "documents_count": len(list_supported_documents()),
        "indexed_chunks": rag_engine.vector_store.get_collection_count()
    })

@app.route('/api/vectorstore/reset', methods=['POST'])
@login_required
def reset_vectorstore():
    """Zera a base vetorial sem apagar os arquivos físicos."""
    success = rag_engine.reset_index()

    if not success:
        return jsonify({"error": "Não foi possível resetar o banco vetorial"}), 500

    return jsonify({
        "message": "Banco vetorial resetado com sucesso.",
        "documents_on_disk": len(list_supported_documents()),
        "indexed_chunks": rag_engine.vector_store.get_collection_count()
    })

@app.route('/api/vectorstore/reindex', methods=['POST'])
@login_required
def reindex_vectorstore():
    """Reconstrói o banco vetorial a partir dos arquivos em disco."""
    success = rag_engine.index_directory(DOCUMENTS_PATH)

    if not success:
        return jsonify({"error": "Nenhum documento disponível para reindexação"}), 400

    return jsonify({
        "message": "Banco vetorial reindexado com sucesso.",
        "documents_on_disk": len(list_supported_documents()),
        "indexed_chunks": rag_engine.vector_store.get_collection_count()
    })

@app.route('/api/vectorstore/documents/<path:filename>', methods=['DELETE'])
@login_required
def delete_document_from_vectorstore(filename):
    """Remove um documento apenas da base vetorial."""
    safe_name = Path(filename).name
    source_path = (DOCUMENTS_PATH / safe_name).resolve()
    deleted_chunks = rag_engine.delete_document_from_index(source_path)

    if deleted_chunks == 0:
        return jsonify({"error": f"Documento não encontrado no banco vetorial: {safe_name}"}), 404

    return jsonify({
        "message": "Documento removido do banco vetorial com sucesso.",
        "filename": safe_name,
        "deleted_chunks": deleted_chunks,
        "documents_on_disk": len(list_supported_documents()),
        "indexed_chunks": rag_engine.vector_store.get_collection_count()
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)
