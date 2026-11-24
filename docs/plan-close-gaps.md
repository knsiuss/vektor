# Plan: tutup celah fitur (lanjutan)

Status per 2026-11-24. Urutan = urutan pengerjaan, bukan urutan kepentingan.
Setiap fase selesai hanya kalau perintah verifikasinya hijau.

## Kondisi awal

`uv run pytest -q` sebelum perubahan: **35 gagal / 95 lulus**. Penyebabnya bukan
satu bug, tapi refactor multi-tenant yang setengah jalan: migrasi dan test sudah
ada, model/repository belum.

| Akar masalah | Test terdampak |
|---|---|
| `ConversationRepository(principal=...)` belum ada; `Conversation` belum punya `tenant_id`/`owner_id` | 13 |
| `DocumentExtractor(on_usage=...)` belum ada | 2 |
| Scoping dokumen belum diimplementasi | 9 |
| Repo/usage/auth turunan refactor yang sama | 8 |
| 3 unit test hardening | 3 |

## Fase 0 — Selesaikan refactor multi-tenant (SELESAI)

Kenapa dulu: tanpa ini, setiap fitur baru berdiri di atas test yang merah, jadi
"selesai" tidak bisa dibuktikan.

- `Conversation` + `ConversationRepository`: `tenant_id`/`owner_id`, scope
  list/get/delete/usage, admin lintas user dengan audit (`conversation.read`,
  `conversation.list`, `conversation.delete`), `list_tenant_conversations`,
  `get_usage_summary(tenant_wide=True)`.
- `api/routers/conversations.py`, `usage.py`: meneruskan principal.
- `api/auth.py`: akses terbuka hanya selama belum ada API key sama sekali.
- `tools/registry.py`: detail exception tidak lagi sampai ke model.
- `model_gateway/embeddings.py`: request `/embeddings` di-batch.
- `knowledge/extractors.py`: PDF di atas 500 halaman ditolak.
- Endpoint baru: `GET /usage/breakdown`, `GET /usage/timeseries`.
- `api/main.py`: flush metering setelah respons (termasuk streaming).
- `knowledge/repository.hybrid_search`: menerima filter `service`/`environment`/
  `doc_type` (belum dipakai karena dokumen belum punya metadata).

Verifikasi: `uv run pytest -q` → **149 lulus, 0 gagal** (awal: 95/35).

Belum: `alembic_version` DB masih `0004` padahal tabel `0007` sudah ada. Jangan
`alembic upgrade head` sebelum diselaraskan.

## Fase 1 — Scoping dokumen (SELESAI)

- Model: `tenant_id`/`owner_id`/`visibility` di dokumen, `tenant_id` di chunk,
  tabel `document_grants`.
- Repository: filter baca (own / tenant / granted), dedupe per tenant, kelola
  grant, set visibility, cek hak ubah.
- API: `PATCH /documents/{id}/visibility`, `POST|GET /documents/{id}/grants`,
  `DELETE /documents/{id}/grants/{grantee}`, delete lintas pemilik diaudit.

Verifikasi: `uv run pytest tests/integration/test_knowledge_scoping.py` → 9 lulus.

## Fase 2 — Feedback jadi data (SELESAI)

- `POST /api/v1/chat/feedback`: hanya untuk pesan di percakapan yang boleh dibaca
  pemanggil (pesan orang lain → 404), disimpan lewat `record_feedback`.
- `GET /api/v1/usage/feedback?rating=&limit=`: daftar feedback milik pemanggil,
  lengkap dengan judul percakapan dan potongan jawaban.
- `frontend/components/feedback-panel.tsx`: kartu "Answers To Review" di
  Telemetry, hanya menampilkan yang di-downvote beserta komentar dan tanggal.

Verifikasi: `tests/integration/test_feedback.py` (3 lulus), `tsc --noEmit` bersih,
`vitest` 33 lulus.

## Fase 3 — Budget per tenant (SELESAI)

- Tabel `tenant_budgets` (migrasi `0008`) + `BudgetRepository` di
  `modules/usage/budget.py`.
