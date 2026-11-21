# Architecture

Diagrams are Mermaid, so GitHub renders them and they change in the same commit
as the code. Two views:

- **Current state:** what exists in the repo today. Updated at the end of every phase.
- **Target:** where the project is heading. Changes only when a decision changes.

---

## Current state: Phase 1 (fully local)

```mermaid
flowchart TB
  subgraph Sources
    PDF[Well-Architected PDFs]
    MD[Runbooks .md]
  end

  subgraph Ingest["kb ingest"]
    L[Loader<br/>PyMuPDF + TOC] --> C[Chunker<br/>1200 chars, 200 overlap]
    C --> FP{Fingerprint<br/>changed?}
    FP -- yes --> E[Embed in batches]
    FP -- no --> SKIP[Skip]
  end

  subgraph Local["Local machine"]
    OL[(Ollama<br/>nomic-embed-text<br/>llama3.2)]
    PG[(Postgres + pgvector<br/>HNSW cosine index)]
  end

  subgraph Ask["kb ask / POST /ask"]
    Q[Question] --> QE[Embed question]
    QE --> S[Top-k search<br/>similarity floor]
    S -- nothing relevant --> NF[Not found<br/>no model call]
    S -- chunks --> P[Prompt with<br/>numbered sources]
    P --> G[Generate]
    G --> A[Answer + citations<br/>tokens + cost]
  end

  PDF --> L
  MD --> L
  E <--> OL
  E --> PG
  QE <--> OL
  S <--> PG
  G <--> OL
```

### Ask: sequence

```mermaid
sequenceDiagram
  actor U as User
  participant API as CLI / FastAPI
  participant R as RagPipeline
  participant EM as Embeddings
  participant DB as pgvector
  participant LLM as Chat model

  U->>API: question
  API->>R: answer(question)
  R->>EM: embed_query("search_query: " + question)
  EM-->>R: vector (768)
  R->>DB: ORDER BY embedding <=> vector LIMIT k
  DB-->>R: chunks + similarity
  alt no chunk above the similarity floor
    R-->>API: "not found" (no model call, $0)
  else
    R->>LLM: system rules + sources in user message
    LLM-->>R: answer with [n] markers + token usage
    R-->>API: answer, citations, tokens, cost
  end
  API-->>U: response
```

### Data model

```mermaid
erDiagram
  kb_documents ||--o{ kb_chunks_SPACE : has
  kb_documents ||--o{ kb_ingest_state : "tracked in"
  kb_documents {
    text document_id PK
    text title
    text uri
  }
  kb_chunks_SPACE {
    text chunk_id PK
    text document_id FK
    int ordinal
    text section
    int page
    text content
    vector embedding
    tsvector content_tsv
  }
  kb_ingest_state {
    text space PK
    text document_id PK
    text fingerprint
    int chunk_count
  }
```

`SPACE` is the embedding space, for example `ollama_nomic_embed_text_768`.

---

## Target architecture (end of Phase 8)

```mermaid
flowchart TB
  user([User]) --> CF[CloudFront + S3<br/>React UI]
  agent([MCP clients<br/>Claude Desktop, IDEs]) --> MCP

  CF --> API
  subgraph VPC["VPC (private subnets, VPC endpoints, no NAT)"]
    API[FastAPI on ECS Fargate<br/>ARM64, SSE streaming]
    MCP[MCP server<br/>search_docs, get_source]
    AG[LangGraph agent]
    ING[Ingestion Lambda]
  end

  COG[Cognito] -.auth.-> API
  S3IN[(S3 raw documents)] -- event --> SQS[[SQS + DLQ]] --> ING
  ING --> BR
  ING --> VEC[(S3 Vectors)]
  API --> AG
  AG --> MCP
  API --> VEC
  MCP --> VEC
  API --> BR[Amazon Bedrock<br/>Nova / Claude, Titan embeddings<br/>Guardrails]
  API --> DDB[(DynamoDB<br/>conversations, feedback,<br/>semantic cache)]

  API -.traces.-> LF[Langfuse]
  API -.metrics, logs.-> CW[CloudWatch + X-Ray]
  GH[GitHub Actions<br/>OIDC, eval gate] -.deploys.-> API
  TF[Terraform] -.provisions.-> VPC
```
