MVP Goal
At the end of two days, the demonstration should prove this workflow:

An administrator configures a regulatory circular website.
A Spring Boot batch process scans the configured source.
A new circular is identified and downloaded.
The circular is stored in MinIO.
A Kafka event containing the MinIO reference is published.
A Python consumer processes one document event.
LangChain and LangGraph extract clauses and obligations.
Regulatory chunks are indexed in PostgreSQL with pgvector.
Citation and relationship data are stored in Neo4j.
Each obligation is compared with a mock policy handbook and control register.
The system identifies covered, partially covered, missing, or unverified obligations.
For a gap, AI drafts a policy update or action recommendation.
The action is assigned to an existing organizational role.
A reviewer can accept, edit, or reject the finding.
An employee chatbot answers questions only from approved policies.
A lightweight sensitive-field scanner checks a sample database schema or ER representation.
Strict Scope Boundaries
Included
Configurable regulator-source records
Manual and scheduled source scanning
New-document detection
PDF download
MinIO storage
Kafka event publication and consumption
One-document-at-a-time Python processing
PDF text extraction
Clause-aware chunking
Obligation extraction
pgvector indexing
Neo4j citation and relationship storage
Mock policy handbook
Mock control register
Mock role directory
Basic gap analysis
Draft policy or remediation action
Accept, edit, or reject workflow
Basic employee policy chatbot
Basic schema-level sensitive-field scanning
Docker Compose environment
Excluded
Production-grade crawling for every regulator
Complex OCR for badly scanned PDFs
Complete legal interpretation
Production database scanning
Automated production changes
Enterprise SSO
Advanced notification and escalation
Full document-version comparison
Fine-grained security
High availability
Comprehensive regulatory applicability logic
Complete audit and model governance
Production-quality frontend design
Simplified Architecture
Component	Technology	Responsibility
Admin and batch backend	Spring Boot	Source configuration, source scanning, metadata, review APIs
Scheduler	Spring Scheduler	Periodically starts source scans
Object storage	MinIO	Original circulars, policies, and generated drafts
Event broker	Kafka in KRaft mode	Document-processing events
Transaction database	PostgreSQL with pgvector	Metadata, vectors, obligations, findings, actions, reviews
Graph database	Neo4j	Clause, obligation, policy, control, role, and citation relationships
AI ingestion worker	Python	Kafka consumption, parsing, indexing, and AI processing
AI orchestration	LangChain and LangGraph	Obligation extraction, mapping, gap analysis, and recommendations
Frontend	React or existing UI framework	Admin, findings, review, chatbot, and scan results
LLM	Approved hosted or local model	Structured extraction and generation
For the two-day MVP, use a PostgreSQL image that already includes pgvector rather than running a separate vector database.

Docker Compose Services
The Docker Compose environment should contain:

text

postgres-pgvector
minio
kafka
kafka-ui
neo4j
spring-backend
python-ai-worker
frontend
Optional services such as schema registry, Redis, monitoring, and distributed tracing should be postponed.

Suggested Ports
Service	Port
Spring Boot API	8080
Python worker health API	8000
Frontend	3000
PostgreSQL	5432
MinIO API	9000
MinIO console	9001
Kafka	9092
Kafka UI	8081
Neo4j browser	7474
Neo4j Bolt	7687
Repository Structure
A monorepo will be fastest for the MVP:

text

clauseiq/
  docker-compose.yml
  .env.example
  README.md
  backend/
    src/
    Dockerfile
  ai-worker/
    app/
      consumer/
      parsing/
      graphs/
      retrieval/
      models/
      scanners/
    Dockerfile
    requirements.txt
  frontend/
    src/
    Dockerfile
  sample-data/
    circulars/
    policies/
    controls/
    schemas/
  database/
    migrations/
    seed/
  scripts/
    bootstrap-minio.sh
    demo-reset.sh
Phase 1: Regulatory Source Monitoring
Source Configuration
Website information should be stored in PostgreSQL so an administrator can add or disable sources without changing code.

Suggested regulatory_source fields:

