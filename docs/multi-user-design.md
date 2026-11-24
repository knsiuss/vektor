# Vektor: Rancangan Multi-User, Tenant, dan Izin

Status: Fase 0-4 diimplementasikan (belum diverifikasi dengan pytest). Fase 5 belum.

## 1. Masalah
Saat ini percakapan, dokumen knowledge, dan usage bersifat global. Siapa pun dengan API key
dapat membaca atau menghapus data siapa pun. Ini bertentangan dengan prinsip di scope.md:
"akses mengikuti izin user".

## 2. Model identitas
Principal (hasil autentikasi, tersedia di `request.state.principal`):

    Principal(user_id: str, tenant_id: str, roles: frozenset[str], scopes: frozenset[str])

- **Tenant** = batas isolasi keras (perusahaan/organisasi). Data tidak pernah lintas tenant.
- **User** = pemilik percakapan dan dokumen pribadi.
- **Role**: `member`, `admin` (admin tenant), `service` (integrasi mesin).

### Autentikasi (bertahap)
1. **Fase 1: API key per user.** Tabel `api_keys(id, tenant_id, user_id, key_hash, roles, revoked_at, expires_at)`.
   Simpan hanya SHA-256 hash. Menggantikan `VEKTOR_API_KEYS` global. Key lama tetap
   didukung sebagai principal `service` di tenant default selama masa migrasi.
2. **Fase 2: OIDC/JWT** (Okta, Entra, Google). Validasi `iss`, `aud`, `exp`; ambil `sub` ->
   user_id, claim tenant -> tenant_id, group -> roles.

Rate limit memakai `user_id`, bukan hash key.

## 3. Perubahan skema

| Tabel | Kolom baru | Catatan |
|---|---|---|
| conversations | `tenant_id`, `owner_id` (index gabungan `tenant_id, owner_id, updated_at`) | NOT NULL setelah backfill |
| conversation_messages | (turun dari conversations) | tidak perlu kolom sendiri |
| knowledge_documents | `tenant_id`, `owner_id`, `visibility` (`private` / `tenant` / `shared`) | index `tenant_id, visibility` |
| knowledge_chunks | `tenant_id` (denormalisasi dari dokumen) | agar filter vector search tanpa join |
| document_grants | `document_id`, `grantee_type` (`user`/`role`), `grantee_id`, `permission` (`read`) | untuk visibility `shared` |
| usage_events (baru) | `tenant_id`, `user_id`, `kind` (chat/embed/vision/rewrite), `model`, token | juga menyelesaikan temuan #8 |

`content_hash` unique berubah menjadi unique pada `(tenant_id, content_hash)`.

## 4. Aturan izin

| Resource | Baca | Tulis/Hapus |
|---|---|---|
| Percakapan | pemilik | pemilik (admin tenant: hapus saja, atas kebijakan) |
| Dokumen `private` | pemilik | pemilik |
| Dokumen `tenant` | semua user tenant | pemilik atau admin |
| Dokumen `shared` | pemilik + grantee | pemilik atau admin |
| Usage (milik sendiri) | user | - |
| Usage (seluruh tenant) | admin | - |

Prinsip: **default tolak**. Resource lintas tenant dibalas **404**, bukan 403, agar
keberadaannya tidak bocor.

## 5. Penegakan di kode (inti rancangan)

**Jangan mengandalkan setiap endpoint mengingat untuk memfilter.** Paksa lewat lapisan repository:

1. Dependency `get_principal` membaca hasil middleware auth.
2. Repository dibuat dengan konteks: `ConversationRepository(session, principal)`,
   `KnowledgeRepository(session, embeddings, principal)`.
3. Semua query lewat helper terpusat, misalnya `_scoped(stmt)`, yang menambahkan
   `WHERE tenant_id = :t AND owner_id = :u` (atau klausa visibility untuk dokumen).
   Tidak ada method repository yang menerima id tanpa scope.
4. `hybrid_search` memfilter **sebelum** scoring: `tenant_id` + (`owner_id = user` OR
   `visibility = 'tenant'` OR ada grant). Ini juga mencegah chunk dokumen orang lain
   masuk ke prompt RAG.
5. Tool registry menerima `principal`; tool `search_knowledge_base` dan
   `get_token_usage_report` otomatis ter-scope. Tool bermutasi di masa depan
   memeriksa `scopes` sebelum dijalankan.
6. Streaming: session factory di endpoint stream harus membawa principal yang sama.

**Pertahanan berlapis (Postgres):** aktifkan Row-Level Security pada tabel utama dengan
`SET LOCAL app.tenant_id = ...` per transaksi. Jadi bug query di aplikasi tetap tidak bisa
menembus batas tenant. SQLite (dev) tidak punya RLS; di sana hanya lapisan aplikasi.

## 6. Perubahan API
- Respons tidak berubah bentuk; hanya hasilnya ter-scope.
- Dokumen baru: field opsional `visibility` (default `private`).
- Endpoint baru: `POST /api/v1/knowledge/documents/{id}/grants`, `DELETE .../grants/{grant_id}`.
- Endpoint admin: `GET /api/v1/admin/usage` (per user dalam tenant).
- Header `X-Request-ID` tetap; log akses menambahkan `tenant_id` dan `user_id`.

## 7. Migrasi data
1. Tambah kolom sebagai NULLABLE.
2. Buat tenant `default` dan user `legacy`; backfill semua baris yang ada.
3. Jadikan NOT NULL, tambah index.
4. Mulai pakai Alembic sebelum langkah ini (saat ini masih `create_all`).

Dokumen lama di-set `visibility = 'tenant'` agar tidak tiba-tiba hilang dari pencarian.

## 8. Rencana implementasi

