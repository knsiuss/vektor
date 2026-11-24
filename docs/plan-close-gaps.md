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

## Fase 0 — Selesaikan refactor multi-tenant (prasyarat)

Kenapa dulu: tanpa ini, setiap fitur baru berdiri di atas test yang merah, jadi
"selesai" tidak bisa dibuktikan.

- `src/modules/conversations/models.py`: tambah `tenant_id`, `owner_id` (kolom
  sudah ada di DB lewat migrasi `0002`).
- `src/modules/conversations/repository.py`: terima `principal`; scope
  create/list/get/delete/usage ke tenant + owner; admin boleh lintas user dengan
  audit (`conversation.read`, `conversation.list`, `conversation.delete`);
  sediakan `list_tenant_conversations` dan `get_usage_summary(tenant_wide=True)`
  yang sudah dipanggil `api/routers/admin.py`.
- `src/api/routers/chat.py`, `conversations.py`, `admin.py`: teruskan principal.
- `src/api/auth.py`: permintaan tanpa API key di environment non-development
  harus 401.
- `src/modules/tools/registry.py`: jangan bocorkan detail exception ke model.
- `src/modules/model_gateway/embeddings.py`: kirim batch sesuai batas provider.
- `src/modules/knowledge/extractors.py`: tolak PDF melebihi batas halaman.
- Rapikan `alembic_version` (DB di `0004`, tabel `0007` sudah ada).

Verifikasi: `tests/integration/test_multi_tenant.py`, `test_usage_events.py`,
`test_timeseries_me.py`, `test_stream_and_hardening.py`,
`tests/unit/test_security_hardening.py`.

## Fase 1 — Scoping dokumen (SELESAI)

- Model: `tenant_id`/`owner_id`/`visibility` di dokumen, `tenant_id` di chunk,
  tabel `document_grants`.
- Repository: filter baca (own / tenant / granted), dedupe per tenant, kelola
  grant, set visibility, cek hak ubah.
- API: `PATCH /documents/{id}/visibility`, `POST|GET /documents/{id}/grants`,
  `DELETE /documents/{id}/grants/{grantee}`, delete lintas pemilik diaudit.

Verifikasi: `uv run pytest tests/integration/test_knowledge_scoping.py` → 9 lulus.

## Fase 2 — Feedback jadi data

Sekarang tombol jempol memanggil `chat/feedback` yang tidak ada (404 ditelan).

- `src/api/routers/chat.py`: `POST /feedback` → `UsageEventRepository.record_feedback`.
- `frontend/components/telemetry-view.tsx`: panel "Jawaban bermasalah" berisi
  jawaban yang di-downvote, sitasi, dan chunk yang dipakai.

Verifikasi: test integration baru untuk feedback + tenant scoping-nya.

## Fase 3 — Budget per tenant

- Tabel `tenant_budgets` (limit bulanan, ambang peringatan) + migrasi.
- Cek sebelum panggilan model di `usage/recorder.py`; 80% → status warning,
  100% → tolak dengan pesan jelas (bukan 500).
- `frontend/components/telemetry-view.tsx`: meter budget + sisa hari.

Verifikasi: test yang memaksa limit tercapai dan memastikan request ditolak
dengan 429.

## Fase 4 — Satu tool yang benar-benar mengubah

Gerbang approval ada, objeknya belum ada.

- `src/modules/tools/builtins.py`: tambah satu tool mutating (mis.
  `restart_service`) yang default diblokir.
- `frontend/components/chat-message.tsx`: kartu "ini yang akan dijalankan"
  sebelum Approve, dan jejak audit setelah dieksekusi.

Verifikasi: test tool loop yang memastikan penolakan tetap terjadi tanpa
`allow_mutating_tools`.

## Fase 5 — Kesegaran dokumen

- Kolom `last_synced_at` + `source_url` di dokumen, tombol Re-index.
- Tanda "dokumen ini N hari belum diperbarui" di panel evidence.

Verifikasi: test yang memastikan re-index memperbarui timestamp dan chunk.

## Catatan

- Frontend belum punya halaman untuk visibility/grant; API-nya sudah siap.
- Jangan commit ke `main`; kerjakan di branch `feat/...` saat mulai fase
  berikutnya.