Field	Purpose
id	Source identifier
name	Display name
regulator	RBI, SEBI, IRDAI, or another authority
listing_url	Page containing circular listings
base_url	Base website URL
document_link_selector	Selector for circular links
title_selector	Optional selector for titles
date_selector	Optional selector for publication dates
circular_number_selector	Optional selector for circular numbers
schedule_expression	Scan schedule
enabled	Enables or disables monitoring
last_scan_at	Last attempted scan
last_success_at	Last successful scan
created_at	Creation timestamp
updated_at	Last update timestamp
A simple JSON configuration field can hold source-specific parsing information:

json

{
  "documentLinkSelector": "a[href$='.pdf']",
  "titleSelector": ".circular-title",
  "dateSelector": ".publication-date",
  "dateFormat": "dd-MM-yyyy",
  "maximumPages": 2
}
For the demo, support one known page structure and one generic PDF-link selector.

Admin APIs
Implement the following minimum endpoints:

text

POST   /api/admin/sources
GET    /api/admin/sources
GET    /api/admin/sources/{id}
PUT    /api/admin/sources/{id}
POST   /api/admin/sources/{id}/scan
PATCH  /api/admin/sources/{id}/status
GET    /api/admin/scan-runs
GET    /api/admin/documents
The manual scan endpoint is essential for the demonstration. Do not wait for the daily scheduler during the demo.

Source Scanner Logic
For each enabled source:

Fetch the configured listing URL.
Parse circular links and available metadata.
Resolve relative URLs.
Normalize the URL.
Compare against existing document records.
Download new or changed PDFs.
Calculate a SHA-256 checksum.
Check URL and checksum duplication.
Upload the PDF to MinIO.
Insert document metadata into PostgreSQL.
Publish a Kafka event.
Record the scan result.
New-Document Detection
Use both URL and checksum.

A URL check identifies previously discovered links. A checksum check protects against:

The same PDF appearing under multiple URLs
The source replacing a PDF at the same URL
Duplicate publication across multiple listing pages
For the MVP:

New URL and new checksum: create a new document.
Existing URL and changed checksum: create a new version.
Existing checksum: skip processing.
MinIO Object Convention
text

regulatory-originals/
  {regulator}/
    {document-id}/
      {version-number}/
        original.pdf
Example:

text

regulatory-originals/RBI/4d91a2/version-1/original.pdf
Kafka Event
Kafka should contain the processing instruction, not the PDF.

Topic:

text

regulatory.document.ingested
Event:

json

{
  "eventId": "evt-1001",
  "eventType": "REGULATORY_DOCUMENT_INGESTED",
  "documentId": "doc-1001",
  "documentVersionId": "doc-version-1",
  "regulator": "RBI",
  "title": "Sample Regulatory Circular",
  "sourceUrl": "official-circular-url",
  "minioBucket": "regulatory-originals",
  "minioObjectKey": "RBI/doc-1001/version-1/original.pdf",
  "checksum": "sha256-value",
  "createdAt": "event-timestamp"
}
Phase 2: Python AI Ingestion
Kafka Consumer
The Python service should:

Consume one Kafka event.
Check whether the event was already processed.
Mark the event as processing.
Download the PDF from MinIO.
Extract text with page boundaries.
Generate chunks and citations.
Run the LangGraph workflow.
Save structured results.
Mark processing as completed.
Commit the Kafka offset.
If processing fails:

Record the error.
Do not produce partial approved findings.
Allow one or two retries.
Move the event to a dead-letter topic after the retry limit.
PDF Parsing
For the two-day MVP, use native PDF extraction with a library such as PyMuPDF or pypdf.

Each chunk must preserve:

Document ID
Page number
Clause or section number where detected
Heading
Exact source text
Start and end character offsets
OCR should be a stretch goal. Use digitally generated PDFs for the demonstration.

LangGraph Workflow
Keep the graph small and deterministic.

Workflow Nodes
load_document
parse_pages
detect_clauses
extract_obligations
validate_citations
index_regulatory_content
retrieve_internal_evidence
map_policies_and_controls
check_role_coverage
assess_gap
draft_recommendation
persist_results
await_human_review
Structured Obligation Output
Require the model to return structured JSON:

