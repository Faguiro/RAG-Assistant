# RAG AI

Aplicação RAG em fase beta para consulta de documentos PDF e TXT com interface web, indexação local em ChromaDB e geração de respostas com fallback local ou LLM externa.

## Status

Este projeto está em beta.

O foco atual é:

- ingestão manual de documentos pela interface
- indexação local com `sentence-transformers` + `Chroma`
- consulta via backend Flask
- uso preferencial de Groq como provedor de LLM
- operações de manutenção para excluir documentos e resetar dados

## Arquitetura

- `frontend/`
  Interface web estática.
- `backend/app.py`
  API Flask e rotas principais.
- `backend/rag_engine.py`
  Orquestra recuperação de contexto e geração de resposta.
- `backend/vector_store.py`
  Carregamento de documentos, embeddings e persistência vetorial.
- `backend/user_access.py`
  Catálogo de planos, permissões e limites de acesso.
- `data/users.json`
  Registro local de usuários autenticados, com papel, plano e workspace.
- `data/users/<workspace_key>/documentos/`
  Documentos isolados por conta Google.
- `data/users/<workspace_key>/chroma_db/`
  Banco vetorial isolado por conta Google.

## Funcionalidades atuais

- upload de múltiplos arquivos `.pdf` e `.txt`
- consulta aos documentos indexados
- exibição de fontes consultadas no frontend
- login Google como gate global da aplicação
- persistência local de usuários autenticados em `data/users.json`
- isolamento de documentos e índice vetorial por conta Google
- conta simples com limite de até 3 arquivos e 5 MB por documento
- exclusão individual de documento
- reset completo dos documentos e do índice vetorial
- reindexação do banco a partir dos arquivos em disco

## Requisitos

- Python 3.11+ ou 3.12
- `pip`
- acesso local ao modelo de embeddings do Hugging Face na primeira execução

## Instalação

Crie e ative um ambiente virtual:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

Instale as dependências:

```powershell
pip install -r backend/requirements.txt
```

## Configuração

Crie ou ajuste `backend/.env`.

Variáveis usadas nesta fase:

```env
GROQ_API_KEY=seu_token_aqui
GROQ_MODEL=llama-3.3-70b-versatile
LLM_PROVIDER=groq
GOOGLE_CLIENT_ID=seu_client_id_google
SECRET_KEY=troque_esta_chave_no_beta
```

Observações:

- `GROQ_API_KEY` é a forma principal de ativar respostas com LLM.
- `GROQ_MODEL` é opcional.
- sem credencial válida, o sistema cai no fallback local e as respostas tendem a ficar mais mecânicas.
- o código ainda aceita OpenAI como caminho alternativo, mas o fluxo principal do projeto está orientado para Groq.
- `GOOGLE_CLIENT_ID` habilita o login Google.
- `SECRET_KEY` protege a sessão autenticada no Flask.
- usuários autenticados são persistidos em `data/users.json`.
- cada conta recebe um workspace próprio em `data/users/<workspace_key>/`.
- o backend já mantém base para papéis e planos de usuário, começando por `member/simple`.

## Como executar

Na raiz do projeto:

```powershell
.\venv\Scripts\python.exe backend\app.py
```

Depois abra:

```text
http://localhost:5000
```

## Fluxo básico

1. Envie documentos pela sidebar.
2. O backend valida o plano da conta atual.
3. Em `simple`, cada conta pode manter até 3 arquivos com no máximo 5 MB por arquivo.
4. O backend salva os arquivos aprovados em `data/users/<workspace_key>/documentos/`.
5. O índice vetorial é criado ou atualizado em `data/users/<workspace_key>/chroma_db/`.
6. Faça perguntas no chat.
7. O sistema recupera chunks relevantes apenas do workspace da conta logada e responde com base nesse contexto.

## Endpoints principais

- `POST /api/query`
  Consulta o RAG.
- `GET /api/auth/config`
  Retorna a configuração pública do login Google.
- `GET /api/auth/me`
  Retorna o usuário autenticado da sessão atual.
- `POST /api/auth/google`
  Valida o token do Google e cria a sessão.
- `POST /api/auth/logout`
  Encerra a sessão autenticada.
- `POST /api/upload`
  Envia documentos respeitando o plano atual da conta.
- `GET /api/status`
  Retorna status da API, documentos, estado do LLM, plano e uso da conta.
- `GET /api/documents`
  Lista documentos disponíveis.
- `DELETE /api/documents/<filename>`
  Remove um documento do disco e sincroniza o índice.
- `POST /api/documents/reset`
  Apaga todos os documentos e zera o banco vetorial.

Endpoints de manutenção adicionais:

- `POST /api/vectorstore/reset`
- `POST /api/vectorstore/reindex`
- `DELETE /api/vectorstore/documents/<filename>`

## Operações de limpeza

Pela interface:

- `Excluir` em um documento: remove o arquivo e reindexa o restante.
- `Resetar tudo`: apaga os documentos enviados e zera os dados persistidos.

Pela API:

```powershell
Invoke-RestMethod -Method Post http://localhost:5000/api/documents/reset
```

## Limitações atuais

- reindexações podem ser lentas com corpus grande
- ainda não existe compartilhamento controlado de documentos entre usuários
- apenas o plano `simple` está definido nesta fase, embora a base para novos níveis já exista
- não há suíte de testes automatizados consolidada
- o projeto ainda não possui fluxo formal de migração de dados
- o Chroma no Windows pode exigir cuidado em operações de manutenção durante desenvolvimento

## Estrutura recomendada para desenvolvimento

```text
RAG_AI/
├── backend/
├── frontend/
├── data/
│   ├── users.json
│   └── users/
│       └── <workspace_key>/
│           ├── documentos/
│           └── chroma_db/
├── README.md
└── .gitignore
```

## Notas para esta fase beta

- trate `data/users/<workspace_key>/` como dado local de trabalho da conta correspondente
- não versione credenciais reais
- não considere a interface atual como estável
- prefira testar reset e exclusão em documentos temporários antes de usar corpus importante