| Fase | Isi | Perkiraan |
|---|---|---|
| 0 | Alembic + backfill tenant/user default | 0,5 hari |
| 1 | Principal, tabel `api_keys`, auth middleware, rate limit per user | 1-2 hari |
| 2 | Scoping repository conversations + usage; test isolasi | 1 hari |
| 3 | Scoping knowledge (visibility, grants, filter search); tool registry | 1-2 hari |
| 4 | RLS Postgres, endpoint admin, audit log | 1-2 hari |
| 5 | OIDC/JWT | 1-2 hari |

## 9. Test wajib
- User A tidak bisa GET/DELETE percakapan user B (404).
- Tenant X tidak bisa melihat dokumen tenant Y, termasuk lewat `/knowledge/search` dan
  lewat tool `search_knowledge_base` di chat.
- Dokumen `private` tidak muncul di sitasi RAG user lain.
- Hapus grant langsung mencabut akses.
- `/chat/stream` dan `/chat` menerapkan scope yang sama.
- Key yang di-revoke atau kedaluwarsa menghasilkan 401.

## 10. Pertanyaan terbuka (perlu keputusan kamu)
1. Apakah tenant tunggal dulu (satu perusahaan) atau memang multi-tenant sejak awal?
2. Apakah admin boleh membaca isi percakapan user lain? (privasi vs kebutuhan audit)
3. IdP apa yang dipakai kustomer pertama (menentukan Fase 5)?
4. Apakah dokumen perlu level izin per folder/departemen, bukan hanya per user/role?

## 11. Keputusan dan status implementasi (Fase 0-2)

Keputusan: **multi-tenant sejak awal**; **admin tenant boleh membaca percakapan user lain, dengan audit log**.

Sudah dikerjakan:
- Principal (user, tenant, roles); API key per user (hash SHA-256), kedaluwarsa dan pencabutan;
  CLI `python -m api.cli create-key | list-keys | revoke-key`.
- `VEKTOR_API_KEYS` lama tetap berlaku sebagai key bersama: dipetakan ke member tenant `default`.
- `tenant_id` dan `owner_id` di `conversations`; semua query repository di-scope.
  Lintas tenant dan milik orang lain dibalas 404.
- Admin tenant: baca/hapus percakapan user lain (tercatat `conversation.read` / `conversation.delete`),
  `GET /api/v1/admin/conversations`, `/admin/usage`, `/admin/audit-log`.
- `/api/v1/usage` hanya menghitung data pemanggil.
- Alembic: `0001_baseline`, `0002_multi_tenant` (data lama diberi tenant `default`, owner `legacy`).

## 12. Fase 3: scoping knowledge (diimplementasikan)

- `knowledge_documents`: `tenant_id`, `owner_id`, `visibility` (`private` | `tenant` | `shared`);
  `knowledge_chunks.tenant_id` (denormalisasi); tabel `document_grants` (grantee per user).
- **Baca:** dokumen terbaca bila satu tenant DAN (pemilik, atau `tenant`, atau `shared` + ada grant).
  Filter dijalankan di SQL **sebelum** scoring, jadi chunk yang tidak boleh dibaca tidak pernah masuk
  hasil API, sitasi RAG, maupun prompt. Berlaku juga untuk tool `search_knowledge_base`.
- **Kelola (hapus, ubah visibility, grant):** pemilik atau admin tenant. Admin yang bertindak atas
  dokumen orang lain tercatat di audit log (`knowledge.delete|visibility|grant|revoke`).
  Admin **tidak** otomatis boleh membaca dokumen private/shared milik orang lain.
- Dokumen yang terbaca tetapi bukan milik pemanggil memberi **403** saat dikelola; dokumen yang
  tidak terlihat memberi **404**.
- Menambah grant pada dokumen `private` otomatis mengubahnya menjadi `shared`.
- Dedupe `content_hash` kini unik per tenant. Pencarian hanya membandingkan chunk dengan
  `embedding_model` yang sedang aktif (menutup temuan #6).
- Endpoint baru: `PATCH /knowledge/documents/{id}/visibility`, `GET|POST /documents/{id}/grants`,
  `DELETE /documents/{id}/grants/{grantee_id}`.
- Migrasi `0003_knowledge_scoping`: dokumen lama menjadi tenant `default`, owner `legacy`,
  visibility `tenant` (tetap bisa dicari semua user tenant default).

## 13. Fase 4: usage_events (diimplementasikan)

- Tabel `usage_events` (tenant, user, kind, provider, model, token). Jenis panggilan:
  `chat`, `rewrite` (penulisan ulang query RAG), `embedding`, `vision` (ekstraksi gambar).
- `MeteredProvider` membungkus provider LLM; adapter embedding dan vision melaporkan lewat
  callback `on_usage`. Pencatatan tidak mengubah perilaku panggilan.
- `UsageRecorder` menampung event di memori selama request, lalu menyimpannya **setelah**
  transaksi request selesai (juga saat request gagal, karena panggilan upstream tetap
  ditagih). Untuk streaming, penyimpanan terjadi setelah stream berakhir.
  Kegagalan menyimpan hanya dicatat di log dan tidak pernah merusak request user.
- Endpoint: `GET /api/v1/usage/breakdown` (milik sendiri) dan
  `GET /api/v1/admin/usage/breakdown?by_user=true|false` (seluruh tenant, admin saja).
  Keduanya menerima `since` dan `until`.
- Migrasi `0004_usage_events`. Menutup temuan audit #8.

Keterbatasan: yang tercatat hanya token yang dilaporkan provider; belum ada konversi ke biaya
(harga per model), dan panggilan yang gagal sebelum provider membalas tidak tercatat.
Event yang gagal disimpan hilang (best effort).

Belum (Fase 5+): RLS Postgres, OIDC/JWT, grant per role, harga per model.