json

{
  "documentId": "doc-1001",
  "obligations": [
    {
      "obligationId": "obl-1001",
      "summary": "Maintain audit logs for regulated systems",
      "requiredAction": "Maintain and review audit logs",
      "responsibleEntity": "Regulated entity",
      "deadline": null,
      "applicability": "Systems processing regulated information",
      "citation": {
        "pageNumber": 5,
        "clauseNumber": "4.2",
        "quotedText": "Exact text copied from the circular"
      },
      "confidence": 0.9
    }
  ]
}
Citation Validation
Before accepting an extracted obligation:

Confirm the page exists.
Confirm the quote occurs on that page.
Confirm the document ID and version match.
Reject an obligation without a source quote.
Mark uncertain clause numbers as unavailable rather than inventing them.
pgvector Design
Use pgvector for regulatory and internal-document retrieval.

Suggested table:

text

document_chunk
Minimum columns:

Column	Purpose
id	Chunk identifier
document_id	Parent document
document_type	Circular, policy, control, SRS, or SRE
page_number	Source page
section_number	Internal or regulatory section
clause_number	Clause reference
content	Chunk text
embedding	Vector representation
metadata	Additional JSON metadata
approval_status	Draft or approved
created_at	Creation timestamp
Employee chatbot retrieval must filter for:

text

document_type = POLICY
approval_status = APPROVED
This prevents unapproved AI drafts from being presented as official policy.

Neo4j Design
Use Neo4j for traceability rather than as the primary storage location for full documents.

Minimum Nodes
text

RegulatoryDocument
Clause
Obligation
Policy
PolicySection
Control
Role
Finding
Recommendation
Minimum Relationships
text

RegulatoryDocument CONTAINS Clause
Clause CREATES Obligation
Obligation MAPS_TO PolicySection
Obligation SATISFIED_BY Control
Control OWNED_BY Role
Obligation HAS_GAP Finding
Finding RESOLVED_BY Recommendation
Recommendation ASSIGNED_TO Role
Store the authoritative workflow status and review decisions in PostgreSQL. Neo4j should hold searchable relationships.

Internal Policy and Control Ingestion
To save time, load internal information before the demo through seed scripts.

Mock Policy Handbook
Create a short handbook containing five to ten sections, for example:

Personal-data collection
Consent management
Data retention
Access control
Audit logging
Incident response
Third-party data sharing
Data deletion
Mock Control Register
Use CSV or database seed data:

Control ID	Control name	Description	Owner role	Frequency
CTRL-001	Access review	Review privileged access	IAM Manager	Quarterly
CTRL-002	Retention review	Review expired records	Data Governance Lead	Monthly
CTRL-003	Log review	Review security logs	SOC Manager	Daily
Role Directory
Create a small authoritative role list:

Compliance Officer
Data Protection Officer
Policy Owner
Data Governance Lead
IAM Manager
SOC Manager
Application Owner
Database Administrator
Legal Reviewer
The AI must select from these roles. It must not invent a role or employee.

Obligation Mapping
For every obligation:

Generate an embedding.
Retrieve the top policy chunks.
Retrieve the top controls.
Filter by policy domain where possible.
Ask the model to assess coverage.
Record the matching internal citations.
Check whether the mapped policy or control has an owner role.
Assign a coverage status.
Coverage Status
Use only these statuses:

COVERED
PARTIALLY_COVERED
NOT_COVERED
CONFLICTING
UNVERIFIED
Gap Rules
Condition	Finding
No relevant policy found	Policy gap
Policy found but incomplete	Partial policy gap
Policy exists but no control found	Control-design gap
Control exists but has no role	Ownership gap
Role exists but no evidence was assessed	Implementation unverified
Policy and regulation conflict	Policy conflict
SRS or SRE lacks the necessary capability	System-requirement or operational gap
The system must avoid claiming that production is compliant merely because a matching policy exists.

Draft Policy and Action Generation
For a missing or partial obligation, generate:

Gap title
Gap description
Regulatory citation
Existing policy citation, if available
Suggested severity
Proposed policy wording
Recommended action
Responsible role
Suggested deadline
Required evidence
Confidence score
Example:

