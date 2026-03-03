import os
from pathlib import Path
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
        self.vector_store = VectorStoreManager()
        self.llm_client = None
        self.llm_model = None
        self.llm_provider = self._resolve_llm_provider(
            use_openai=use_openai,
            llm_provider=llm_provider,
        )

        self._initialize_llm_client()

        try:
            self.vector_store.load_vectorstore()
        except Exception as e:
            print(f"⚠️ Banco vetorial não encontrado: {e}")
            print("Será necessário criar um novo ao adicionar documentos.")

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

    def is_ready(self):
        """Indica se o índice vetorial está pronto para busca."""
        return self.vector_store.has_indexed_documents()

    def bootstrap(self, data_path):
        """Garante que documentos existentes em disco sejam indexados."""
        if self.is_ready():
            return True

        print(f"📂 Verificando documentos existentes em: {data_path}")
        documents = self.vector_store.load_documents(data_path=data_path)

        if not documents:
            print("⚠️ Nenhum documento encontrado para inicializar o índice")
            return False

        print("🆕 Inicializando banco vetorial a partir dos documentos existentes...")
        return self.vector_store.create_vectorstore(documents)

    def index_directory(self, data_path):
        """Reindexa completamente o diretório informado."""
        print(f"📂 Reindexando documentos de: {data_path}")
        documents = self.vector_store.load_documents(data_path=data_path)

        if not documents:
            print("⚠️ Nenhum documento encontrado")
            return False

        return self.vector_store.create_vectorstore(documents)

    def index_files(self, file_paths):
        """Indexa apenas os arquivos informados, substituindo versões anteriores."""
        print(f"📄 Indexando {len(file_paths)} arquivo(s) enviado(s)")
        documents = self.vector_store.load_documents(file_paths=file_paths)

        if not documents:
            print("⚠️ Nenhum documento válido encontrado para indexação")
            return False

        if self.is_ready():
            return self.vector_store.add_documents(documents)

        return self.vector_store.create_vectorstore(documents)

    def delete_document_from_index(self, document_path):
        """Remove um documento específico apenas do índice vetorial."""
        return self.vector_store.delete_document_by_source(document_path)

    def reset_index(self):
        """Zera o índice vetorial sem apagar os arquivos de origem."""
        return self.vector_store.reset_vectorstore()

    def get_relevant_context(self, query, k=3):
        """Recupera contexto relevante para a query."""
        results = self.vector_store.search_similar(query, k=k)

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
        return f"""Responda em portugues do Brasil, com linguagem natural e objetiva.
        Use apenas o contexto fornecido, Mas explique e dê exemplos, como um professor.
        Nao invente fatos, nao extrapole e nao complete lacunas com suposicoes. Explique o que o contexto fornece.
        Se a resposta nao estiver no contexto, diga isso explicitamente.
        Sintetize as informacoes como uma explicacao humana, sem copiar blocos longos do texto.


        Contexto:
        {context}

        Pergunta:
        {query}

        Resposta:"""

      
   
   
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

    def query(self, query, k=3):
        """Processa uma consulta completa."""
        print(f"🔍 Processando consulta: {query}")

        context, sources = self.get_relevant_context(query, k)

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