- `GET /api/v1/usage/budget` untuk semua user, `PUT /api/v1/admin/budget`
  khusus admin (member → 403).
- Penegakan di dependency `require_budget` yang dipasang di `POST /chat` dan
  `POST /chat/stream`: 429 dengan pesan jelas saat jatah habis.
- Status: `unlimited` / `ok` / `warning` (≥ warn_ratio, default 0.8) /
  `exhausted`.
- `frontend/components/budget-meter.tsx`: kartu "Monthly Token Budget" di
  Telemetry, menampilkan terpakai/limit, bar, dan sisa token.

Verifikasi: `tests/integration/test_budget.py` (5 lulus), `pytest` 173 lulus,
`tsc` + `vitest` 33 lulus, `ruff`/`mypy` bersih pada file terkait.

## Fase 4 — Tool mutating + preview approval (SELESAI)

Ternyata sesi lain sudah menambahkan tool mutating (`save_skill`,
`run_sandbox_command`). Yang masih hilang adalah bukti "apa yang akan dijalankan":
registry membuang argumen saat tool diblokir.

- `ToolRegistry.execute`: argumen di-parse **sebelum** gerbang risiko, jadi record
  `blocked` membawa `arguments` dan pesan berisi preview JSON (maks 400 char).
- `frontend/components/chat-message.tsx`: banner approval menampilkan nama tool
  dan argumennya sebelum tombol "Approve and run".
- JSON rusak tetap jadi `error`, bukan `blocked`, supaya model tahu harus
  memperbaiki argumen.

Verifikasi: `tests/unit/test_tool_approval_preview.py` (3 lulus), `pytest` 176
lulus, `tsc` + `vitest` 33 lulus.

## Fase 5 — Kesegaran dokumen (SELESAI)

- Kolom `source_url` (nullable) dan `last_synced_at` di `knowledge_documents`
  (migrasi `0009`), diisi saat ingest.
- `is_stale` dihitung dari `retrieval_stale_days` dan ikut di `DocumentSummary`.
- `POST /knowledge/documents/{id}/reindex`: ambil ulang chunk yang tersimpan,
  embedding ulang dengan model aktif, perbarui `last_synced_at`. Butuh hak
  kelola (pembaca tenant-visible → 403, dokumen asing → 404).
- `knowledge-view.tsx`: kolom "Updated", pill "Stale", dan menu "Re-index
  document".

Verifikasi: `tests/integration/test_document_freshness.py` (4 lulus), `pytest`
180 lulus, `tsc` + `vitest` 33 lulus.

Catatan: DB lokal ditambah dua kolom manual (backup
`vektor.db.bak-*-pre-freshness`) karena `create_all` tidak mengubah tabel lama.

## Fase 6 — Sisa kecil (SELESAI)

- `GET /api/v1/usage/tools?days=&limit=` memakai `top_tools()` yang tadinya tidak
  pernah tersambung; kartu "Top Tools" di Telemetry sekarang terisi.
  Verifikasi: `tests/integration/test_tool_usage_report.py` (3 lulus).
- Migrasi saya semula memakai revision `0008`/`0009` yang bertabrakan dengan
  branch `0008_workflow_cron` → `0012_billing_ledger` milik sesi lain. Keduanya
  dinomori ulang jadi `0013_tenant_budgets` dan `0014_document_freshness`,
  dirantai setelah `0012`, sehingga `alembic heads` tunggal.
- DB lokal di-stamp ke `0014_document_freshness` setelah artefak semua revisi
  diperiksa satu per satu. Kedua migrasi saya idempoten (cek tabel/kolom), jadi
  aman kalau nanti dijalankan ulang di environment lain.

## Catatan

- Frontend belum punya halaman untuk visibility/grant; API-nya sudah siap.
- Jangan commit ke `main`; kerjakan di branch `feat/...` saat mulai fase
  berikutnya.
- Banyak perubahan di tree ini berasal dari sesi lain (`ai_runtime`,
  `modules/billing`, `modules/providers`, `streaming.py`). Jangan revert
  berdasarkan asumsi; periksa `git status` dulu.