json

{
  "findingType": "POLICY_GAP",
  "coverageStatus": "PARTIALLY_COVERED",
  "severity": "HIGH",
  "explanation": "The policy requires log collection but does not specify periodic review.",
  "draftPolicyText": "Audit logs for regulated systems must be reviewed at the defined frequency.",
  "recommendedAction": "Update the audit logging policy and define a recurring review control.",
  "assignedRole": "SOC Manager",
  "requiredEvidence": [
    "Approved policy version",
    "Log review procedure",
    "Sample completed review"
  ],
  "confidence": 0.84
}
Human Review Workflow
The reviewer must be able to:

Accept
Accept with edits
Reject
Suggested statuses:

text

PENDING_REVIEW
APPROVED
APPROVED_WITH_CHANGES
REJECTED
Record:

Original AI output
Edited value
Decision
Reviewer
Comment
Decision timestamp
Minimum Review APIs
text

GET   /api/findings
GET   /api/findings/{id}
POST  /api/findings/{id}/approve
POST  /api/findings/{id}/edit-and-approve
POST  /api/findings/{id}/reject
Minimum Frontend Screens
Only five screens are needed:

Source administration
Regulatory documents
Obligations and findings
Finding review
Employee chatbot and schema scan
Employee Policy Chatbot
The chatbot must retrieve information only from approved policy chunks.

Chatbot Flow
Receive an employee question.
Classify the policy domain.
Search approved policy chunks in pgvector.
Apply a retrieval-score threshold.
Generate an answer only from retrieved content.
Display policy citations.
Refuse to guess when evidence is insufficient.
Example question:

Can customer personal data be stored in this development tool?

Expected response structure:

Approved policy answer
Conditions or restrictions
Relevant policy section
Warning when system-specific approval is required
If no approved policy supports the answer:

“The approved policy repository does not contain enough information to answer this question. Please contact the Compliance Officer or Data Protection Officer.”

Draft policies and unapproved findings must not be used by the chatbot.

SRS, SRE, ER, and Sensitive-Field Scan
This feature must be heavily simplified for the two-day demo.

Supported Inputs
Choose one or two of these:

SRS or SRE PDF upload
ER model represented as JSON
SQL DDL file
Read-only connection to a local sample PostgreSQL database
The safest and fastest demo is a SQL DDL or schema JSON upload.

Detection Logic
Use deterministic field-name rules first:

name
email
phone
mobile
address
date_of_birth
dob
aadhaar
pan
passport
account_number
card_number
ip_address
location
biometric
Then use AI classification only for ambiguous names.

Scanner Output
json

{
  "table": "customers",
  "column": "aadhaar_number",
  "classification": "GOVERNMENT_IDENTIFIER",
  "sensitivity": "HIGH",
  "reason": "The field appears to contain an Aadhaar identifier.",
  "confidence": 0.98,
  "recommendedControl": "Mask the field and restrict access by role."
}
The scanner should inspect only schema metadata in the MVP. It should not read production data values.

SRS and SRE Comparison
If an SRS or SRE document is supplied:

Extract and index it as an internal document.
Retrieve relevant sections for each obligation.
Determine whether a required capability is documented.
Mark missing capabilities as potential gaps.
Use UNVERIFIED when technical implementation has not been examined.
Minimum PostgreSQL Tables
To complete the MVP quickly, use the following reduced schema:

text

regulatory_source
source_scan_run
regulatory_document
regulatory_document_version
processed_event
document_chunk
obligation
citation
internal_document
control
organizational_role
obligation_mapping
finding
recommendation
review_decision
chat_session
chat_message
sensitive_field_finding
Avoid creating a highly normalized enterprise schema during the two-day build.

Two-Day Execution Schedule
Day 1: Ingestion and Structured Extraction
Hours 0–2: Bootstrap
DevOps and integration developer

Create monorepo.
Write Docker Compose configuration.
Start PostgreSQL with pgvector.
Start Kafka in KRaft mode.
Start MinIO.
Start Neo4j.
Add health checks.
Create .env.example.
Add sample data.
Completion criterion: All infrastructure services start with one command.

