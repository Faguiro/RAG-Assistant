import gc
import shutil
import tempfile
import time
from pathlib import Path
from threading import Lock
from chromadb.api.client import SharedSystemClient
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
DEFAULT_PERSIST_DIRECTORY = PROJECT_ROOT / "chroma_db"
DEFAULT_DOCUMENTS_DIRECTORY = PROJECT_ROOT / "data" / "documentos"
SUPPORTED_EXTENSIONS = {".pdf", ".txt"}


class VectorStoreManager:
    _shared_embeddings = None
    _embeddings_lock = Lock()

    def __init__(self, persist_directory=None):
        self.persist_directory = Path(
            persist_directory or DEFAULT_PERSIST_DIRECTORY
        ).resolve()
        self.embeddings = self._get_embeddings()
        self.vectorstore = None

    @classmethod
    def _get_embeddings(cls):
        if cls._shared_embeddings is not None:
            return cls._shared_embeddings

        with cls._embeddings_lock:
            if cls._shared_embeddings is None:
                # Reaproveita o mesmo modelo de embeddings entre workspaces.
                cls._shared_embeddings = HuggingFaceEmbeddings(
                    model_name="sentence-transformers/all-MiniLM-L6-v2",
                    model_kwargs={'device': 'cpu'}
                )

        return cls._shared_embeddings

    def _split_documents(self, documents):
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
            length_function=len,
            separators=["\n\n", "\n", " ", ""]
        )
        chunks = text_splitter.split_documents(documents)
        print(f"✅ Total de chunks criados: {len(chunks)}")
        return chunks

    def _resolve_document_paths(self, data_path=None, file_paths=None):
        if file_paths is not None:
            resolved_paths = [Path(file_path).expanduser().resolve() for file_path in file_paths]
        else:
            documents_dir = Path(data_path or DEFAULT_DOCUMENTS_DIRECTORY).expanduser().resolve()
            if not documents_dir.exists():
                print(f"📁 Diretório {documents_dir} não existe, criando...")
                documents_dir.mkdir(parents=True, exist_ok=True)
                return []
            resolved_paths = sorted(path.resolve() for path in documents_dir.iterdir() if path.is_file())

        valid_paths = []
        for file_path in resolved_paths:
            if not file_path.exists() or not file_path.is_file():
                print(f"⚠️ Arquivo ignorado (não encontrado): {file_path}")
                continue

            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                print(f"⚠️ Formato ignorado: {file_path.name}")
                continue

            valid_paths.append(file_path)

        return valid_paths

    def get_collection_count(self):
        """Retorna a quantidade de chunks indexados."""
        if self.vectorstore is None:
            return 0

        try:
            return self.vectorstore._collection.count()
        except Exception as e:
            print(f"⚠️ Erro ao contar documentos indexados: {e}")
            return 0

    def has_indexed_documents(self):
        """Indica se o banco vetorial possui conteúdo indexado."""
        return self.get_collection_count() > 0

    def has_persisted_store(self):
        """Indica se existe uma estrutura persistida do banco vetorial."""
        return self.persist_directory.exists()

    def _stop_client(self, client):
        """Libera o cliente do Chroma e remove o cache compartilhado do processo."""
        if client is None:
            return

        identifier = getattr(client, "_identifier", None)
        system = getattr(client, "_system", None)

        if system is not None:
            system.stop()

        if identifier:
            SharedSystemClient._identifer_to_system.pop(identifier, None)
         
    def close_connection(self):
        """Fecha a conexão com o ChromaDB corretamente"""
        if hasattr(self, 'vectorstore') and self.vectorstore is not None:
            try:
                # Tenta acessar o cliente interno e parar
                if hasattr(self.vectorstore, '_client'):
                    self._stop_client(self.vectorstore._client)
                # Força a liberação da conexão
                self.vectorstore = None
                # Força coleta de lixo
                gc.collect()
                # Pequena pausa para o sistema liberar o arquivo
                time.sleep(1)
                print("✅ Conexão com ChromaDB fechada")
            except Exception as e:
                print(f"⚠️ Erro ao fechar conexão: {e}")

    def _delete_collection(self):
        """Remove a coleção atual do Chroma sem apagar manualmente a pasta do banco."""
        if self.vectorstore is None:
            self.load_vectorstore()

        if self.vectorstore is None:
            self.close_connection()
            return True

        try:
            self.vectorstore.delete_collection()
            print("✅ Coleção vetorial removida")
        except Exception as e:
            if "does not exist" in str(e).lower():
                print("⚠️ Coleção vetorial não existia mais; seguindo com o reset.")
            else:
                print(f"⚠️ Erro ao remover coleção vetorial: {e}")
                return False
        finally:
            self.close_connection()

        return True
    
    def load_documents(self, data_path=None, file_paths=None):
        """Carrega documentos de um diretório ou de arquivos específicos."""
        documents = []

        for file_path in self._resolve_document_paths(data_path=data_path, file_paths=file_paths):
            try:
                if file_path.suffix.lower() == '.pdf':
                    print(f"📄 Carregando PDF: {file_path.name}")
                    loader = PyPDFLoader(str(file_path))
                    documents.extend(loader.load())

                elif file_path.suffix.lower() == '.txt':
                    print(f"📄 Carregando TXT: {file_path.name}")
                    loader = TextLoader(str(file_path), encoding='utf-8')
                    documents.extend(loader.load())

            except Exception as e:
                print(f"❌ Erro ao carregar {file_path.name}: {e}")

        print(f"✅ Total de documentos carregados: {len(documents)}")
        return documents
    
    def create_vectorstore(self, documents):
        """Cria o banco vetorial a partir dos documentos"""
        if not documents:
            print("⚠️ Nenhum documento para processar")
            return False

        chunks = self._split_documents(documents)

        if self.persist_directory.exists():
            print("🗑️ Limpando coleção vetorial antiga...")
            if not self._delete_collection():
                return False
        else:
            self.close_connection()

        # Cria novo banco vetorial
        print("💾 Criando novo banco vetorial...")
        self.persist_directory.parent.mkdir(parents=True, exist_ok=True)
        self.vectorstore = Chroma.from_documents(
            documents=chunks,
            embedding=self.embeddings,
            persist_directory=str(self.persist_directory)
        )
        print("✅ Banco vetorial criado e persistido com sucesso!")
        return True
    
    def _create_vectorstore_temp(self, chunks):
        """Método alternativo: cria em diretório temporário e copia"""
        with tempfile.TemporaryDirectory() as temp_dir:
            print(f"📁 Criando banco temporário em: {temp_dir}")
            temp_vectorstore = Chroma.from_documents(
                documents=chunks,
                embedding=self.embeddings,
                persist_directory=temp_dir
            )
            
            # Fecha conexão temporária
            if hasattr(temp_vectorstore, '_client'):
                self._stop_client(temp_vectorstore._client)
                temp_vectorstore = None
                gc.collect()
            
            # Aguarda e substitui
            time.sleep(2)
            
            # Remove antigo se existir
            if self.persist_directory.exists():
                shutil.rmtree(self.persist_directory, ignore_errors=True)
            
            # Copia temporário para destino final
            print("📋 Copiando banco para diretório final...")
            shutil.copytree(temp_dir, self.persist_directory)
        
        # Recarrega o banco
        self.load_vectorstore()
        print("✅ Banco vetorial criado com sucesso (método alternativo)!")
    
    def add_documents(self, documents):
        """Adiciona ou substitui documentos no banco existente sem duplicar fontes."""
        if not documents:
            print("⚠️ Nenhum documento para adicionar")
            return False

        chunks = self._split_documents(documents)
        
        # Carrega banco existente
        self.load_vectorstore()
        
        # Adiciona ao banco existente
        if self.vectorstore is not None:
            source_paths = sorted({
                doc.metadata.get("source")
                for doc in documents
                if doc.metadata.get("source")
            })

            for source_path in source_paths:
                self.vectorstore._collection.delete(where={"source": source_path})

            print("➕ Adicionando documentos ao banco existente...")
            self.vectorstore.add_documents(chunks)
            print("✅ Documentos adicionados com sucesso!")
            return True
        else:
            print("⚠️ Banco não existe, criando novo...")
            return self.create_vectorstore(documents)

    def delete_document_by_source(self, source_path):
        """Remove todos os chunks de um documento específico do banco vetorial."""
        if self.vectorstore is None:
            self.load_vectorstore()

        if self.vectorstore is None:
            print("⚠️ Banco não disponível para exclusão")
            return 0

        resolved_source = str(Path(source_path).expanduser().resolve())
        matches = self.vectorstore._collection.get(
            where={"source": resolved_source},
            include=[]
        )
        ids = matches.get("ids", [])

        if not ids:
            print(f"⚠️ Nenhum chunk encontrado para a fonte: {resolved_source}")
            return 0

        self.vectorstore.delete(ids=ids)
        print(f"✅ Documento removido do banco vetorial: {Path(resolved_source).name} ({len(ids)} chunks)")
        return len(ids)

    def reset_vectorstore(self):
        """Zera o banco vetorial persistido, mantendo os arquivos físicos intactos."""
        self.persist_directory.parent.mkdir(parents=True, exist_ok=True)

        if self.persist_directory.exists():
            if not self._delete_collection():
                return False
        else:
            self.close_connection()

        self.load_vectorstore()
        print("✅ Banco vetorial resetado")
        return True
    
    def load_vectorstore(self):
        """Carrega o banco vetorial existente"""
        if self.persist_directory.exists():
            try:
                print("📂 Carregando banco vetorial existente...")
                self.vectorstore = Chroma(
                    persist_directory=str(self.persist_directory),
                    embedding_function=self.embeddings
                )
                print(f"✅ Banco vetorial carregado ({self.get_collection_count()} chunks)")
            except Exception as e:
                print(f"❌ Erro ao carregar banco: {e}")
                self.vectorstore = None
        else:
            print("⚠️ Nenhum banco vetorial encontrado")
            self.vectorstore = None
        
        return self.vectorstore
    
    def search_similar(self, query, k=3):
        """Busca documentos similares à query"""
        if self.vectorstore is None:
            self.load_vectorstore()
        
        if self.vectorstore is None:
            print("⚠️ Banco não disponível para busca")
            return []

        if not self.has_indexed_documents():
            print("⚠️ Banco vetorial vazio")
            return []
        
        results = self.vectorstore.similarity_search_with_score(query, k=k)
        return results
