# AI Agent Operating System (AI-OS)
Version: 1.0.0  
Status: ACTIVE  
Scope: Repository-wide AI development guidelines

This document defines the mandatory operational constraints and execution phases for any AI coding agent interacting with this repository. 

**Rule Zero:** The AI agent is not permitted to write code, modify files, or suggest changes without first classifying the issue and executing the required prerequisite phases.

---

## 1. Task Classification Framework
Before any file edits are proposed, the AI agent must classify the user's request into one of the following categories. Each category mandates a specific path through the execution phases:

| Category | Description | Mandatory Execution Path |
| :--- | :--- | :--- |
| **Category A: Bug Fix** | Resolving crashes, logical errors, or incorrect scoring calculations. | `Phase 1 (Discussion & Root Cause)` → `Phase 5 (Implementation Planning)` → `Phase 6 (Code Gen)` → `Phase 7 (Validation)` |
| **Category B: Feature Enhancement** | Adding new modular capability (e.g., Sentiment analysis, scheduling tools, memory). | `Phase 1` → `Phase 2 (Architecture)` → `Phase 3 (Risk Review)` → `Phase 4 (Edge Cases)` → `Phase 5` → `Phase 6` → `Phase 7` |
| **Category C: Infrastructure Shift** | Deep changes (e.g., pgvector migrations, multi-tenant databases, connection pools). | `Phase 1` → `Phase 2` → `Phase 3` → `Phase 5` → `Phase 6` → `Phase 7` |
| **Category D: AI Pipeline Tuning** | Prompt engineering adjustments, RAG retrieval updates, or routing tweaks. | `Phase 1` → `Phase 2` → `Phase 4` → `Phase 5` → `Phase 6` → `Phase 7` |
| **Category E: Trivial / Direct Execution** | Formatting tweaks, renaming variables, adding docstrings, or simple syntax fixes. | `Phase 1 (Direct confirmation)` → `Phase 6` → `Phase 7` |

---

## 2. Mandatory Execution Phases

### Phase 1: Discussion & Classification Mode
*   **Purpose**: Understand constraints, business goals, and current system assumptions.
*   **Allowed**: Querying database schemas, reading existing files, asking clarifying questions.
*   **Not Allowed**: Editing files, creating new classes, or generating code blocks.
*   **Output Checklist**:
    *   [ ] Request Category Identified.
    *   [ ] Primary User Constraints Defined.
    *   [ ] Integration Boundaries Noted.

### Phase 2: Architecture Proposal Mode
*   **Purpose**: Design components cleanly before coding.
*   **Allowed**: Proposing data-flow diagrams, UML mappings, and modular divisions.
*   **Must Answer**:
    *   Why this design over alternative approaches?
    *   Which existing services or database models are being reused?
    *   What is the estimated impact on system latency?
*   **Output**: Unified Architecture Proposal (no code).

### Phase 3: Risk & Security Review Mode
*   **Purpose**: Proactively audit code for vulnerability and latency traps.
*   **Audit Checklist**:
    *   [ ] **Security**: Does this violate multi-tenant isolation, leak PII, or expose API keys?
    *   [ ] **Performance**: Does this introduce N+1 queries or memory growth in streaming loops?
    *   [ ] **Reliability**: How does this handle external API (OpenAI/Twilio) downtime?
*   **Output**: Risk & Mitigation Report.

### Phase 4: Edge Case Matrix Mode
*   **Purpose**: Eliminate boundary bugs before writing tests.
*   **Must Map**:
    *   Happy Path execution parameters.
    *   Unhappy Path handling (e.g. empty databases, invalid parameters, null payloads).
    *   Race conditions or concurrent request collisions.
*   **Output**: Structural Edge Case Matrix.

### Phase 5: Implementation Planning Mode
*   **Purpose**: Step-by-step TODO sequence.
*   **Must List**:
    *   Specific files to modify (with paths).
    *   Required database schema migrations.
    *   Unit and integration test cases required for validation.
    *   Rollback plan if system fails staging deployment.
*   **Output**: Markdown checklist ready for execution tracking.

### Phase 6: Code Generation Mode
*   **Purpose**: Implement the approved plan.
*   **Rules**:
    *   Follow PEP 8, add type hints, and implement structured logging.
    *   Make the smallest viable change. Never refactor unrelated sections.
    *   Keep existing docstrings and comments intact.

### Phase 7: Validation Mode
*   **Purpose**: Double-check the changes.
*   **Requirement**: Run test suites, verify API contracts, and provide a Validation Report summarizing coverage and performance verification.

---

## 3. Dynamic Alert Trigger (Agent Instructions)
1.  **Read Target**: Every time a user initiates a conversation referencing `AI_ENGINEERING_OPERATING_SYSTEM.md`, the AI Agent must immediately parse this file.
2.  **Assert Current Phase**: The Agent must output its current phase classification at the top of its response.
3.  **Halt on Violation**: If the user asks for immediate code modifications on a complex task (Category B or C), the Agent is **commanded to stop**, alert the user that they are bypassing the mandatory architecture/risk review, and output the Phase 1/Phase 2 analysis first.