bash

docker compose up --build
Hours 0–4: Database and Spring Boot Foundation
Spring Boot developer

Create entities and migrations.
Implement regulatory-source CRUD.
Implement source scan-run records.
Implement document metadata records.
Add manual scan API.
Configure MinIO and Kafka clients.
Completion criterion: An administrator can add and retrieve a regulatory source.

Hours 2–7: Website Scanner
Spring Boot developer

Fetch one configured source page.
Parse PDF links.
Resolve relative URLs.
Detect new links.
Download the PDF.
Calculate checksum.
Store it in MinIO.
Save document metadata.
Publish Kafka event.
Add scheduled daily scan.
Completion criterion: A manual scan produces a document record, MinIO object, and Kafka event.

Hours 0–5: Python Worker Foundation
Python and AI developer

Create Kafka consumer.
Create MinIO client.
Retrieve one PDF.
Extract page-aware text.
Create citation-aware chunks.
Add event idempotency.
Add worker health endpoint.
Completion criterion: The worker consumes one event and extracts page-level text.

Hours 5–10: LangGraph Extraction
Python and AI developer

Define structured output schemas.
Implement obligation extraction.
Implement citation validation.
Persist obligations and citations.
Index chunks in pgvector.
Create initial Neo4j relationships.
Completion criterion: One circular produces at least two cited obligations.

Hours 4–10: Frontend Foundation
Frontend developer

Create source-administration screen.
Create documents screen.
Add a “Scan now” button.
Show document-processing status.
Create basic obligations list.
Completion criterion: Users can trigger and observe the ingestion workflow.

End-of-Day-1 Checkpoint
The following flow must work:

text

Add source
-> Scan source
-> Detect circular
-> Download PDF
-> Store in MinIO
-> Publish Kafka event
-> Consume event
-> Extract obligations
-> Save citations
-> Display obligations
If this does not work by the end of Day 1, postpone the chatbot and sensitive-field scanner.

Day 2: Mapping, Gaps, Review, and Optional Features
Hours 0–3: Internal Knowledge Setup
AI developer and domain contributor

Load mock policy handbook.
Load control register.
Load organizational roles.
Chunk internal documents.
Create embeddings.
Insert policy and control relationships into Neo4j.
Completion criterion: Internal policy and control content is searchable.

Hours 2–7: Mapping and Gap Analysis
Python and AI developer

Retrieve matching policies and controls for each obligation.
Check role ownership.
Assign coverage status.
Generate finding.
Draft policy update.
Generate action recommendation.
Assign an existing role.
Persist results in PostgreSQL and Neo4j.
Completion criterion: At least one obligation is covered and at least one produces a gap.

Hours 0–6: Review Backend
Spring Boot developer

Implement findings APIs.
Implement accept, edit, and reject.
Save review decisions.
Record a basic audit history.
Add role and control lookup endpoints.
Completion criterion: A finding can be approved, edited, or rejected.

Hours 3–8: Review Frontend
Frontend developer

Display regulatory citation.
Display matching policy and control.
Display coverage result.
Display severity and confidence.
Display draft policy.
Display assigned role.
Add accept, edit, and reject controls.
Completion criterion: A compliance reviewer can complete a finding review.

Hours 6–9: Employee Chatbot
AI and frontend developers

Add approved-policy-only retrieval.
Implement chatbot endpoint.
Return policy citations.
Add insufficient-information fallback.
Add a simple chat screen.
Completion criterion: One employee question is answered using an approved policy citation.

Hours 7–10: Sensitive-Field Scanner
AI or backend developer

Accept SQL DDL, schema JSON, or sample database metadata.
Apply deterministic sensitive-field rules.
Add optional AI classification for ambiguous fields.
Store and display scan findings.
Completion criterion: The scanner flags at least three sensitive columns in the sample schema.

Hours 10–12: Integration and Demo Hardening
Entire team:

Run the complete workflow.
Fix inconsistent identifiers.
Verify Kafka retry behavior.
Verify duplicate detection.
Validate citations.
Seed stable demo records.
Add loading and error states.
Prepare a reset script.
Write demonstration instructions.
Record known limitations.
Priority Order
If time becomes constrained, implement in this order:

