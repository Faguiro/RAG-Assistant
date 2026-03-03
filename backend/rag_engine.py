import os
from pathlib import Path
from threading import Lock
from dotenv import load_dotenv

try:
    from groq import Groq
except ImportError:
    Groq = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    from .vector_store import VectorStoreManager
except ImportError:
    from vector_store import VectorStoreManager

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(BACKEND_DIR / ".env", override=True)


class RAGEngine:
    def __init__(self, use_openai=False, llm_provider=None):
        self._vector_store_lock = Lock()
        self._vector_stores = {}
        self.vector_store = self._get_vector_store()
        self.llm_client = None
        self.llm_model = None
        self.llm_provider = self._resolve_llm_provider(
            use_openai=use_openai,
            llm_provider=llm_provider,
        )

        self._initialize_llm_client()

    def _resolve_llm_provider(self, use_openai=False, llm_provider=None):
        provider = (llm_provider or os.getenv("LLM_PROVIDER", "")).strip().lower()
        if provider:
            return provider

        if use_openai:
            return "openai"

        return "groq"

    def _initialize_llm_client(self):
        if self.llm_provider == "groq":
            self._initialize_groq_client()
        elif self.llm_provider == "openai":
            self._initialize_openai_client()
        elif self.llm_provider:
            print(f"⚠️ Provedor de LLM não suportado: {self.llm_provider}. Usando fallback sem LLM.")
            self.llm_provider = None

    def _initialize_groq_client(self):
        api_key = os.getenv("GROQ_API_KEY")
        self.llm_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

        if not api_key:
            print("⚠️ GROQ_API_KEY não encontrada. Usando fallback sem LLM.")
            self.llm_provider = None
            return

        if Groq is None:
            print("⚠️ SDK Groq não instalada. Usando fallback sem LLM.")
            self.llm_provider = None
            return

        try:
            self.llm_client = Groq(api_key=api_key)
        except Exception as e:
            print(f"⚠️ Falha ao inicializar cliente Groq: {e}")
            print("Usando fallback sem LLM.")
            self.llm_provider = None

    def _initialize_openai_client(self):
        api_key = os.getenv("OPENAI_API_KEY")
        self.llm_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        if not api_key:
            print("⚠️ OPENAI_API_KEY não encontrada. Usando fallback sem LLM.")
            self.llm_provider = None
            return

        if OpenAI is None:
            print("⚠️ SDK OpenAI não instalada. Usando fallback sem LLM.")
            self.llm_provider = None
            return

        try:
            self.llm_client = OpenAI(api_key=api_key)
        except Exception as e:
            print(f"⚠️ Falha ao inicializar cliente OpenAI: {e}")
            print("Usando fallback sem LLM.")
            self.llm_provider = None

    def has_llm(self):
        """Indica se há um provedor de LLM pronto para uso."""
        return self.llm_client is not None

    def _resolve_persist_directory(self, persist_directory=None):
        if persist_directory is None:
            if getattr(self, "vector_store", None) is not None:
                return self.vector_store.persist_directory

            return (PROJECT_ROOT / "chroma_db").resolve()

        return Path(persist_directory).expanduser().resolve()

    def _get_vector_store(self, persist_directory=None):
        resolved_directory = self._resolve_persist_directory(persist_directory)
        workspace_key = str(resolved_directory)

        with self._vector_store_lock:
            vector_store = self._vector_stores.get(workspace_key)
            if vector_store is None:
                vector_store = VectorStoreManager(persist_directory=resolved_directory)
                self._vector_stores[workspace_key] = vector_store

        return vector_store

    def load_vectorstore(self, persist_directory=None):
        return self._get_vector_store(persist_directory).load_vectorstore()

    def has_persisted_store(self, persist_directory=None):
        return self._get_vector_store(persist_directory).has_persisted_store()

    def get_collection_count(self, persist_directory=None):
        return self._get_vector_store(persist_directory).get_collection_count()

    def is_ready(self, persist_directory=None):
        """Indica se o índice vetorial está pronto para busca."""
        return self._get_vector_store(persist_directory).has_indexed_documents()

    def bootstrap(self, data_path, persist_directory=None):
        """Garante que documentos existentes em disco sejam indexados."""
        vector_store = self._get_vector_store(persist_directory)

        if vector_store.has_indexed_documents():
            return True

        print(f"📂 Verificando documentos existentes em: {data_path}")
        documents = vector_store.load_documents(data_path=data_path)

        if not documents:
            print("⚠️ Nenhum documento encontrado para inicializar o índice")
            return False

        print("🆕 Inicializando banco vetorial a partir dos documentos existentes...")
        return vector_store.create_vectorstore(documents)

    def index_directory(self, data_path, persist_directory=None):
        """Reindexa completamente o diretório informado."""
        vector_store = self._get_vector_store(persist_directory)
        print(f"📂 Reindexando documentos de: {data_path}")
        documents = vector_store.load_documents(data_path=data_path)

        if not documents:
            print("⚠️ Nenhum documento encontrado")
            return False

        return vector_store.create_vectorstore(documents)

    def index_files(self, file_paths, persist_directory=None):
        """Indexa apenas os arquivos informados, substituindo versões anteriores."""
        vector_store = self._get_vector_store(persist_directory)
        print(f"📄 Indexando {len(file_paths)} arquivo(s) enviado(s)")
        documents = vector_store.load_documents(file_paths=file_paths)

        if not documents:
            print("⚠️ Nenhum documento válido encontrado para indexação")
            return False

        if vector_store.has_indexed_documents():
            return vector_store.add_documents(documents)

        return vector_store.create_vectorstore(documents)

    def delete_document_from_index(self, document_path, persist_directory=None):
        """Remove um documento específico apenas do índice vetorial."""
        return self._get_vector_store(persist_directory).delete_document_by_source(document_path)

    def reset_index(self, persist_directory=None):
        """Zera o índice vetorial sem apagar os arquivos de origem."""
        return self._get_vector_store(persist_directory).reset_vectorstore()

    def get_relevant_context(self, query, k=3, persist_directory=None):
        """Recupera contexto relevante para a query."""
        results = self._get_vector_store(persist_directory).search_similar(query, k=k)

        if not results:
            return "", []

        context = ""
        sources = []

        for doc, score in results:
            context += doc.page_content + "\n\n"
            source_file = doc.metadata.get("source", "Desconhecido")
            if source_file != "Desconhecido":
                source_file = Path(source_file).name

            sources.append({
                "content": doc.page_content[:150] + "...",
                "source": source_file,
                "relevance": round(score, 3)
            })

        return context, sources

    # def _build_prompt(self, query, context):
    #     return f"""Responda em portugues do Brasil, com linguagem natural e objetiva.
    #     Use apenas o contexto fornecido.
    #     Nao invente fatos, nao extrapole e nao complete lacunas com suposicoes.
    #     Se a resposta nao estiver no contexto, diga isso explicitamente.
    #     Sintetize as informacoes como uma explicacao humana, sem copiar blocos longos do texto.


    #     Contexto:
    #     {context}

    #     Pergunta:
    #     {query}

    #     Resposta:"""

    def _build_prompt(self, query, context):
        return f"""Você é um bibliotecário experiente e prestativo. Seu papel é ajudar as pessoas a 
        encontrar e compreender informações nos documentos disponíveis.

        DIRETRIZES:
        - Responda em português do Brasil, com linguagem clara e acessível
        - Base-se exclusivamente no contexto fornecido - você é guardião desses documentos
        - Se a informação não estiver nos documentos, seja honesto: "Não encontrei essa informação nos documentos disponíveis"
        - Sintetize as informações de forma didática, como se estivesse explicando para alguém
        - Cite referências quando relevante: "De acordo com o documento X..."
        - Se houver informações relacionadas que possam ajudar, mencione-as

        Contexto (documentos disponíveis):
        {context}

        Pergunta do visitante:
        {query}

        Sua orientação:"""
         
    def generate_response_llm(self, query, context):
        """Gera resposta usando o provedor LLM configurado."""
        if self.llm_client is None:
            return self.generate_response_simple(query, context)

        try:
            response = self.llm_client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Voce responde perguntas com base exclusiva no contexto fornecido, "
                            "em portugues do Brasil, com linguagem natural e clara."
                        ),
                    },
                    {
                        "role": "user",
                        "content": self._build_prompt(query, context),
                    },
                ],
                model=self.llm_model,
                temperature=0.5,
                max_tokens=400,
            )

            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"❌ Erro ao chamar {self.llm_provider}: {e}")
            return self.generate_response_simple(query, context)

    def generate_response_simple(self, query, context):
        """Gera resposta simples (fallback sem LLM)."""
        if not context.strip():
            return "Não encontrei informação suficiente para responder."

        paragraphs = [paragraph.strip() for paragraph in context.split('\n\n') if paragraph.strip()]
        if paragraphs:
            relevant_paragraph = paragraphs[0]
            return f"Com base nos documentos encontrados:\n\n{relevant_paragraph}"

        return "Não encontrei informação suficiente para responder."

    def query(self, query, k=3, persist_directory=None):
        """Processa uma consulta completa."""
        print(f"🔍 Processando consulta: {query}")

        context, sources = self.get_relevant_context(
            query,
            k=k,
            persist_directory=persist_directory,
        )

        if not context.strip():
            print("⚠️ Nenhum documento relevante encontrado")
            return {
                "answer": "Não encontrei documentos relevantes para sua pergunta. Tente fazer upload de mais documentos.",
                "sources": []
            }

        print(f"📚 Contexto recuperado ({len(sources)} fontes)")

        if self.has_llm():
            answer = self.generate_response_llm(query, context)
        else:
            answer = self.generate_response_simple(query, context)

        return {
            "answer": answer,
            "sources": sources,
            "context": context[:500] + "..."
        }