Source administration
Website scanner
MinIO storage
Kafka event
PDF processing
Obligation extraction with citation
Policy and control retrieval
Gap finding
Role assignment
Review workflow
Employee chatbot
Sensitive-field scanner
SRS or SRE comparison
The chatbot and sensitive-field scanner should never delay the main clause-to-gap workflow.

Parallel Team Work Allocation
Workstream	Owner	Primary output
Infrastructure	DevOps developer	Docker Compose environment
Batch ingestion	Spring Boot developer	Source scan, MinIO, and Kafka
AI processing	Python developer	LangGraph extraction and assessment
User interface	Frontend developer	Admin and review screens
Domain data	Compliance contributor	Policies, controls, roles, expected results
Demo Data Preparation
Use deterministic sample data rather than depending entirely on a live regulator website during the final presentation.

Prepare:

One live or official source configuration
One local fallback circular listing
Three sample circular PDFs
One eight-to-ten-page policy handbook
Five to ten controls
Eight organizational roles
One SRS or SRE sample
One SQL schema containing sensitive fields
Three expected obligations
One covered obligation
One policy gap
One ownership or evidence gap
The live scan can be demonstrated first. If the external website is unavailable, switch to the local fallback source.

Demo Script
Open source administration.
Add or display a configured regulator source.
Click Scan now.
Show the newly discovered circular.
Open MinIO and show the stored PDF.
Open Kafka UI and show the event.
Wait for the Python worker to process the document.
Open the obligations page.
Show the extracted obligation and exact citation.
Show the matching internal policy and control.
Show a missing or partial coverage finding.
Show the generated policy draft and action.
Show the assigned role.
Edit and approve the finding.
Ask the employee chatbot a policy question.
Upload a sample schema.
Show identified sensitive fields.
Two-Day Acceptance Criteria
The MVP is successful if:

An administrator can add a circular website.
A manual or scheduled scan can inspect it.
A new PDF can be identified.
The PDF is stored in MinIO.
Duplicate PDFs are not processed twice.
A Kafka event is published.
The Python service consumes one event.
The circular is parsed with page references.
At least one atomic obligation is extracted.
Every obligation contains an exact source quote.
Regulatory content is indexed in pgvector.
Citation relationships are stored in Neo4j.
Obligations are compared with a policy handbook.
Obligations are compared with a control register.
Existing owner roles are checked.
At least one gap produces a draft policy or remediation.
An existing role is assigned.
A reviewer can accept, edit, or reject the result.
Approved policies can answer an employee question.
A sample schema scan identifies sensitive fields.
The entire environment starts through Docker Compose.
Required Shortcuts
To stay within two days:

Support one regulator-page layout.
Use digital PDFs and postpone OCR.
Seed policies, controls, and roles.
Use one organization and no multi-tenancy.
Use simple username-based demo authentication.
Use one Kafka consumer.
Use one LangGraph workflow.
Use PostgreSQL for all authoritative workflow data.
Use Neo4j only for relationships.
Use deterministic severity rules.
Restrict the chatbot to approved policies.
Scan schema metadata rather than production data.
Use one model and one embedding provider.
Process documents sequentially.
Key Technical Safeguards
Even for the MVP:

Do not send full PDFs through Kafka.
Do not let document text act as agent instructions.
Do not accept an obligation without a validated citation.
Do not let AI invent organizational roles.
Do not present draft policies as approved policies.
Do not claim production compliance from policy matching.
Do not allow the chatbot to use unapproved content.
Do not allow the sensitive-field scanner to modify a database.
Record original AI output before human editing.
Use read-only credentials for any sample database connection.
Expected End State
At the end of the second day, ClauseIQ should provide a credible vertical slice:

Configured website → detected circular → MinIO document → Kafka event → LangGraph processing → cited obligations → pgvector retrieval → Neo4j traceability → policy and control comparison → gap → draft remediation → role assignment → human review

The employee chatbot and sensitive-field scanner should be presented as lightweight extensions built on the same approved knowledge base, not as fully production-ready modules.